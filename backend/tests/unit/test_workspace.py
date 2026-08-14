"""
Unit tests for workspace status transitions.
"""

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
