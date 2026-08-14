from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime
import structlog
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import select as sa_select
from sqlalchemy import text as sa_text

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.logging_config import setup_logging, log_upload_rejection
from src.vectorstore import VectorStore
from src.validation import validate_pdf_file
from src.gap_analyzer import GapAnalyzer
from src.brief_generator import generate_executive_brief_text
from src.workspace import WorkspaceService
from src.db_models import Base, WorkspaceStatus, ChatSession, ChatMessage, Report
from src.brief_synthesis import generate_brief as generate_brief_v2, render_brief_markdown
from src.brief_export import render_docx, render_pdf
from src.framework_sync import FrameworkSyncService
from src.framework_library import get_framework_library
from src.guardrails import Guardrails
from src.verify import verify_citation
from src.ingestion import ingest_document
from src.chat import chat as chat_fn

setup_logging()
logger = structlog.get_logger()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://aura:aura@localhost:5432/aura_sdg")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
UPLOAD_DIR = Path(__file__).parent / "data" / "uploads"
# Comma-separated list of allowed browser origins (e.g. "https://app.example.com,http://localhost:3000")
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
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


async def get_db() -> AsyncSession:
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
        # Idempotent migration: chat_sessions.mode is new in Part 3.
        # create_all does not alter existing tables, so add the column if
        # the table predates this build. Safe to re-run on every boot.
        try:
            await conn.execute(sa_text(
                "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS "
                "mode VARCHAR(50) DEFAULT 'advisor' NOT NULL"
            ))
            # Mode A (general) sessions have no workspace scope.
            await conn.execute(sa_text(
                "ALTER TABLE chat_sessions ALTER COLUMN workspace_id DROP NOT NULL"
            ))
        except Exception:
            logger.warning("chat_sessions_mode_migration_skipped")
        # Executive brief (Part 3): reports gained content + meta columns so a
        # generated brief (structured JSON in meta, markdown in content) is
        # cached and exported without re-running the synthesis LLM call.
        try:
            await conn.execute(sa_text(
                "ALTER TABLE reports ADD COLUMN IF NOT EXISTS content TEXT"
            ))
            await conn.execute(sa_text(
                "ALTER TABLE reports ADD COLUMN IF NOT EXISTS meta JSON"
            ))
        except Exception:
            logger.warning("reports_brief_columns_migration_skipped")
        # AI Auditor: workspaces used for document chat only get the new
        # chat_only status (never analysed). Adds the enum value idempotently.
        # NOTE: SQLAlchemy's SAEnum(WorkspaceStatus) serializes the MEMBER NAME
        # (the existing type holds 'QUEUED'/'COMPLETE'/'ERROR'), so the added
        # value must be 'CHAT_ONLY' — the lowercase 'chat_only' would never
        # match what SQLAlchemy emits and every chat_only insert would fail.
        try:
            await conn.execute(sa_text(
                "ALTER TYPE workspacestatus ADD VALUE IF NOT EXISTS 'CHAT_ONLY'"
            ))
        except Exception:
            logger.warning("workspacestatus_chat_only_migration_skipped")
        # Clean up the stray lowercase value added by an earlier migration
        # attempt (SQLAlchemy emits the NAME, so only 'CHAT_ONLY' is valid).
        # Harmless if the DROP fails (value unused), but keeps the enum tidy.
        try:
            await conn.execute(sa_text(
                "ALTER TYPE workspacestatus DROP VALUE IF EXISTS 'chat_only'"
            ))
        except Exception:
            logger.warning("workspacestatus_stray_value_cleanup_skipped")
    logger.info("database_tables_created")
    get_vector_store()
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
    async for db in get_db():
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
            created_at=workspace.created_at.isoformat() if workspace.created_at else "",
            updated_at=workspace.updated_at.isoformat() if workspace.updated_at else "",
        )


@app.get("/api/v1/workspace")
async def list_workspaces():
    async for db in get_db():
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
                created_at=w.created_at.isoformat() if w.created_at else "",
                updated_at=w.updated_at.isoformat() if w.updated_at else "",
            )
            for w in workspaces
        ]


@app.get("/api/v1/workspace/{workspace_id}")
async def get_workspace(workspace_id: str):
    async for db in get_db():
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

    async for db in get_db():
        ws_service = WorkspaceService(db)
        workspace = await ws_service.get_workspace(workspace_id)
        if not workspace:
            raise HTTPException(404, "Workspace not found")

        await ws_service.update_status(
            workspace_id,
            WorkspaceStatus.PROCESSING,
            detail="Upload received. Starting analysis pipeline.",
        )
        await ws_service.log_upload(
            filename=file.filename or "unknown",
            file_size=len(file_bytes),
            validation_passed=True,
            workspace_id=workspace_id,
            ocr_warning=validation.ocr_warning,
        )

        from src.tasks import run_full_analysis_pipeline

        background_tasks.add_task(
            run_full_analysis_pipeline,
            workspace_id=workspace_id,
            file_path=str(file_path),
            file_name=file.filename or "document.pdf",
            frameworks=workspace.frameworks,
        )

    return {
        "status": "processing",
        "message": "Upload accepted. Analysis pipeline started.",
        "workspace_id": workspace_id,
        "file_name": file.filename,
        "file_size": len(file_bytes),
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

    async for db in get_db():
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


@app.get("/api/v1/analyze/{workspace_id}")
async def get_analysis(workspace_id: str):
    async for db in get_db():
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
            analysis_list.append({
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
                "scope_disclaimer": (metrics.get("scope_disclaimer") or {})
                .get("disclaimer", ""),
                "evaluated_documents": metrics.get("evaluated_documents", []),
                "created_at": a.created_at.isoformat() if a.created_at else "",
            })

        return {
            "workspace_id": workspace_id,
            "status": workspace.status.value,
            "status_detail": workspace.status_detail,
            "analyses": analysis_list,
        }


@app.post("/api/v1/brief")
async def generate_brief(body: BriefRequest):
    async for db in get_db():
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
    db.add(Report(
        workspace_id=uuid.UUID(workspace_id),
        type="executive_brief",
        content=markdown,
        meta=brief,
        created_at=datetime.utcnow(),
    ))
    await db.commit()


@app.post("/api/v1/brief/{workspace_id}/generate")
async def generate_brief_v2_route(workspace_id: str):
    async for db in get_db():
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
    async for db in get_db():
        report = await _load_cached_brief(db, workspace_id)
        if report is None or not report.meta:
            raise HTTPException(404, "No brief generated for this workspace yet.")
        return report.meta


@app.get("/api/v1/brief/{workspace_id}/export")
async def export_brief(workspace_id: str, format: str = "pdf"):
    """Render the CACHED brief into DOCX or PDF — no LLM call on export."""
    async for db in get_db():
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
    async for db in get_db():
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

    async for db in get_db():
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
            stmt = (
                await db.execute(
                    sa_select(ChatMessage)
                    .where(ChatMessage.session_id == session_uuid)
                    .order_by(ChatMessage.created_at)
                )
            )
            msgs = stmt.scalars().all()
            history_messages = [{"role": m.role, "content": m.content} for m in msgs]
        else:
            session_id = str(uuid.uuid4())
            new_session = ChatSession(
                id=uuid.UUID(session_id),
                workspace_id=(
                    uuid.UUID(workspace_id) if workspace_id else None
                ),
                mode=mode,
                title=body.message[:80],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(new_session)
            await db.commit()

        # Load analysis results for contextual awareness
        analysis_data = None
        try:
            if workspace_id:
                analyses = await ws_service.get_analyses_for_workspace(workspace_id)
                if analyses:
                    gaps_raw = analyses[0].governance_gaps or []
                    gaps_dict = {}
                    for g in gaps_raw:
                        if isinstance(g, dict):
                            gaps_dict[g.get("dimension", "")] = g
                    analysis_data = {"gaps": gaps_dict}
        except Exception:
            pass

        result = chat_fn(
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
            guardrail_result={"blocked": result.get("blocked", False), "reason": result.get("reason")},
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
        )


@app.get("/api/v1/chat/sessions", response_model=list[ChatSessionResponse])
async def list_chat_sessions(workspace_id: str = "", mode: str | None = None):
    async for db in get_db():
        stmt = sa_select(ChatSession)
        # Empty workspace_id lists Mode A sessions (no workspace scope); a
        # non-empty one filters to that workspace's sessions.
        ws = (workspace_id or "").strip()
        if ws:
            stmt = stmt.where(ChatSession.workspace_id == uuid.UUID(ws))
        else:
            stmt = stmt.where(ChatSession.workspace_id.is_(None))
        stmt = stmt.order_by(ChatSession.updated_at.desc())
        if mode in ("advisor", "framework_qa", "document_overview"):
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
    async for db in get_db():
        stmt = (
            sa_select(ChatSession)
            .where(ChatSession.id == uuid.UUID(session_id))
        )
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
    async for db in get_db():
        stmt = (
            sa_select(ChatSession)
            .where(ChatSession.id == uuid.UUID(session_id))
        )
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
