"""The analysis orchestrator, which had no tests at all.

tasks.py was at 0% coverage while being the module that decides what happens
to a workspace when something goes wrong — and the failure path had a bug
that made every ingestion failure wedge the workspace permanently.
"""

import pytest

from src import tasks
from src.db_models import WorkspaceStatus


class FakeWorkspaceService:
    def __init__(self, db):
        self.statuses = []
        self.dimension_results = {}
        self.saved = None
        self.cleared = False

    async def update_status(self, workspace_id, status, detail=None):
        self.statuses.append((status, detail))

    async def get_dimension_results(self, workspace_id):
        return {}

    async def update_dimension_result(self, workspace_id, dim, gap, info):
        self.dimension_results[dim] = gap

    async def clear_dimension_results(self, workspace_id):
        self.cleared = True

    async def get_workspace(self, workspace_id):
        class _WS:
            country = "Testland"

        return _WS()

    async def save_analysis(self, payload):
        self.saved = payload


@pytest.fixture
def service(monkeypatch):
    """One shared service instance so assertions see what the pipeline did."""
    holder = {}

    def _factory(db):
        if "svc" not in holder:
            holder["svc"] = FakeWorkspaceService(db)
        return holder["svc"]

    monkeypatch.setattr(tasks, "WorkspaceService", _factory)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield object()

    monkeypatch.setattr(tasks, "_get_db_session", _session)
    yield holder


class TestArgumentHandling:
    async def test_no_documents_at_all_is_rejected(self):
        with pytest.raises(ValueError, match="at least one document"):
            await tasks.run_full_analysis_pipeline(workspace_id="w1", frameworks=[])

    async def test_the_legacy_single_file_signature_is_still_accepted(
        self, service, monkeypatch, tmp_path
    ):
        # A background task queued before a restart may still call the old
        # one-document signature; failing on signature would lose that run.
        monkeypatch.setattr(tasks, "VectorStore", _boom_store)

        result = await tasks.run_full_analysis_pipeline(
            workspace_id="w1",
            frameworks=[],
            file_path=str(tmp_path / "a.pdf"),
            file_name="a.pdf",
        )

        assert result["status"] == "error"


class TestFailureHandling:
    async def test_an_ingestion_failure_marks_the_workspace_ERROR(
        self, service, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(tasks, "VectorStore", _boom_store)

        result = await tasks.run_full_analysis_pipeline(
            workspace_id="w1",
            frameworks=[],
            documents=[{"file_path": str(tmp_path / "a.pdf"), "file_name": "a.pdf"}],
        )

        # The regression this pins: completed_dimensions was assigned only
        # after ingestion, so a failure during ingestion made the except block
        # itself raise UnboundLocalError. That masked the real error and
        # skipped this status update, wedging the workspace in PROCESSING.
        assert result["status"] == "error"
        statuses = [s for s, _ in service["svc"].statuses]
        assert WorkspaceStatus.ERROR in statuses

    async def test_the_original_error_is_reported_not_swallowed(
        self, service, monkeypatch, tmp_path
    ):
        class _Boom:
            def __init__(self, **kw):
                raise RuntimeError("chroma is unreachable")

        monkeypatch.setattr(tasks, "VectorStore", _Boom)

        result = await tasks.run_full_analysis_pipeline(
            workspace_id="w1",
            frameworks=[],
            documents=[{"file_path": str(tmp_path / "a.pdf"), "file_name": "a.pdf"}],
        )

        assert "chroma is unreachable" in result["error"]

    async def test_the_failure_detail_reaches_the_workspace(self, service, monkeypatch, tmp_path):
        monkeypatch.setattr(tasks, "VectorStore", _boom_store)

        await tasks.run_full_analysis_pipeline(
            workspace_id="w1",
            frameworks=[],
            documents=[{"file_path": str(tmp_path / "a.pdf"), "file_name": "a.pdf"}],
        )

        details = [d for _, d in service["svc"].statuses if d]
        # A user staring at a failed run needs a reason, not a blank card.
        assert any("Pipeline error" in d for d in details)


class TestDisplayNames:
    def test_upload_uuid_prefixes_are_stripped(self):
        name = tasks._display_name(
            "f3e3617d-1234-4321-9876-c052cd62d574_Artificial_Intelligence_Policy.pdf"
        )

        # document_name is user-facing: it is what the report lists under
        # "documents evaluated".
        assert name == "Artificial_Intelligence_Policy.pdf"

    def test_repeated_prefixes_are_all_stripped(self):
        raw = "f3e3617d-1234-4321-9876-c052cd62d574_a1b2c3d4-1234-4321-9876-c052cd62d574_policy.pdf"

        assert tasks._display_name(raw) == "policy.pdf"

    def test_a_clean_name_is_untouched(self):
        assert tasks._display_name("EU AI ACT.pdf") == "EU AI ACT.pdf"

    def test_none_falls_back_to_a_placeholder(self):
        assert tasks._display_name(None) == "document.pdf"


class TestScopeDisclaimer:
    def test_a_single_document_is_named(self):
        scope = tasks._build_scope_disclaimer(_FakeVS(["strategy.pdf"]), "w1")

        assert "strategy.pdf" in scope["disclaimer"]
        assert scope["documents"] == ["strategy.pdf"]

    def test_multiple_documents_are_all_listed(self):
        scope = tasks._build_scope_disclaimer(_FakeVS(["a.pdf", "b.pdf"]), "w1")

        # A multi-document workspace must not have the report imply it scored
        # only one of them.
        assert "a.pdf" in scope["disclaimer"] and "b.pdf" in scope["disclaimer"]

    def test_an_empty_workspace_never_renders_an_empty_parenthetical(self):
        disclaimer = tasks._build_scope_disclaimer(_FakeVS([]), "w1")["disclaimer"]

        assert "()" not in disclaimer
        assert "document(s) provided" in disclaimer

    def test_korea_without_pipa_gets_the_scope_limited_note(self):
        scope = tasks._build_scope_disclaimer(
            _FakeVS(["AI Framework Act.pdf"]), "w1", country="South Korea"
        )

        # Korea's personal-data governance lives in PIPA; scoring Privacy from
        # the AI Act alone would understate it without saying so.
        assert "PIPA" in scope["disclaimer"]

    def test_korea_with_pipa_present_gets_no_note(self):
        scope = tasks._build_scope_disclaimer(
            _FakeVS(["AI Framework Act.pdf", "PIPA 2020.pdf"]), "w1", country="South Korea"
        )

        # PIPA still appears — in the list of documents evaluated, which is
        # correct. What must be absent is the scope-limited caveat.
        assert "Note:" not in scope["disclaimer"]
        assert "scope-limited assessment" not in scope["disclaimer"]

    def test_the_note_is_country_specific_not_global(self):
        scope = tasks._build_scope_disclaimer(_FakeVS(["policy.pdf"]), "w1", country="Kenya")

        assert "PIPA" not in scope["disclaimer"]

    def test_the_disclaimer_always_states_the_scope_limit(self):
        disclaimer = tasks._build_scope_disclaimer(_FakeVS(["a.pdf"]), "w1")["disclaimer"]

        # Never an assessment of a country's complete governance apparatus.
        assert "not an assessment of the country" in disclaimer


class _FakeVS:
    def __init__(self, docs):
        self._docs = docs

    def get_workspace_documents(self, workspace_id):
        return self._docs


def _boom_store(*a, **kw):
    raise RuntimeError("vector store unavailable")
