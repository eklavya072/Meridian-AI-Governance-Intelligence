from __future__ import annotations

import uuid
import structlog
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from src.db_models import Workspace, WorkspaceStatus, Analysis, Report, UploadLog

logger = structlog.get_logger()


class WorkspaceService:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create_workspace(
        self,
        country: str,
        policy_title: str,
        frameworks: list[str] | None = None,
        policy_file_name: str | None = None,
        policy_file_path: str | None = None,
    ) -> Workspace:
        workspace = Workspace(
            id=uuid.uuid4(),
            country=country,
            policy_title=policy_title,
            frameworks=frameworks or [],
            policy_file_name=policy_file_name,
            policy_file_path=policy_file_path,
            status=WorkspaceStatus.QUEUED,
        )
        self.db.add(workspace)
        await self.db.commit()
        await self.db.refresh(workspace)

        logger.info("workspace_created", workspace_id=str(workspace.id), country=country)
        return workspace

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        result = await self.db.execute(
            select(Workspace).where(Workspace.id == uuid.UUID(workspace_id))
        )
        return result.scalar_one_or_none()

    async def list_workspaces(self) -> list[Workspace]:
        result = await self.db.execute(
            select(Workspace).order_by(Workspace.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        workspace_id: str,
        status: WorkspaceStatus,
        detail: str | None = None,
    ) -> Workspace | None:
        values: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.utcnow(),
        }
        if detail:
            values["status_detail"] = detail

        await self.db.execute(
            update(Workspace)
            .where(Workspace.id == uuid.UUID(workspace_id))
            .values(**values)
        )
        await self.db.commit()
        return await self.get_workspace(workspace_id)

    async def set_pending_documents(
        self,
        workspace_id: str,
        documents: list[dict[str, Any]],
    ) -> Workspace | None:
        """Replace the queue of uploaded-but-not-yet-analysed documents.

        Whole-list replacement rather than append: the caller already holds
        the current list and decides how a re-uploaded filename is handled, so
        two concurrent uploads cannot interleave into a half-written queue.
        """
        await self.db.execute(
            update(Workspace)
            .where(Workspace.id == uuid.UUID(workspace_id))
            .values(pending_documents=list(documents), updated_at=datetime.utcnow())
        )
        await self.db.commit()
        return await self.get_workspace(workspace_id)

    async def delete_workspace(self, workspace_id: str) -> bool:
        result = await self.db.execute(
            delete(Workspace).where(Workspace.id == uuid.UUID(workspace_id))
        )
        await self.db.commit()
        return result.rowcount > 0

    async def save_analysis(self, analysis_data: dict[str, Any]) -> Analysis:
        gaps_raw = analysis_data.get("governance_gaps", [])
        if gaps_raw and hasattr(gaps_raw[0], "model_dump"):
            gaps_serialized = [g.model_dump() for g in gaps_raw]
        else:
            gaps_serialized = list(gaps_raw)

        analysis = Analysis(
            id=uuid.UUID(analysis_data["analysis_id"]),
            workspace_id=uuid.UUID(analysis_data["workspace_id"]),
            document_name=analysis_data["document_name"],
            frameworks_used=analysis_data.get("frameworks_used", []),
            governance_gaps=gaps_serialized,
            summary=analysis_data.get("summary", ""),
            total_retrieved=analysis_data.get("total_retrieved", 0),
            retrieval_frameworks=analysis_data.get("retrieval_frameworks", []),
            similarity_scores=analysis_data.get("similarity_scores", []),
            llm_latency=analysis_data.get("llm_latency", 0.0),
            total_processing_time=analysis_data.get("total_processing_time", 0.0),
            generated_by=analysis_data.get("generated_by"),
            # Analysis-level metrics (llm_call_count, tier_stats,
            # decision_analytics) ride in the existing ragas_metrics JSON
            # column and are surfaced by GET /analyze so the frontend's
            # call-count / decision-analytics cards actually render.
            ragas_metrics=analysis_data.get("ragas_metrics"),
        )
        self.db.add(analysis)
        await self.db.commit()
        await self.db.refresh(analysis)
        return analysis

    async def get_analyses_for_workspace(self, workspace_id: str) -> list[Analysis]:
        result = await self.db.execute(
            select(Analysis)
            .where(Analysis.workspace_id == uuid.UUID(workspace_id))
            .order_by(Analysis.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_dimension_result(
        self,
        workspace_id: str,
        dimension: str,
        result: dict[str, Any],
        provider_info: dict[str, str],
    ) -> None:
        ws = await self.get_workspace(workspace_id)
        if not ws:
            return
        existing = dict(ws.dimension_results) if ws.dimension_results else {}
        # A gap with analysis_error is a FAILED analysis, not a completed
        # result — never cache it as "completed", or the next run would load
        # it via get_dimension_results() and skip re-analysis forever.
        failed = bool((result or {}).get("analysis_error"))
        existing[dimension] = {
            "status": "failed" if failed else "completed",
            "provider": provider_info,
            "result": result,
        }
        await self.db.execute(
            update(Workspace)
            .where(Workspace.id == uuid.UUID(workspace_id))
            .values(dimension_results=existing, updated_at=datetime.utcnow())
        )
        await self.db.commit()

    async def set_dimension_failed(
        self,
        workspace_id: str,
        dimension: str,
        error: str,
    ) -> None:
        ws = await self.get_workspace(workspace_id)
        if not ws:
            return
        existing = dict(ws.dimension_results) if ws.dimension_results else {}
        existing[dimension] = {
            "status": "failed",
            "error": error,
        }
        await self.db.execute(
            update(Workspace)
            .where(Workspace.id == uuid.UUID(workspace_id))
            .values(dimension_results=existing, updated_at=datetime.utcnow())
        )
        await self.db.commit()

    async def get_dimension_results(self, workspace_id: str) -> dict[str, Any]:
        ws = await self.get_workspace(workspace_id)
        if not ws or not ws.dimension_results:
            return {}
        return dict(ws.dimension_results)

    async def clear_dimension_results(self, workspace_id: str) -> None:
        await self.db.execute(
            update(Workspace)
            .where(Workspace.id == uuid.UUID(workspace_id))
            .values(dimension_results=None, updated_at=datetime.utcnow())
        )
        await self.db.commit()

    async def log_upload(
        self,
        filename: str,
        file_size: int | None,
        validation_passed: bool,
        error_type: str | None = None,
        error_message: str | None = None,
        ocr_warning: bool = False,
        workspace_id: str | None = None,
    ) -> UploadLog:
        log_entry = UploadLog(
            id=uuid.uuid4(),
            workspace_id=uuid.UUID(workspace_id) if workspace_id else None,
            filename=filename,
            file_size=file_size,
            validation_passed=validation_passed,
            error_type=error_type,
            error_message=error_message,
            ocr_warning=ocr_warning,
        )
        self.db.add(log_entry)
        await self.db.commit()
        await self.db.refresh(log_entry)
        return log_entry
