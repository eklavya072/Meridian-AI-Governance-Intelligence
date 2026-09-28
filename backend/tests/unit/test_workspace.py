"""
Unit tests for workspace status transitions.
"""

import uuid

import pytest

from src.db_models import WorkspaceStatus


class TestWorkspaceStatusTransitions:
    def test_status_enum_values(self):
        assert WorkspaceStatus.QUEUED.value == "queued"
        assert WorkspaceStatus.PROCESSING.value == "processing"
        assert WorkspaceStatus.GENERATING_REPORT.value == "generating_report"
        assert WorkspaceStatus.COMPLETE.value == "complete"
        assert WorkspaceStatus.ERROR.value == "error"

    def test_status_comparison(self):
        assert WorkspaceStatus.QUEUED != WorkspaceStatus.PROCESSING
        assert WorkspaceStatus.PROCESSING != WorkspaceStatus.COMPLETE

    def test_status_order_concept(self):
        valid_transitions = {
            WorkspaceStatus.QUEUED: [WorkspaceStatus.PROCESSING, WorkspaceStatus.ERROR],
            WorkspaceStatus.PROCESSING: [
                WorkspaceStatus.GENERATING_REPORT,
                WorkspaceStatus.ERROR,
            ],
            WorkspaceStatus.GENERATING_REPORT: [WorkspaceStatus.COMPLETE, WorkspaceStatus.ERROR],
            WorkspaceStatus.COMPLETE: [],
            WorkspaceStatus.ERROR: [],
        }

        for from_status, to_statuses in valid_transitions.items():
            for to_status in to_statuses:
                assert from_status != to_status


class TestBriefInvalidation:
    """A cached brief belongs to the analysis it was written from.

    The cache is keyed on workspace alone, so a re-analysis left the stored
    brief describing verdicts that no longer exist — while GET /brief serves
    it unconditionally and /brief/export renders it straight to PDF. The EU's
    brief was from 26 Aug against an analysis re-scored seven times since.
    """

    @pytest.mark.asyncio
    async def test_saving_an_analysis_drops_the_stale_brief(self):
        import src.workspace as ws_mod

        executed: list = []

        class _Result:
            def scalars(self):
                return self

            def first(self):
                return None

        class _DB:
            def add(self, obj):
                pass

            async def execute(self, stmt):
                executed.append(str(stmt))
                return _Result()

            async def commit(self):
                pass

            async def refresh(self, obj):
                pass

        svc = ws_mod.WorkspaceService(_DB())
        await svc.save_analysis(
            {
                "analysis_id": str(uuid.uuid4()),
                "workspace_id": str(uuid.uuid4()),
                "document_name": "d.pdf",
                "governance_gaps": [],
            }
        )

        assert any("DELETE FROM reports" in q for q in executed), (
            "a re-analysis must invalidate the cached executive brief"
        )
