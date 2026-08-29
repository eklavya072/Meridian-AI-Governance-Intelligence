from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from dotenv import load_dotenv
from sqlalchemy import select as sa_select
from sqlalchemy import text as sa_text

load_dotenv()

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.brief_export import render_docx, render_pdf
from src.brief_generator import generate_executive_brief_text
from src.brief_synthesis import generate_brief as generate_brief_v2
from src.brief_synthesis import render_brief_markdown
from src.chat import chat as chat_fn
from src.db_models import Base, ChatMessage, ChatSession, Report, WorkspaceStatus
from src.framework_library import get_framework_library
from src.framework_sync import FrameworkSyncService
from src.guardrails import Guardrails
from src.logging_config import log_upload_rejection, setup_logging
from src.validation import validate_pdf_file
from src.vectorstore import VectorStore
from src.workspace import WorkspaceService

setup_logging()
logger = structlog.get_logger()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://aura:aura@localhost:5432/aura_sdg")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
UPLOAD_DIR = Path(__file__).parent / "data" / "uploads"
# Comma-separated list of allowed browser origins (e.g. "https://app.example.com,http://localhost:3000")
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if o.strip()
]

_engine = None
_session_factory = None
_vector_store: VectorStore | None = None
_guardrails: Guardrails | None = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(persist_dir=CHROMA_PERSIST_DIR)
    return _vector_store


def get_guardrails() -> Guardrails:
    global _guardrails
    if _guardrails is None:
        _guardrails = Guardrails(vector_store=get_vector_store())
    return _guardrails


@asynccontextmanager
async def get_db():
    """DB session as a proper async context manager.

    Every call site uses `async with get_db() as db: ...; return X` (see the
    handlers below). This used to be a bare async generator consumed via
    `async for db in get_db(): ...; return X` — returning from inside that
    loop abandons the generator without ever running its `finally`/`__aexit__`
    cleanup (Python only closes an async generator eagerly when it's fully
    exhausted or explicitly `.aclose()`d; an early `return` just drops the
    reference and leaves cleanup to eventual GC, which asyncio does not
    guarantee promptly). Under sustained polling (the workspace/analysis
    pages poll every few seconds) that leaked one pooled connection per
    request, and once the pool (5 + 10 overflow = 15 connections) was
    exhausted every subsequent request — including simple GETs with nothing
    to do with the running analysis pipeline — hung forever waiting for a
    connection that was never coming back. `@asynccontextmanager` guarantees
    `__aexit__` (and therefore the session close) runs the moment the `async
    with` block exits, return statement or not.
    """
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_async_engine(DATABASE_URL, echo=False)
        _session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    async with _session_factory() as session:
        yield session


@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    global _engine, _session_factory
    _engine = create_async_engine(DATABASE_URL, echo=False)
    _session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Idempotent schema top-ups for databases that predate a given build.
    # create_all only creates missing TABLES; it never alters existing ones.
    #
    # Each statement gets its OWN transaction, and that is the whole point.
    # Postgres aborts an entire transaction on the first failed statement, and
    # "ALTER TYPE ... ADD VALUE" cannot run inside a transaction block at all —
    # so when these all shared one `begin()` block, that single failure poisoned
    # the connection and the block's commit turned into a rollback, discarding
    # every migration that had already succeeded. They looked fine in the logs
    # (each failure was caught and warned individually) while none of them
    # actually applied.
    migrations: list[tuple[str, str]] = [
        # chat_sessions.mode is new in Part 3.
        (
            "chat_sessions_mode",
            "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS "
            "mode VARCHAR(50) DEFAULT 'advisor' NOT NULL",
        ),
        # Mode A (general) sessions have no workspace scope.
        (
            "chat_sessions_workspace_nullable",
            "ALTER TABLE chat_sessions ALTER COLUMN workspace_id DROP NOT NULL",
        ),
        # Executive brief (Part 3): a generated brief is cached as structured
        # JSON in meta plus markdown in content, so exporting it does not
        # re-run the synthesis LLM call.
        ("reports_content", "ALTER TABLE reports ADD COLUMN IF NOT EXISTS content TEXT"),
        ("reports_meta", "ALTER TABLE reports ADD COLUMN IF NOT EXISTS meta JSON"),
        # Upload and "Run Analysis" are separate actions, so a workspace has
        # to remember which files are waiting to be analysed between the two.
        (
            "workspaces_pending_documents",
            "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS pending_documents JSON",
        ),
        # AI Auditor: workspaces used for document chat only carry the
        # chat_only status (ingested for chat, never analysed).
        # NOTE: SQLAlchemy's SAEnum(WorkspaceStatus) serializes the MEMBER NAME
        # (the existing type holds 'QUEUED'/'COMPLETE'/'ERROR'), so the added
        # value must be 'CHAT_ONLY' — a lowercase 'chat_only' would never match
        # what SQLAlchemy emits and every chat_only insert would fail.
        (
            "workspacestatus_chat_only",
            "ALTER TYPE workspacestatus ADD VALUE IF NOT EXISTS 'CHAT_ONLY'",
        ),
    ]
    # AUTOCOMMIT so ALTER TYPE ... ADD VALUE is not wrapped in a transaction
    # block, which Postgres rejects outright.
    autocommit = await _engine.connect()
    autocommit = await autocommit.execution_options(isolation_level="AUTOCOMMIT")
    try:
        for name, statement in migrations:
            try:
                await autocommit.execute(sa_text(statement))
            except Exception as exc:
                # Already-applied migrations are the normal case here; a real
                # problem shows up as the next query failing on a missing
                # column, so log loudly enough to connect the two.
                logger.warning("schema_migration_skipped", migration=name, error=str(exc))
    finally:
        await autocommit.close()

    logger.info("database_tables_created")

    # Reclaim workspaces the last process died holding.
    #
    # The analysis worker runs in-process, so nothing that was mid-run can
    # possibly have survived a restart — yet its row still says "processing",
    # and the run endpoint refuses to start a second analysis for a workspace
    # already in that state. A crash therefore wedged the workspace forever:
    # the page polled a job with no worker behind it, and the only way back
    # was editing the database by hand.
    #
    # A row in "processing" at startup is orphaned by definition, so it is
    # safe to reset here. The two live states resolve differently: a
    # "processing" workspace lost its analysis and goes back to "queued" so
    # the user can re-run it, while "generating_report" had already finished
    # analysing and only lost the brief, so it returns to "complete" rather
    # than throwing that work away.
    #
    # The literals are upper-case because the Postgres enum's labels are the
    # Python member NAMES, not their lower-case values.
    reclaim = await _engine.connect()
    reclaim = await reclaim.execution_options(isolation_level="AUTOCOMMIT")
    try:
        for name, statement in (
            (
                "processing",
                "UPDATE workspaces SET status = 'QUEUED', status_detail = "
                "'Interrupted by a server restart. Run the analysis again.' "
                "WHERE status = 'PROCESSING'",
            ),
            (
                "generating_report",
                "UPDATE workspaces SET status = 'COMPLETE', status_detail = "
                "'Analysis complete. Brief generation was interrupted by a "
                "server restart.' WHERE status = 'GENERATING_REPORT'",
            ),
        ):
            try:
                result = await reclaim.execute(sa_text(statement))
                if result.rowcount:
                    logger.info(
                        "orphaned_workspaces_reclaimed",
                        previous_status=name,
                        count=result.rowcount,
                    )
            except Exception as exc:
                logger.warning(
                    "orphaned_workspace_reclaim_failed",
                    previous_status=name,
                    error=str(exc),
                )
    finally:
        await reclaim.close()

    vs = get_vector_store()
    # Warm the per-framework chunk counts while the process is already starting
    # up. Building them costs one sweep of the collection; paying it here means
    # the first request to /frameworks — which the Analysis page issues on
    # mount — is served from cache instead of blocking a user for ~5 seconds.
    #
    # Skippable, because the try/except below cannot catch the way this
    # actually fails on a constrained machine. The sweep holds the whole
    # collection in memory, and when the OS kills the process for it there is
    # no exception to catch — the worker dies with no traceback while the
    # reloader keeps holding port 8000, so the API looks up and answers
    # nothing. Set WARM_FRAMEWORK_COUNTS=0 to trade a slower first
    # /frameworks call for a start that survives memory pressure.
    if os.getenv("WARM_FRAMEWORK_COUNTS", "1").strip().lower() not in ("0", "false", "no"):
        try:
            from src.framework_library import _framework_chunk_counts

            await asyncio.to_thread(_framework_chunk_counts, vs)
            logger.info("framework_counts_warmed")
        except Exception as exc:
            # Purely an optimisation; a failure here must never stop the app.
            logger.warning("framework_counts_warm_failed", error=str(exc))
    else:
        logger.info("framework_counts_warm_skipped")
    yield
    if _engine:
        await _engine.dispose()


app = FastAPI(
    title="Meridian — AI Policy Intelligence Workbench",
    description="UNDP DAI Hub: Policy gap analysis against international AI governance frameworks.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Schemas ---


class WorkspaceCreate(BaseModel):
    country: str
    policy_title: str
    # Framework selection is deterministic (per-dimension + region routing in
    # backend code) — the client no longer chooses frameworks. Kept optional
    # with a default so old clients and stored workspaces keep working.
    frameworks: list[str] = []


class WorkspaceResponse(BaseModel):
    id: str
    country: str
    policy_title: str
    frameworks: list[str]
    status: str
    status_detail: str | None = None
    # Filenames uploaded but not yet analysed. Drives the workspace card's
    # "Run Analysis" affordance, so it must survive a page reload.
    pending_documents: list[str] = []
    created_at: str
    updated_at: str


class AnalysisResponse(BaseModel):
    analysis_id: str
    workspace_id: str
    document_name: str
    frameworks_used: list[str]
    governance_gaps: list[dict[str, Any]]
    summary: str
    total_retrieved: int
    total_processing_time: float


class BriefRequest(BaseModel):
    workspace_id: str


# --- Routes ---


@app.get("/api/v1/health")
async def health():
    vs = get_vector_store()
    chunk_count = vs.count_chunks()
    frameworks = vs.get_all_frameworks()
    return {
        "status": "ok",
        "service": "meridian-api",
        "version": "1.0.0",
        "vector_store": {
            "chunks": chunk_count,
            "frameworks": frameworks,
        },
    }


@app.get("/api/v1/frameworks")
async def list_frameworks():
    vs = get_vector_store()
    return get_framework_library(vs)


@app.post("/api/v1/frameworks/sync")
async def sync_frameworks():
    vs = get_vector_store()
    sync_service = FrameworkSyncService(vs)
    results = sync_service.sync_all()
    return {"frameworks_synced": len(results), "results": results}


@app.post("/api/v1/workspace", response_model=WorkspaceResponse)
async def create_workspace(body: WorkspaceCreate):
    async with get_db() as db:
        ws_service = WorkspaceService(db)
        workspace = await ws_service.create_workspace(
            country=body.country,
            policy_title=body.policy_title,
            frameworks=body.frameworks,
        )
        return WorkspaceResponse(
            id=str(workspace.id),
            country=workspace.country,
            policy_title=workspace.policy_title,
            frameworks=workspace.frameworks,
            status=workspace.status.value,
            status_detail=workspace.status_detail,
            pending_documents=[d.get("file_name", "") for d in (workspace.pending_documents or [])],
            created_at=workspace.created_at.isoformat() if workspace.created_at else "",
            updated_at=workspace.updated_at.isoformat() if workspace.updated_at else "",
        )


@app.get("/api/v1/workspace")
async def list_workspaces():
    async with get_db() as db:
        ws_service = WorkspaceService(db)
        workspaces = await ws_service.list_workspaces()
        return [
            WorkspaceResponse(
                id=str(w.id),
                country=w.country,
                policy_title=w.policy_title,
                frameworks=w.frameworks,
                status=w.status.value,
                status_detail=w.status_detail,
                pending_documents=[d.get("file_name", "") for d in (w.pending_documents or [])],
                created_at=w.created_at.isoformat() if w.created_at else "",
                updated_at=w.updated_at.isoformat() if w.updated_at else "",
            )
            for w in workspaces
        ]


@app.get("/api/v1/workspace/{workspace_id}")
async def get_workspace(workspace_id: str):
    async with get_db() as db:
        ws_service = WorkspaceService(db)
        workspace = await ws_service.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(404, "Workspace not found")
        return WorkspaceResponse(
            id=str(workspace.id),
            country=workspace.country,
            policy_title=workspace.policy_title,
            frameworks=workspace.frameworks,
            status=workspace.status.value,
            status_detail=workspace.status_detail,
            pending_documents=[d.get("file_name", "") for d in (workspace.pending_documents or [])],
            created_at=workspace.created_at.isoformat() if workspace.created_at else "",
            updated_at=workspace.updated_at.isoformat() if workspace.updated_at else "",
        )


@app.post("/api/v1/upload/{workspace_id}")
async def upload_policy(
    workspace_id: str,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    file_bytes = await file.read()
    file_size = len(file_bytes)
    file_type = "pdf" if file.filename and file.filename.lower().endswith(".pdf") else "unknown"
    logger.info(
        "stage_1_file_upload_received",
        filename=file.filename or "unknown",
        file_type=file_type,
        file_size=file_size,
        workspace_id=workspace_id,
    )

    validation = validate_pdf_file(file_bytes, file.filename or "document.pdf")
    if not validation.valid:
        log_upload_rejection(
            filename=file.filename or "unknown",
            error_type=validation.error_type or "validation_failed",
            error_message=validation.error_message or "Validation failed.",
        )
        logger.error(
            "stage_1_file_upload_rejected",
            filename=file.filename or "unknown",
            error_type=validation.error_type,
            error_message=validation.error_message,
            ocr_warning=validation.ocr_warning,
            workspace_id=workspace_id,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": validation.error_type,
                "message": validation.error_message,
                "ocr_warning": validation.ocr_warning,
            },
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / f"{uuid.uuid4()}_{file.filename}"
    file_path.write_bytes(file_bytes)
    logger.info(
        "stage_1_file_upload_saved",
        filename=file.filename,
        file_size=file_size,
        saved_path=str(file_path),
        workspace_id=workspace_id,
    )

    async with get_db() as db:
        ws_service = WorkspaceService(db)
        workspace = await ws_service.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(404, "Workspace not found")

        # Uploading no longer starts the pipeline. The file is queued on the
        # workspace and waits for an explicit POST to /analyze/{id}/run, which
        # is what lets a user attach a second document (a strategy and its
        # implementation plan, say) and have both evaluated as one body of
        # policy instead of the first upload racing ahead on its own.
        pending = list(workspace.pending_documents or [])
        file_label = file.filename or "document.pdf"
        # Re-uploading the same filename replaces the earlier copy rather than
        # queueing it twice — the pipeline would otherwise ingest, then
        # immediately delete and re-index, the same document.
        pending = [d for d in pending if d.get("file_name") != file_label]
        pending.append({"file_path": str(file_path), "file_name": file_label})

        await ws_service.set_pending_documents(workspace_id, pending)
        await ws_service.update_status(
            workspace_id,
            WorkspaceStatus.QUEUED,
            detail=(f"{len(pending)} document(s) ready. Run analysis to start."),
        )
        await ws_service.log_upload(
            filename=file_label,
            file_size=len(file_bytes),
            validation_passed=True,
            workspace_id=workspace_id,
            ocr_warning=validation.ocr_warning,
        )

    return {
        "status": "ready",
        "message": "Upload accepted. Run analysis when your documents are ready.",
        "workspace_id": workspace_id,
        "file_name": file_label,
        "file_size": len(file_bytes),
        "pending_documents": [d["file_name"] for d in pending],
    }


@app.post("/api/v1/auditor/upload")
async def auditor_upload(file: UploadFile = File(...)):
    """AI Auditor: ingest an AI policy PDF for chat ONLY — no dimension
    analysis pipeline is run (that is the workspace flow's job). Creates a
    chat_only workspace, ingests the document chunks tagged to it, and hands
    the workspace id back so the merged auditor chat can scope document
    retrieval to it."""
    file_bytes = await file.read()
    file_name = file.filename or "document.pdf"
    logger.info(
        "auditor_upload_received",
        filename=file_name,
        file_size=len(file_bytes),
    )

    validation = validate_pdf_file(file_bytes, file_name)
    if not validation.valid:
        log_upload_rejection(
            filename=file_name,
            error_type=validation.error_type or "validation_failed",
            error_message=validation.error_message or "Validation failed.",
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": validation.error_type,
                "message": validation.error_message,
                "ocr_warning": validation.ocr_warning,
            },
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / f"{uuid.uuid4()}_{file_name}"
    file_path.write_bytes(file_bytes)

    async with get_db() as db:
        ws_service = WorkspaceService(db)
        title = file_name.rsplit(".", 1)[0]
        workspace = await ws_service.create_workspace(
            country="",
            policy_title=f"AI Auditor — {title}",
            frameworks=[],
            policy_file_name=file_name,
            policy_file_path=str(file_path),
        )
        # NOTE: str() is required — after commit/refresh the ORM hands back
        # an asyncpg UUID object, not a python uuid.UUID; update_status
        # re-parses the id with uuid.UUID(...).
        # NOTE: str() is required — after commit/refresh the ORM hands back
        # an asyncpg UUID object, not a python uuid.UUID; update_status
        # re-parses the id with uuid.UUID(...).
        workspace_id_str = str(workspace.id)
        try:
            await ws_service.update_status(
                workspace_id_str,
                WorkspaceStatus.CHAT_ONLY,
                detail="Uploaded for AI Auditor chat — no dimension analysis run.",
            )
            from src.ingestion import ingest_document

            vector_store = get_vector_store()
            chunks = ingest_document(
                file_path,
                framework_name=None,
                workspace_id=workspace_id_str,
                document_name=file_name,
            )
            vector_store.add_chunks(chunks)
        except Exception as exc:
            # No orphaned chat_only workspace / stray PDF on ingest failure:
            # roll back the workspace row and delete the saved file, then
            # surface a clean 500. (Any chunks already added are tagged to the
            # deleted workspace id and become unreachable — harmless.)
            logger.error(
                "auditor_upload_ingest_failed",
                workspace_id=workspace_id_str,
                filename=file_name,
                error=str(exc),
            )
            try:
                await ws_service.delete_workspace(workspace_id_str)
            except Exception:
                pass
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise HTTPException(
                500, detail="Failed to ingest the document for chat. Please try another PDF."
            ) from exc
        logger.info(
            "auditor_upload_ingested",
            workspace_id=workspace_id_str,
            filename=file_name,
            chunk_count=len(chunks),
        )
        return {
            "workspace_id": workspace_id_str,
            "file_name": file_name,
            "policy_title": title,
            "chunk_count": len(chunks),
        }


@app.post("/api/v1/analyze/{workspace_id}/run")
async def run_analysis(
    workspace_id: str,
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Start the pipeline over every document queued on this workspace.

    Separate from upload so the user controls when analysis begins and can
    attach more than one document first. Every queued file is ingested before
    any dimension is scored, so a multi-document workspace is evaluated as a
    single body of policy rather than as whichever file happened to land last.
    """
    async with get_db() as db:
        ws_service = WorkspaceService(db)
        workspace = await ws_service.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(404, "Workspace not found")

        pending = list(workspace.pending_documents or [])
        if not pending:
            raise HTTPException(
                400,
                detail={
                    "error": "no_documents",
                    "message": "Upload at least one PDF before running the analysis.",
                },
            )
        if workspace.status in (
            WorkspaceStatus.PROCESSING,
            WorkspaceStatus.GENERATING_REPORT,
        ):
            raise HTTPException(
                409,
                detail={
                    "error": "already_running",
                    "message": "An analysis is already running for this workspace.",
                },
            )

        # Missing files (a wiped uploads dir between restarts) are dropped here
        # rather than failing mid-pipeline, where the workspace would be left
        # in PROCESSING with a stack trace and no obvious way back.
        missing = [d for d in pending if not Path(d.get("file_path", "")).is_file()]
        usable = [d for d in pending if Path(d.get("file_path", "")).is_file()]
        if missing:
            logger.warning(
                "run_analysis_dropped_missing_files",
                workspace_id=workspace_id,
                missing=[d.get("file_name") for d in missing],
            )
            await ws_service.set_pending_documents(workspace_id, usable)
        if not usable:
            raise HTTPException(
                400,
                detail={
                    "error": "files_unavailable",
                    "message": "The uploaded files are no longer on disk. Please upload them again.",
                },
            )

        await ws_service.update_status(
            workspace_id,
            WorkspaceStatus.PROCESSING,
            detail=f"Starting analysis of {len(usable)} document(s).",
        )

        from src.tasks import run_full_analysis_pipeline

        background_tasks.add_task(
            run_full_analysis_pipeline,
            workspace_id=workspace_id,
            documents=usable,
            frameworks=workspace.frameworks,
        )

    return {
        "status": "processing",
        "message": "Analysis started.",
        "workspace_id": workspace_id,
        "documents": [d["file_name"] for d in usable],
    }


@app.get("/api/v1/analyze/{workspace_id}")
async def get_analysis(workspace_id: str):
    async with get_db() as db:
        ws_service = WorkspaceService(db)
        workspace = await ws_service.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(404, "Workspace not found")

        analyses = await ws_service.get_analyses_for_workspace(workspace_id)
        if not analyses:
            return {
                "workspace_id": workspace_id,
                "status": workspace.status.value,
                "status_detail": workspace.status_detail,
                "analyses": [],
            }

        analysis_list = []
        for a in analyses:
            # Analysis-level metrics persisted in the ragas_metrics JSON blob
            # (llm_call_count / tier_stats / decision_analytics) ride through
            # to the frontend so the call-count and decision-analytics cards
            # render instead of reading fields that never arrive.
            metrics = a.ragas_metrics or {}
            analysis_list.append(
                {
                    "analysis_id": str(a.id),
                    "document_name": a.document_name,
                    "frameworks_used": a.frameworks_used,
                    "governance_gaps": a.governance_gaps or [],
                    "summary": a.summary or "",
                    "total_retrieved": a.total_retrieved or 0,
                    "similarity_scores": a.similarity_scores or [],
                    "llm_latency": a.llm_latency or 0.0,
                    "total_processing_time": a.total_processing_time or 0.0,
                    "generated_by": a.generated_by or {"provider": "unknown", "tier": "unknown"},
                    "llm_call_count": metrics.get("llm_call_count", 0),
                    "tier_stats": metrics.get("tier_stats"),
                    "decision_analytics": metrics.get("decision_analytics"),
                    # Deterministic scope disclaimer + evaluated document list
                    # (multi-doc workspaces: NAIS + Model AI Governance Framework).
                    "scope_disclaimer": (metrics.get("scope_disclaimer") or {}).get(
                        "disclaimer", ""
                    ),
                    "evaluated_documents": metrics.get("evaluated_documents", []),
                    "created_at": a.created_at.isoformat() if a.created_at else "",
                }
            )

        return {
            "workspace_id": workspace_id,
            "status": workspace.status.value,
            "status_detail": workspace.status_detail,
            "analyses": analysis_list,
        }


@app.post("/api/v1/brief")
async def generate_brief(body: BriefRequest):
    async with get_db() as db:
        ws_service = WorkspaceService(db)
        analyses = await ws_service.get_analyses_for_workspace(body.workspace_id)
        if not analyses:
            raise HTTPException(404, "No analyses found for this workspace")

        latest = analyses[0]

        from src.gap_analyzer import GapAnalysisResult, GovernanceGap

        gaps = [GovernanceGap(**g) for g in (latest.governance_gaps or [])]
        result = GapAnalysisResult(
            analysis_id=str(latest.id),
            workspace_id=body.workspace_id,
            document_name=latest.document_name,
            frameworks_used=latest.frameworks_used or [],
            governance_gaps=gaps,
            summary=latest.summary or "",
            total_retrieved=latest.total_retrieved or 0,
            retrieval_frameworks=latest.retrieval_frameworks or [],
            similarity_scores=latest.similarity_scores or [],
            llm_latency=latest.llm_latency or 0.0,
            total_processing_time=latest.total_processing_time or 0.0,
        )

        brief_text = generate_executive_brief_text(result)
        return {"brief": brief_text, "format": "text"}


# --- Executive Brief (Part 3) ---
# Generate = ONE synthesis LLM call over the already-stored, citation-verified
# results. The structured brief is cached in reports (type='executive_brief',
# meta=JSON); exports render from the cache and never re-run the LLM call.


async def _load_latest_analysis(ws_service, workspace_id: str):
    analyses = await ws_service.get_analyses_for_workspace(workspace_id)
    if not analyses:
        return None
    return analyses[0]  # ordered created_at DESC — newest first


async def _load_cached_brief(db, workspace_id: str) -> Report | None:
    stmt = (
        sa_select(Report)
        .where(
            Report.workspace_id == uuid.UUID(workspace_id),
            Report.type == "executive_brief",
        )
        .order_by(Report.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _save_brief(db, workspace_id: str, brief: dict, markdown: str) -> None:
    """Upsert: one executive_brief per workspace (a regenerate replaces the
    previous one so the brief never goes stale)."""
    old = await _load_cached_brief(db, workspace_id)
    if old:
        await db.delete(old)
    db.add(
        Report(
            workspace_id=uuid.UUID(workspace_id),
            type="executive_brief",
            content=markdown,
            meta=brief,
            created_at=datetime.utcnow(),
        )
    )
    await db.commit()


@app.post("/api/v1/brief/{workspace_id}/generate")
async def generate_brief_v2_route(workspace_id: str):
    async with get_db() as db:
        ws_service = WorkspaceService(db)
        workspace = await ws_service.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(404, "Workspace not found")
        latest = await _load_latest_analysis(ws_service, workspace_id)
        if latest is None:
            raise HTTPException(
                409, "No analysis found for this workspace — run the analysis first."
            )

        gaps_raw = latest.governance_gaps or []
        metrics = latest.ragas_metrics or {}
        scope_info = metrics.get("scope_disclaimer") or {}
        scope_disclaimer = scope_info.get("disclaimer", "")
        if not scope_disclaimer:
            scope_disclaimer = (
                "Scope: this assessment evaluates the document(s) provided to "
                "the system. It is not an assessment of the country's complete "
                "AI governance apparatus."
            )
        documents = metrics.get("evaluated_documents") or (
            [latest.document_name] if latest.document_name else []
        )
        decision = metrics.get("decision_analytics") or {}

        try:
            brief = generate_brief_v2(
                workspace_id=workspace_id,
                country=workspace.country,
                policy_title=workspace.policy_title,
                document_name=latest.document_name or "",
                documents=documents,
                frameworks_used=latest.frameworks_used or [],
                scope_disclaimer=scope_disclaimer,
                gaps=list(gaps_raw),
                decision_analytics=decision,
            )
        except Exception as exc:
            logger.error(
                "brief_generation_failed",
                workspace_id=workspace_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise HTTPException(
                502,
                detail=(
                    "Brief generation failed (LLM provider/quota error). "
                    "Try again when quota is available."
                ),
            ) from exc

        await _save_brief(db, workspace_id, brief, render_brief_markdown(brief))
        return brief


@app.get("/api/v1/brief/{workspace_id}")
async def get_brief(workspace_id: str):
    """Return the cached brief (if any) — never re-runs the synthesis call."""
    async with get_db() as db:
        report = await _load_cached_brief(db, workspace_id)
        if report is None or not report.meta:
            raise HTTPException(404, "No brief generated for this workspace yet.")
        return report.meta


@app.get("/api/v1/brief/{workspace_id}/export")
async def export_brief(workspace_id: str, format: str = "pdf"):
    """Render the CACHED brief into DOCX or PDF — no LLM call on export."""
    async with get_db() as db:
        report = await _load_cached_brief(db, workspace_id)
        if report is None or not report.meta:
            raise HTTPException(
                404, "No brief generated for this workspace yet — generate one first."
            )
        brief = report.meta
        slug = workspace_id[:8]
        if format == "docx":
            data = render_docx(brief)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            filename = f"meridian_brief_{slug}.docx"
        elif format == "pdf":
            data = render_pdf(brief)
            media = "application/pdf"
            filename = f"meridian_brief_{slug}.pdf"
        else:
            raise HTTPException(400, "format must be 'pdf' or 'docx'")
        return Response(
            content=data,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@app.get("/api/v1/workspace/{workspace_id}/analyses")
async def list_analyses(workspace_id: str):
    async with get_db() as db:
        ws_service = WorkspaceService(db)
        analyses = await ws_service.get_analyses_for_workspace(workspace_id)
        return [
            {
                "analysis_id": str(a.id),
                "document_name": a.document_name,
                "summary": a.summary,
                "total_retrieved": a.total_retrieved,
                "citation_pass_count": a.citation_pass_count,
                "citation_fail_count": a.citation_fail_count,
                "generated_by": a.generated_by or {"provider": "unknown", "tier": "unknown"},
                "created_at": a.created_at.isoformat() if a.created_at else "",
            }
            for a in analyses
        ]


# --- Chat Schemas ---


class ChatRequest(BaseModel):
    workspace_id: str | None = ""  # empty/None = Mode A (general, unscoped)
    message: str
    session_id: str | None = None
    finding_context: dict[str, Any] | None = None
    mode: str = "advisor"  # "advisor" | "framework_qa" | "document_overview"
    # Which run the question is about. A workspace holds one run per document
    # set, and the Rapporteur sits beside a run selector — without this it
    # answered from the newest run whatever the user was looking at.
    analysis_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    citations: list[dict[str, Any]] = []
    blocked: bool = False
    reason: str | None = None
    retrieval_count: int = 0
    citation_pass_count: int = 0
    citation_fail_count: int = 0
    intent: str = "unknown"
    dimension: str | None = None
    provider: str = "template"
    mode: str = "advisor"
    # Article/recital numbers written into the reply that the retrieved
    # evidence does not support. Same two severities as the gap analysis.
    unverifiable_citations: list[str] = []
    fabricated_citations: list[str] = []


class ChatSessionResponse(BaseModel):
    session_id: str
    workspace_id: str = ""  # empty for Mode A (general, no workspace scope)
    finding_id: str | None = None
    mode: str = "advisor"
    title: str | None = None
    created_at: str
    updated_at: str


# --- Chat Routes ---


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat_endpoint(body: ChatRequest):
    vs = get_vector_store()
    gd = get_guardrails()

    async with get_db() as db:
        ws_service = WorkspaceService(db)

        # Mode A (general educational) has no workspace scope — an empty/null
        # workspace_id is valid there. Modes that need a workspace must resolve
        # it; anything else is a 404.
        workspace_id = (body.workspace_id or "").strip()
        workspace = None
        if workspace_id:
            workspace = await ws_service.get_workspace(workspace_id)
            if not workspace:
                raise HTTPException(404, "Workspace not found")

        history_messages: list[dict[str, str]] = []
        session_id = body.session_id
        mode = (
            body.mode
            if body.mode in ("advisor", "framework_qa", "document_overview", "auditor")
            else "advisor"
        )

        if session_id:
            session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
            stmt = await db.execute(
                sa_select(ChatMessage)
                .where(ChatMessage.session_id == session_uuid)
                .order_by(ChatMessage.created_at)
            )
            msgs = stmt.scalars().all()
            history_messages = [{"role": m.role, "content": m.content} for m in msgs]
        else:
            session_id = str(uuid.uuid4())
            new_session = ChatSession(
                id=uuid.UUID(session_id),
                workspace_id=(uuid.UUID(workspace_id) if workspace_id else None),
                mode=mode,
                title=body.message[:80],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(new_session)
            await db.commit()

        # Load analysis results for contextual awareness.
        #
        # Two things were wrong here. The run was always analyses[0] — the most
        # recent — so a question about the run the user had open in the selector
        # was answered from a different one whenever a workspace held more than
        # one, which is every two-run country. And only the gaps were passed, so
        # nothing cross-dimensional (coverage index, binding share, which
        # dimension came out strongest) had any figures behind it.
        analysis_data = None
        try:
            if workspace_id:
                analyses = await ws_service.get_analyses_for_workspace(workspace_id)
                if analyses:
                    chosen = analyses[0]
                    if body.analysis_id:
                        chosen = next(
                            (a for a in analyses if str(a.id) == body.analysis_id),
                            analyses[0],
                        )
                    gaps_raw = chosen.governance_gaps or []
                    gaps_dict = {}
                    for g in gaps_raw:
                        if isinstance(g, dict):
                            gaps_dict[g.get("dimension", "")] = g
                    metrics = chosen.ragas_metrics or {}
                    analysis_data = {
                        "gaps": gaps_dict,
                        "decision_analytics": metrics.get("decision_analytics") or {},
                        "documents": metrics.get("evaluated_documents") or [],
                        "country": workspace.country if workspace else None,
                        "policy_title": workspace.policy_title if workspace else None,
                    }
        except Exception:
            pass

        # OFF THE EVENT LOOP. chat_fn is synchronous and spends most of its
        # time waiting on the LLM — 8 to 75 seconds in measured runs. Called
        # directly from an async endpoint it blocks the single event loop for
        # that entire duration, so every other request (the workspace list, the
        # analysis fetch, the status poller) queues behind whoever is chatting.
        # That is the same defect already fixed in the analysis pipeline; it
        # was never applied here, and it is a large part of why the Analysis
        # page felt slow to load while the Auditor was answering.
        result = await asyncio.to_thread(
            chat_fn,
            workspace_id=workspace_id,
            user_message=body.message,
            vector_store=vs,
            guardrails=gd,
            finding_context=body.finding_context,
            conversation_history=history_messages,
            frameworks=workspace.frameworks if workspace else None,
            analysis_results=analysis_data,
            session_id=str(session_id) if session_id else None,
            mode=mode,
        )

        msg_user = ChatMessage(
            id=uuid.uuid4(),
            session_id=uuid.UUID(session_id) if isinstance(session_id, str) else session_id,
            role="user",
            content=body.message,
            created_at=datetime.utcnow(),
        )
        msg_assistant = ChatMessage(
            id=uuid.uuid4(),
            session_id=uuid.UUID(session_id) if isinstance(session_id, str) else session_id,
            role="assistant",
            content=result["reply"],
            citations=result.get("citations"),
            retrieval_count=result.get("retrieval_count", 0),
            citation_pass_count=result.get("citation_pass_count", 0),
            citation_fail_count=result.get("citation_fail_count", 0),
            llm_latency=result.get("llm_latency", 0.0),
            guardrail_result={
                "blocked": result.get("blocked", False),
                "reason": result.get("reason"),
            },
            created_at=datetime.utcnow(),
        )
        db.add(msg_user)
        db.add(msg_assistant)
        await db.commit()

        return ChatResponse(
            session_id=str(session_id),
            reply=result["reply"],
            citations=result.get("citations", []),
            blocked=result.get("blocked", False),
            reason=result.get("reason"),
            retrieval_count=result.get("retrieval_count", 0),
            citation_pass_count=result.get("citation_pass_count", 0),
            citation_fail_count=result.get("citation_fail_count", 0),
            intent=result.get("intent", "unknown"),
            dimension=result.get("dimension"),
            provider=result.get("provider", "template"),
            mode=mode,
            unverifiable_citations=result.get("unverifiable_citations", []),
            fabricated_citations=result.get("fabricated_citations", []),
        )


@app.get("/api/v1/chat/sessions", response_model=list[ChatSessionResponse])
async def list_chat_sessions(workspace_id: str = "", mode: str | None = None):
    async with get_db() as db:
        stmt = sa_select(ChatSession)
        # Empty workspace_id lists Mode A sessions (no workspace scope); a
        # non-empty one filters to that workspace's sessions.
        ws = (workspace_id or "").strip()
        if ws:
            stmt = stmt.where(ChatSession.workspace_id == uuid.UUID(ws))
        else:
            stmt = stmt.where(ChatSession.workspace_id.is_(None))
        stmt = stmt.order_by(ChatSession.updated_at.desc())
        # Must match the whitelist the create endpoint accepts (line ~1009) —
        # "auditor" was missing here, so an Auditor history request silently
        # dropped its mode filter instead of scoping to auditor sessions,
        # mixing in every Rapporteur ("advisor") conversation as well.
        if mode in ("advisor", "framework_qa", "document_overview", "auditor"):
            stmt = stmt.where(ChatSession.mode == mode)
        result = await db.execute(stmt)
        sessions = result.scalars().all()
        return [
            ChatSessionResponse(
                session_id=str(s.id),
                workspace_id=str(s.workspace_id) if s.workspace_id else "",
                finding_id=s.finding_id,
                mode=s.mode or "advisor",
                title=s.title,
                created_at=s.created_at.isoformat() if s.created_at else "",
                updated_at=s.updated_at.isoformat() if s.updated_at else "",
            )
            for s in sessions
        ]


@app.get("/api/v1/chat/sessions/{session_id}")
async def get_chat_session(session_id: str):
    async with get_db() as db:
        stmt = sa_select(ChatSession).where(ChatSession.id == uuid.UUID(session_id))
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(404, "Session not found")

        msg_stmt = (
            sa_select(ChatMessage)
            .where(ChatMessage.session_id == uuid.UUID(session_id))
            .order_by(ChatMessage.created_at)
        )
        msg_result = await db.execute(msg_stmt)
        messages = msg_result.scalars().all()

        return {
            "session": ChatSessionResponse(
                session_id=str(session.id),
                workspace_id=str(session.workspace_id) if session.workspace_id else "",
                finding_id=session.finding_id,
                mode=session.mode or "advisor",
                title=session.title,
                created_at=session.created_at.isoformat() if session.created_at else "",
                updated_at=session.updated_at.isoformat() if session.updated_at else "",
            ),
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "citations": m.citations or [],
                    "created_at": m.created_at.isoformat() if m.created_at else "",
                }
                for m in messages
            ],
        }


@app.delete("/api/v1/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    async with get_db() as db:
        stmt = sa_select(ChatSession).where(ChatSession.id == uuid.UUID(session_id))
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(404, "Session not found")
        await db.delete(session)
        await db.commit()
        return {"status": "deleted"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
