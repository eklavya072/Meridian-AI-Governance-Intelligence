from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src import metrics
from src.db_models import WorkspaceStatus
from src.gap_analyzer import (
    CoverageLevel,
    GapAnalysisResult,
    GapAnalyzer,
    GovernanceGap,
)
from src.ingestion import ingest_document
from src.logging_config import log_analysis_run
from src.provenance import build_provenance
from src.storage import get_storage
from src.vectorstore import VectorStore
from src.verify import verify_gap_analysis_citations
from src.workspace import WorkspaceService

logger = structlog.get_logger()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://aura:aura@localhost:5432/aura_sdg")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")

_engine = None
_session_factory = None


def _build_scope_disclaimer(
    vector_store: VectorStore,
    workspace_id: str,
    country: str = "",
) -> dict[str, Any]:
    """Deterministic scope disclaimer for one analysis run.

    States plainly that the analysis evaluates ONLY the specific document(s)
    uploaded to this workspace, never the country's complete governance
    apparatus. Document names are derived from the actually-ingested chunks
    (metadata document_name), so multi-document workspaces list every input
    and single-document workspaces state the one document evaluated.

    Companion-instrument scope note (deterministic, document-name based —
    never an LLM judgment): when a country's governance for a dimension
    lives in a separate statute, an analysis of the uploaded document alone
    would silently understate that dimension. Korea's personal-data
    governance is in the Personal Information Protection Act (PIPA), not the
    AI Basic Act — if PIPA is not among the ingested documents, the Privacy
    dimension is scope-limited and the disclaimer says so explicitly.
    """
    docs = vector_store.get_workspace_documents(workspace_id) or []
    if len(docs) == 1:
        doc_clause = f"the provided document ({docs[0]})"
    elif len(docs) > 1:
        doc_clause = "the provided documents (" + ", ".join(docs) + ")"
    else:
        # Defensive: no document_name metadata found (e.g. all-old chunks or
        # an empty workspace) — never render an empty parenthetical.
        doc_clause = "the document(s) provided to the system"
    disclaimer = (
        f"Scope: this assessment evaluates {doc_clause}. "
        "It is not an assessment of the country's complete AI governance "
        "apparatus — governance instruments not provided to the system are "
        "outside this evaluation, and coverage verdicts should be read as "
        "relative to the evidence supplied."
    )
    pipa_absent = not any(
        re.search(r"pipa|personal information protection", d, re.IGNORECASE) for d in docs
    )
    if (country or "").lower() in ("south korea", "korea", "republic of korea") and pipa_absent:
        disclaimer += (
            " Note: Korea's personal-data governance lives primarily in the "
            "Personal Information Protection Act (PIPA), which is not among "
            "the provided documents — the Privacy dimension reflects only the "
            "uploaded document's own data provisions and is a scope-limited "
            "assessment, not an evaluation of Korea's privacy regime."
        )
    return {
        "documents": docs,
        "disclaimer": disclaimer,
    }


def _get_db_session() -> AsyncSession:
    global _engine, _session_factory
    if _engine is None:
        DATABASE_URL.replace("+asyncpg", "").replace("+psycopg2", "")
        _engine = create_async_engine(DATABASE_URL, echo=False)
        _session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _session_factory()


# Storage filenames routinely carry one or more uuid4 prefixes from the upload
# path ("f3e3617d-...-c052cd62d574_Artificial_Intelligence_Policy.pdf").
# document_name is user-facing — it is what the report lists under "documents
# evaluated" — so strip the prefixes before they reach the vector store
# metadata and the analysis output.
_UPLOAD_UUID_PREFIX_RE = re.compile(
    r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}_)+"
)


def _display_name(file_name: str | None) -> str:
    return _UPLOAD_UUID_PREFIX_RE.sub("", file_name or "") or (file_name or "document.pdf")


async def run_full_analysis_pipeline(
    workspace_id: str,
    frameworks: list[str],
    documents: list[dict[str, str]] | None = None,
    file_path: str | None = None,
    file_name: str | None = None,
) -> dict[str, Any]:
    """Ingest every queued document, then score the workspace as one corpus.

    `documents` is the current shape: [{"file_path": ..., "file_name": ...}].
    The single file_path/file_name pair is the older one-document call and is
    still accepted so an in-flight background task queued before a restart
    does not fail on signature.
    """
    if not documents:
        if not file_path:
            raise ValueError("run_full_analysis_pipeline needs at least one document")
        documents = [{"file_path": file_path, "file_name": file_name or "document.pdf"}]

    start_time = time.time()
    logger.info(
        "pipeline_orchestration_started",
        workspace_id=workspace_id,
        documents=[d.get("file_name") for d in documents],
        document_count=len(documents),
        frameworks=frameworks,
    )

    async with _get_db_session() as db:
        ws_service = WorkspaceService(db)

        # Declared BEFORE the try. The except block below reads this to
        # persist whatever finished, and it used to be assigned only after
        # ingestion — so any failure during ingestion (a corrupt PDF, a
        # missing file, an unreachable vector store) made the handler itself
        # raise UnboundLocalError. That masked the real error AND skipped the
        # update_status(ERROR) call, leaving the workspace wedged in
        # PROCESSING with nothing to explain why.
        completed_dimensions: list[tuple[str, dict, dict]] = []

        try:
            await ws_service.update_status(workspace_id, WorkspaceStatus.PROCESSING)

            logger.info(
                "pipeline_orchestration_initializing",
                workspace_id=workspace_id,
                stage="vector_store_and_analyzer_init",
            )
            vector_store = VectorStore(persist_dir=CHROMA_PERSIST_DIR)
            analyzer = GapAnalyzer(vector_store=vector_store)

            logger.info(
                "pipeline_orchestration_ingesting",
                workspace_id=workspace_id,
                stage="document_ingestion",
                document_count=len(documents),
            )
            # Every queued document is ingested BEFORE any scoring runs, and
            # their chunks are pooled. Scoring a workspace one file at a time
            # would let the last upload define the verdict while the earlier
            # ones only ever showed up as retrieval noise.
            chunks = []
            document_names: list[str] = []
            for doc in documents:
                doc_name = _display_name(doc.get("file_name"))
                document_names.append(doc_name)
                # ingest_document / add_chunks are synchronous, CPU-bound calls
                # (PDF parsing, chunking, embedding). Calling them directly here
                # would block this single-threaded event loop for the entire
                # pipeline's duration — every other request (GET /workspace,
                # GET /workspace/{id}, chat, etc.) would hang until the pipeline
                # finished, which is why the workspace list appeared to "vanish"
                # on reload while an analysis was running. Running them via
                # to_thread hands the blocking work to a worker thread so the
                # event loop stays free to serve concurrent requests.
                # Resolved through the storage interface: a filesystem
                # reference yields the file in place, an Azure reference is
                # downloaded to a temporary file and cleaned up on exit.
                # ingest_document needs a real path because pypdf does.
                with (
                    get_storage().local_path(doc["file_path"]) as local_pdf,
                    metrics.timed_stage("ingest"),
                ):
                    doc_chunks = await asyncio.to_thread(
                        ingest_document,
                        local_pdf,
                        framework_name=None,
                        workspace_id=workspace_id,
                        # Clean display name for multi-document workspaces:
                        # the UUID-prefixed storage filename would otherwise
                        # leak into the prompt source labels and the evidence
                        # chain.
                        document_name=doc_name,
                    )
                # Replace, don't append. Chunk ids are fresh uuid4s per
                # ingestion, so re-uploading a document would otherwise stack a
                # second full copy into the workspace and starve retrieval with
                # duplicates — see delete_workspace_document for the measured
                # impact.
                removed = await asyncio.to_thread(
                    vector_store.delete_workspace_document, workspace_id, doc_name
                )
                if removed:
                    logger.info(
                        "pipeline_orchestration_replaced_previous_copy",
                        workspace_id=workspace_id,
                        document_name=doc_name,
                        removed_chunks=removed,
                    )
                with metrics.timed_stage("index"):
                    await asyncio.to_thread(vector_store.add_chunks, doc_chunks)
                metrics.chunks_indexed.inc(len(doc_chunks))
                metrics.documents_ingested.labels(outcome="ok").inc()
                chunks.extend(doc_chunks)
                logger.info(
                    "pipeline_orchestration_document_indexed",
                    workspace_id=workspace_id,
                    document_name=doc_name,
                    num_chunks=len(doc_chunks),
                )

            file_name = " + ".join(document_names) if document_names else "document.pdf"
            logger.info(
                "pipeline_orchestration_indexing",
                workspace_id=workspace_id,
                stage="vector_store_indexing",
                num_chunks=len(chunks),
                documents=document_names,
            )

            await ws_service.update_status(
                workspace_id,
                WorkspaceStatus.PROCESSING,
                detail="Ingestion complete. Starting analysis.",
            )

            full_text = "\n".join(c.text for c in chunks)
            full_text_length = len(full_text)

            existing_dim = await ws_service.get_dimension_results(workspace_id)
            existing_gaps: dict[str, GovernanceGap] = {}
            for dim_name, data in existing_dim.items():
                if data.get("status") == "completed" and data.get("result"):
                    try:
                        existing_gaps[dim_name] = GovernanceGap(**data["result"])
                    except Exception:
                        pass

            def on_dimension(dim: str, gap: GovernanceGap, provider_info: dict) -> None:
                completed_dimensions.append((dim, gap.model_dump(), provider_info))

            logger.info(
                "pipeline_orchestration_analysis",
                workspace_id=workspace_id,
                stage="gap_analysis",
                document_length=full_text_length,
                num_chunks_for_analysis=len(chunks),
                existing_dimensions=len(existing_gaps),
            )
            # Deterministic regional routing needs the workspace country
            # (set at workspace creation), never an LLM guess.
            ws = await ws_service.get_workspace(workspace_id)
            ws_country = (ws.country if ws else None) or ""
            logger.info(
                "pipeline_orchestration_country_resolved",
                workspace_id=workspace_id,
                country=ws_country,
            )
            # Same reasoning as above: analyze() is synchronous and runs for
            # minutes (up to 16 LLM calls across 8 dimensions). Off the event
            # loop, via to_thread, so the workspace list and status polling
            # keep working for the whole duration of the run.
            with metrics.timed_stage("analyse"):
                result: GapAnalysisResult = await asyncio.to_thread(
                    analyzer.analyze,
                    document_text=full_text,
                    document_name=file_name,
                    workspace_id=workspace_id,
                    frameworks=frameworks,
                    existing_results=existing_gaps if existing_gaps else None,
                    dimension_callback=on_dimension,
                    country=ws_country,
                )
            logger.info(
                "pipeline_orchestration_analysis_complete",
                workspace_id=workspace_id,
                stage="gap_analysis_complete",
                dimensions_analyzed=len(result.governance_gaps),
                # Real call count: 8 combined Module 1+2 calls + 1 conditional
                # Module 3+4 call per Partial/Missing dimension (Fully Covered
                # dimensions cost exactly one call). Reported so quota usage
                # is observable against the ~8 + up to 8 = up to 16 budget.
                total_llm_calls=result.llm_call_count,
                module34_calls=result.llm_call_count - len(result.governance_gaps),
                covered=sum(
                    1 for g in result.governance_gaps if g.coverage == CoverageLevel.COVERED
                ),
                partial=sum(
                    1 for g in result.governance_gaps if g.coverage == CoverageLevel.PARTIAL
                ),
                missing=sum(
                    1 for g in result.governance_gaps if g.coverage == CoverageLevel.MISSING
                ),
                failed=sum(1 for g in result.governance_gaps if g.analysis_error),
            )

            for dim_name, gap_dict, p_info in completed_dimensions:
                await ws_service.update_dimension_result(
                    workspace_id,
                    dim_name,
                    gap_dict,
                    p_info,
                )

            doc_total_pages = 0
            if chunks:
                page_nums = [c.page_number for c in chunks if c.page_number]
                doc_total_pages = max(page_nums) if page_nums else 0

            logger.info(
                "pipeline_orchestration_citation_verification",
                workspace_id=workspace_id,
                stage="citation_verification",
            )
            citation_results = []
            sum(len(gap.evidence) for gap in result.governance_gaps)
            for gap in result.governance_gaps:
                ev_dicts = [e.model_dump() for e in gap.evidence]
                verified = verify_gap_analysis_citations(
                    {"evidence": ev_dicts},
                    vector_store,
                    document_total_pages=doc_total_pages,
                )
                # Map verification results back into the gap's evidence items
                verified_by_id = {v["chunk_id"]: v for v in verified}
                for ev_item in gap.evidence:
                    v = verified_by_id.get(ev_item.chunk_id)
                    if v:
                        ev_item.verified = v.get("verified", False)
                        ev_item.verification = v.get("verification")
                citation_results.extend(verified)

                # NOTE: Module 1 + Module 2 citation fields are verified inside
                # GapAnalyzer._verify_module_citations, which calls verify.py's
                # verify_citation; the in-memory gaps already carry verified
                # flags before the dimension_callback persists them. No
                # re-verification here.

            cit_pass = sum(1 for c in citation_results if c.get("verified", False))
            cit_fail = sum(1 for c in citation_results if not c.get("verified", False))
            # The evidence gate's own pass rate. A prompt change that starts
            # producing citations which no longer resolve moves this before
            # anyone reads a brief.
            metrics.record_citation_results(citation_results)
            for gap in result.governance_gaps:
                metrics.coverage_verdicts.labels(
                    verdict=getattr(gap.coverage, "value", str(gap.coverage)),
                    dimension=gap.dimension,
                ).inc()

            log_analysis_run(
                analysis_id=result.analysis_id,
                retrieval_count=result.total_retrieved,
                frameworks_queried=frameworks,
                similarity_scores=result.similarity_scores,
                citation_results=citation_results,
                llm_latency=result.llm_latency,
                total_processing_time=time.time() - start_time,
            )

            logger.info(
                "pipeline_orchestration_report_generation",
                workspace_id=workspace_id,
                stage="report_generation",
                citation_pass=cit_pass,
                citation_fail=cit_fail,
                total_citations=len(citation_results),
            )
            await ws_service.update_status(
                workspace_id,
                WorkspaceStatus.GENERATING_REPORT,
                detail="Analysis complete. Generating report.",
            )

            analysis_dict = result.model_dump()
            analysis_dict["generated_by"] = result.generated_by
            analysis_dict["citation_verification"] = {
                "total": len(citation_results),
                "passed": cit_pass,
                "failed": cit_fail,
                "details": citation_results,
            }
            # Analysis-level metrics the DB has no dedicated columns for are
            # persisted in the ragas_metrics JSON blob (already a nullable
            # JSON column) and surfaced by main.py's GET /analyze response,
            # so the frontend can render the call-count / decision-analytics
            # cards instead of reading fields that never arrive.
            # Deterministic scope disclaimer (never LLM-generated): the
            # analysis evaluates ONLY the specific document(s) uploaded to this
            # workspace — never a country's complete governance apparatus.
            # Document names come from the actual ingested chunks, so a
            # multi-document workspace (e.g. NAIS + Model AI Governance
            # Framework) lists every evaluated input.
            scope_disclaimer = _build_scope_disclaimer(
                vector_store, workspace_id, country=ws_country
            )
            # Persisted with the analysis so an auditor can ask what produced
            # a verdict without needing to know which build was deployed.
            provenance = build_provenance(
                llm_model=getattr(result, "generated_by", None),
                llm_calls=result.llm_call_count,
            )
            analysis_dict["provenance"] = provenance
            analysis_dict["ragas_metrics"] = {
                "provenance": provenance,
                "llm_call_count": result.llm_call_count,
                "tier_stats": result.tier_stats,
                "decision_analytics": result.decision_analytics,
                "scope_disclaimer": scope_disclaimer,
                "evaluated_documents": scope_disclaimer["documents"],
            }
            await ws_service.save_analysis(analysis_dict)
            logger.info(
                "pipeline_orchestration_report_saved",
                workspace_id=workspace_id,
                stage="analysis_saved",
                analysis_id=result.analysis_id,
            )

            # If any dimension failed analysis (LLM quota/provider error), say
            # so plainly instead of reporting a clean COMPLETE. Partial results
            # are still saved and viewable.
            failed_dims = [g.dimension for g in result.governance_gaps if g.analysis_error]
            if failed_dims:
                await ws_service.update_status(
                    workspace_id,
                    WorkspaceStatus.COMPLETE,
                    detail=(
                        f"Analysis complete but {len(failed_dims)} dimension(s) failed "
                        f"({', '.join(failed_dims)}): LLM/provider error. "
                        f"{cit_pass}/{len(citation_results)} citations verified. "
                        "Re-run when quota is available for a full result."
                    ),
                )
                # Deliberately NOT clearing dimension_results here. This cache is
                # what lets a re-upload skip dimensions that already succeeded
                # (see the existing_dim/existing_gaps load near the top of this
                # function) and only retry the ones that actually failed.
                # Clearing it unconditionally (the old behaviour) wiped every
                # successful dimension's result the moment the run finished —
                # so the NEXT re-upload re-analyzed all 8 dimensions from
                # scratch instead of just the failed ones, burning far more
                # quota than needed and making which dimensions happened to
                # succeed pure luck-of-the-draw each retry, including ones
                # that had just succeeded seconds earlier.
            else:
                await ws_service.update_status(
                    workspace_id,
                    WorkspaceStatus.COMPLETE,
                    detail=f"Analysis complete. {cit_pass}/{len(citation_results)} citations verified.",
                )
                # Only safe to drop the scratch cache once every dimension is
                # clean — nothing left that a future re-run would need to skip.
                await ws_service.clear_dimension_results(workspace_id)

            logger.info(
                "pipeline_orchestration_complete",
                workspace_id=workspace_id,
                stage="pipeline_finished",
                total_time=time.time() - start_time,
                analysis_id=result.analysis_id,
                document_name=file_name,
                total_retrieved=result.total_retrieved,
                framed_with=frameworks,
            )

            metrics.analysis_runs.labels(outcome="complete").inc()
            return {
                "status": "complete",
                "analysis_id": result.analysis_id,
                "citation_pass": cit_pass,
                "citation_fail": cit_fail,
                "processing_time": time.time() - start_time,
            }

        except Exception as exc:
            logger.error(
                "pipeline_orchestration_failed",
                workspace_id=workspace_id,
                stage="pipeline_error",
                file_name=file_name,
                frameworks=frameworks,
                error=str(exc),
                error_type=type(exc).__name__,
                completed_dimensions=list(completed_dimensions),
            )
            for dim_name, gap_dict, p_info in completed_dimensions:
                await ws_service.update_dimension_result(
                    workspace_id,
                    dim_name,
                    gap_dict,
                    p_info,
                )
            await ws_service.update_status(
                workspace_id,
                WorkspaceStatus.ERROR,
                detail=f"Pipeline error: {exc}",
            )
            metrics.analysis_runs.labels(outcome="error").inc()
            return {
                "status": "error",
                "error": str(exc),
            }
