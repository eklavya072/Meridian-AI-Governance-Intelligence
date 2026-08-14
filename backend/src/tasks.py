from __future__ import annotations

import os
import time
import structlog
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db_models import WorkspaceStatus
from src.workspace import WorkspaceService
from src.vectorstore import VectorStore
from src.ingestion import ingest_document
from src.gap_analyzer import GapAnalyzer, GapAnalysisResult, GovernanceGap, CoverageLevel, RiskLevel, GOVERNANCE_DIMENSIONS
from src.verify import verify_gap_analysis_citations
from src.brief_generator import generate_executive_brief_text
from src.logging_config import log_analysis_run

logger = structlog.get_logger()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://aura:aura@localhost:5432/aura_sdg")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")

_engine = None
_session_factory = None


def _build_scope_disclaimer(
    vector_store: VectorStore,
    workspace_id: str,
) -> dict[str, Any]:
    """Deterministic scope disclaimer for one analysis run.

    States plainly that the analysis evaluates ONLY the specific document(s)
    uploaded to this workspace, never the country's complete governance
    apparatus. Document names are derived from the actually-ingested chunks
    (metadata document_name), so multi-document workspaces list every input
    and single-document workspaces state the one document evaluated.
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
    return {
        "documents": docs,
        "disclaimer": disclaimer,
    }


def _get_db_session() -> AsyncSession:
    global _engine, _session_factory
    if _engine is None:
        sync_url = DATABASE_URL.replace("+asyncpg", "").replace("+psycopg2", "")
        _engine = create_async_engine(DATABASE_URL, echo=False)
        _session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _session_factory()


async def run_full_analysis_pipeline(
    workspace_id: str,
    file_path: str,
    file_name: str,
    frameworks: list[str],
) -> dict[str, Any]:
    start_time = time.time()
    logger.info(
        "pipeline_orchestration_started",
        workspace_id=workspace_id,
        file_path=file_path,
        file_name=file_name,
        frameworks=frameworks,
    )

    async with _get_db_session() as db:
        ws_service = WorkspaceService(db)

        try:
            await ws_service.update_status(workspace_id, WorkspaceStatus.PROCESSING)

            logger.info(
                "pipeline_orchestration_initializing",
                workspace_id=workspace_id,
                stage="vector_store_and_analyzer_init",
            )
            vector_store = VectorStore(persist_dir=CHROMA_PERSIST_DIR)
            analyzer = GapAnalyzer(vector_store=vector_store)

            path = Path(file_path)
            logger.info(
                "pipeline_orchestration_ingesting",
                workspace_id=workspace_id,
                stage="document_ingestion",
            )
            chunks = ingest_document(
                path,
                framework_name=None,
                workspace_id=workspace_id,
                # Clean display name for multi-document workspaces: the
                # UUID-prefixed storage filename would otherwise leak into the
                # prompt source labels and the evidence chain.
                document_name=file_name,
            )
            logger.info(
                "pipeline_orchestration_indexing",
                workspace_id=workspace_id,
                stage="vector_store_indexing",
                num_chunks=len(chunks),
            )
            vector_store.add_chunks(chunks)

            await ws_service.update_status(
                workspace_id, WorkspaceStatus.PROCESSING,
                detail="Ingestion complete. Starting analysis."
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

            completed_dimensions: list[tuple[str, dict, dict]] = []

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
            result: GapAnalysisResult = analyzer.analyze(
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
                covered=sum(1 for g in result.governance_gaps if g.coverage == CoverageLevel.COVERED),
                partial=sum(1 for g in result.governance_gaps if g.coverage == CoverageLevel.PARTIAL),
                missing=sum(1 for g in result.governance_gaps if g.coverage == CoverageLevel.MISSING),
                failed=sum(1 for g in result.governance_gaps if g.analysis_error),
            )

            for dim_name, gap_dict, p_info in completed_dimensions:
                await ws_service.update_dimension_result(
                    workspace_id, dim_name, gap_dict, p_info,
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
            total_evidence_items = sum(len(gap.evidence) for gap in result.governance_gaps)
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
                workspace_id, WorkspaceStatus.GENERATING_REPORT,
                detail="Analysis complete. Generating report."
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
            scope_disclaimer = _build_scope_disclaimer(vector_store, workspace_id)
            analysis_dict["ragas_metrics"] = {
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
                    workspace_id, WorkspaceStatus.COMPLETE,
                    detail=(
                        f"Analysis complete but {len(failed_dims)} dimension(s) failed "
                        f"({', '.join(failed_dims)}): LLM/provider error. "
                        f"{cit_pass}/{len(citation_results)} citations verified. "
                        "Re-run when quota is available for a full result."
                    ),
                )
            else:
                await ws_service.update_status(
                    workspace_id, WorkspaceStatus.COMPLETE,
                    detail=f"Analysis complete. {cit_pass}/{len(citation_results)} citations verified."
                )

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
                    workspace_id, dim_name, gap_dict, p_info,
                )
            await ws_service.update_status(
                workspace_id, WorkspaceStatus.ERROR,
                detail=f"Pipeline error: {exc}",
            )
            return {
                "status": "error",
                "error": str(exc),
            }
