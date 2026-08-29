"""Reclaim workspaces the last process died holding.

The analysis worker runs in-process, so a workspace still marked PROCESSING at
startup is orphaned by definition — no worker exists behind it. The run
endpoint refuses to start a second analysis while a workspace is in that
state, so before the startup sweep existed a crash wedged the workspace
permanently: the page polled a job that would never finish and the only way
back was editing the database by hand. Two EU workspaces sat like that, one of
them for nine hours.

The sweep's literals are the trap. SQLAlchemy stores this enum by member NAME,
so the Postgres labels are upper-case while the Python values are lower-case.
Writing the values reads correctly and updates nothing, and because the
statement fails into a warning rather than an exception, a broken sweep looks
exactly like a sweep with nothing to do.
"""
import re
from pathlib import Path

from src.db_models import WorkspaceStatus

MAIN = Path(__file__).resolve().parents[2] / "main.py"


def _reclaim_statements() -> list[str]:
    """The UPDATE statements the startup sweep issues against workspaces."""
    source = MAIN.read_text()
    return re.findall(r"UPDATE workspaces SET status = '(\w+)'[^\"]*?"
                      r"WHERE status = '(\w+)'",
                      source.replace('"\n                "', ""), re.DOTALL)


class TestOrphanRecoverySql:
    def test_the_sweep_is_present(self):
        assert _reclaim_statements(), "startup no longer reclaims orphaned workspaces"

    def test_every_literal_is_a_real_enum_label(self):
        """Postgres labels are the member names, not the lower-case values."""
        labels = {s.name for s in WorkspaceStatus}
        for target, source in _reclaim_statements():
            assert source in labels, f"WHERE status = '{source}' matches no enum label"
            assert target in labels, f"SET status = '{target}' matches no enum label"

    def test_only_the_two_live_states_are_reclaimed(self):
        """COMPLETE and ERROR are terminal — a restart must not disturb them."""
        sources = {source for _, source in _reclaim_statements()}
        assert sources == {
            WorkspaceStatus.PROCESSING.name,
            WorkspaceStatus.GENERATING_REPORT.name,
        }

    def test_an_interrupted_analysis_becomes_runnable_again(self):
        moves = dict((source, target) for target, source in _reclaim_statements())
        assert moves[WorkspaceStatus.PROCESSING.name] == WorkspaceStatus.QUEUED.name

    def test_an_interrupted_brief_keeps_its_analysis(self):
        """GENERATING_REPORT had already finished analysing and lost only the
        brief. Sending it back to QUEUED would throw that work away."""
        moves = dict((source, target) for target, source in _reclaim_statements())
        assert moves[WorkspaceStatus.GENERATING_REPORT.name] == WorkspaceStatus.COMPLETE.name
