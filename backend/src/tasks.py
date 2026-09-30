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
    evaluation_mode,
)
from src.ingestion import ingest_document, ingest_key
from src.logging_config import log_analysis_run
from src.mechanism_adjudication import UNAVAILABLE
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
    """Deterministic scope disclaimer for one analysis run: two sentences
    saying the verdicts rest only on the documents supplied, never on the
    country's complete governance apparatus.

    The documents are counted rather than named. Their names are listed with
    the run (and in the brief's header), and naming four files here turned a
    two-line caveat into a paragraph. Document names come from the ingested
    chunks, so the count is what was actually evaluated.
    """
    docs = vector_store.get_workspace_documents(workspace_id) or []
    if len(docs) == 1:
        supplied = "the document supplied"
    elif docs:
        supplied = f"the {len(docs)} documents supplied"
    else:
        supplied = "the documents supplied"
    name = (country or "").strip()
    if not name:
        whose = "the country's"
    elif name.lower() in ("european union", "united kingdom", "republic of korea"):
        whose = f"the {name}'s"
    else:
        whose = f"{name}'s"
    disclaimer = (
        f"Scope: this assessment covers only {supplied}, not {whose} full AI "
        "governance framework. Instruments that were not supplied are outside "
        "it, so each verdict reflects that evidence alone."
    )
    return {
        "documents": docs,
        "disclaimer": disclaimer,
    }


def _get_db_session() -> AsyncSession:
    global _engine, _session_factory
    if _engine is None:
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


def reusable_cached_gaps(
    cached: dict[str, Any], made_now: dict[str, str], workspace_id: str
) -> dict[str, GovernanceGap]:
    """The cached dimensions this run may reuse instead of analysing again.

    A cached dimension is a result from an earlier attempt at this run, kept so
    a failure costs only what failed. It is reused only if it was made the way
    this run would make it — same model, same evaluation mode. Otherwise a
    resumed run stitches one model's or one mode's answers to another's, and
    nothing on the page says so. Each one dropped is logged: after a change of
    settings every run pays full price again, and that should not be silent.
    """
    reusable: dict[str, GovernanceGap] = {}
    for dim_name, data in cached.items():
        if data.get("status") != "completed" or not data.get("result"):
            continue
        made_then = data.get("provider") or {}
        if any(made_then.get(k) != v for k, v in made_now.items()):
            logger.warning(
                "cached_dimension_discarded",
                workspace_id=workspace_id,
                dimension=dim_name,
                error=f"made with {made_then}, this run uses {made_now}",
            )
            continue
        try:
            reusable[dim_name] = GovernanceGap(**data["result"])
        except Exception as exc:
            logger.warning(
                "cached_dimension_discarded",
                workspace_id=workspace_id,
                dimension=dim_name,
                error=str(exc),
            )
    return reusable


def cited_chunk_ids(records: Any) -> set[str]:
    """Every chunk id a stored analysis (or cached dimension) cites.

    Walks the stored JSON rather than naming fields, because citations sit in
    several places — evidence, three module-1/2 citation lists, roadmap
    citations, incident matches, international examples — and a field added
    later would otherwise be missed silently.
    """
    found: set[str] = set()
    stack = [records]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            cid = item.get("chunk_id")
            if isinstance(cid, str) and cid:
                found.add(cid)
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return found


async def run_full_analysis_pipeline(
    workspace_id: str,
    frameworks: list[str],
    documents: list[dict[str, str]] | None = None,
    file_path: str | None = None,
    file_name: str | None = None,
) -> dict[str, Any]:
    """Ingest every queued document, then score the workspace as one corpus.

    `documents` is [{"file_path": ..., "file_name": ...}]. The single
    file_path/file_name pair is the one-document form, accepted so a
    background task queued before a restart does not fail on signature.
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

        # Declared BEFORE the try: the except block below reads this to persist
        # whatever finished, including after a failure during ingestion.
        completed_dimensions: list[tuple[str, dict, dict]] = []

        try:
            await ws_service.update_status(workspace_id, WorkspaceStatus.PROCESSING)
            # Chunks the workspace's earlier runs cite. Re-reading a document
            # under newer ingestion rules replaces its chunks; these are kept
            # (retired, not deleted) so every stored run still resolves.
            earlier = await ws_service.get_analyses_for_workspace(workspace_id)
            still_cited = cited_chunk_ids([a.governance_gaps for a in earlier])
            still_cited |= cited_chunk_ids(await ws_service.get_dimension_results(workspace_id))

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
                # (PDF parsing, chunking, embedding), so they run in a worker
                # thread and the event loop stays free for other requests.
                # Resolved through the storage interface: a filesystem
                # reference yields the file in place, an Azure reference is
                # downloaded to a temporary file and cleaned up on exit.
                # ingest_document needs a real path because pypdf does.
                with (
                    get_storage().local_path(doc["file_path"]) as local_pdf,
                    metrics.timed_stage("ingest"),
                ):
                    key = await asyncio.to_thread(ingest_key, local_pdf)
                    stored = await asyncio.to_thread(
                        vector_store.stored_document_chunks, workspace_id, doc_name, key
                    )
                    if stored:
                        # The same file under the same rules: its chunks are
                        # already indexed, byte for byte, with the same ids.
                        chunks.extend(stored)
                        logger.info(
                            "pipeline_orchestration_document_reused",
                            workspace_id=workspace_id,
                            document_name=doc_name,
                            num_chunks=len(stored),
                        )
                        continue
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
                for c in doc_chunks:
                    c.metadata["ingest_key"] = key
                    c.metadata["ingest_total"] = len(doc_chunks)
                # Replace, don't append: a second copy in the workspace starves
                # retrieval with duplicates. Chunks an earlier run cites are
                # retired rather than deleted, so its citations still resolve.
                removed, retired = await asyncio.to_thread(
                    vector_store.retire_workspace_document,
                    workspace_id,
                    doc_name,
                    still_cited,
                    {c.chunk_id for c in doc_chunks},
                )
                if removed or retired:
                    logger.info(
                        "pipeline_orchestration_replaced_previous_copy",
                        workspace_id=workspace_id,
                        document_name=doc_name,
                        removed_chunks=removed,
                        retired_chunks=retired,
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
            existing_gaps = reusable_cached_gaps(
                existing_dim,
                {"provider": analyzer.provider.model_name, "evaluation": evaluation_mode()},
                workspace_id,
            )

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
            # minutes, so it runs off the event loop.
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
                # The per-module breakdown is logged by the analyzer, which
                # counted the calls; cached dimensions on a resumed run cost
                # nothing.
                total_llm_calls=result.llm_call_count,
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
            # persisted in the ragas_metrics JSON blob and surfaced by main.py's
            # GET /analyze response.
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
                llm_model=(getattr(result, "generated_by", None) or {}).get("provider"),
                llm_calls=result.llm_call_count,
            )
            analysis_dict["provenance"] = provenance
            analysis_dict["ragas_metrics"] = {
                "provenance": provenance,
                "llm_call_count": result.llm_call_count,
                "decision_analytics": result.decision_analytics,
                "consistency": result.consistency_report,
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
                # Deliberately NOT clearing dimension_results here: this cache
                # lets a re-run skip dimensions that already succeeded and
                # retry only the ones that failed.
            else:
                # Every dimension landed, but if mechanism adjudication did not
                # run, the depth stages rest on raw cue matches and can read
                # higher than they should. Complete, and said to be provisional.
                provisional = any(
                    g.mechanism_adjudication == UNAVAILABLE for g in result.governance_gaps
                )
                await ws_service.update_status(
                    workspace_id,
                    WorkspaceStatus.COMPLETE,
                    detail=(
                        f"Analysis complete. {cit_pass}/{len(citation_results)} citations verified."
                        + (
                            " Mechanism evidence could not be checked on this run, so "
                            "implementation depth is provisional; re-run to confirm it."
                            if provisional
                            else ""
                        )
                    ),
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
