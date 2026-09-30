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

    async def get_analyses_for_workspace(self, workspace_id):
        return []

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
    def test_a_single_document_is_counted_and_recorded(self):
        scope = tasks._build_scope_disclaimer(_FakeVS(["strategy.pdf"]), "w1")

        assert "only the document supplied" in scope["disclaimer"]
        assert scope["documents"] == ["strategy.pdf"]

    def test_multiple_documents_are_counted(self):
        scope = tasks._build_scope_disclaimer(_FakeVS(["a.pdf", "b.pdf"]), "w1")

        # A multi-document workspace must not have the report imply it scored
        # only one of them.
        assert "the 2 documents supplied" in scope["disclaimer"]
        assert scope["documents"] == ["a.pdf", "b.pdf"]

    def test_an_empty_workspace_still_reads_as_a_sentence(self):
        disclaimer = tasks._build_scope_disclaimer(_FakeVS([]), "w1")["disclaimer"]

        assert "()" not in disclaimer
        assert "only the documents supplied" in disclaimer

    def test_the_country_is_named(self):
        scope = tasks._build_scope_disclaimer(_FakeVS(["policy.pdf"]), "w1", country="Kenya")

        assert "not Kenya's full AI governance framework" in scope["disclaimer"]

    def test_a_union_takes_the_article(self):
        scope = tasks._build_scope_disclaimer(
            _FakeVS(["EU AI ACT.pdf"]), "w1", country="European Union"
        )

        assert "not the European Union's full" in scope["disclaimer"]

    def test_it_stays_two_sentences(self):
        """Two or three lines on every country, never a paragraph."""
        scope = tasks._build_scope_disclaimer(
            _FakeVS(["EU AI ACT.pdf"]), "w1", country="European Union"
        )

        assert "Note:" not in scope["disclaimer"]
        assert len(scope["disclaimer"]) < 240

    def test_the_disclaimer_always_states_the_scope_limit(self):
        disclaimer = tasks._build_scope_disclaimer(_FakeVS(["a.pdf"]), "w1")["disclaimer"]

        # Never an assessment of a country's complete governance apparatus.
        assert "not the country's full AI governance framework" in disclaimer


class _FakeVS:
    def __init__(self, docs):
        self._docs = docs

    def get_workspace_documents(self, workspace_id):
        return self._docs


def _boom_store(*a, **kw):
    raise RuntimeError("vector store unavailable")


class TestCachedDimensionReuse:
    """A resumed run may reuse only what it would itself have produced."""

    NOW = {"provider": "gemini-3.5-flash", "evaluation": "per_dimension"}

    def _entry(self, dimension, **provider):
        from src.models import CoverageLevel, GovernanceGap

        gap = GovernanceGap(
            dimension=dimension,
            coverage=CoverageLevel.PARTIAL,
            reason_flagged="",
            recommendation="",
        )
        return {"status": "completed", "provider": provider, "result": gap.model_dump()}

    def test_an_answer_made_the_same_way_is_reused(self):
        from src.tasks import reusable_cached_gaps

        cached = {"Privacy": self._entry("Privacy", **self.NOW)}

        assert list(reusable_cached_gaps(cached, self.NOW, "w")) == ["Privacy"]

    def test_another_model_or_mode_is_analysed_again(self):
        from src.tasks import reusable_cached_gaps

        cached = {
            # A fallback model on a bad day, then the usual one the next.
            "Privacy": self._entry(
                "Privacy", provider="gemini-3.6-flash", evaluation="per_dimension"
            ),
            # A shared reply cites fewer passages than a dimension asked alone.
            "Safety": self._entry("Safety", provider="gemini-3.5-flash", evaluation="shared"),
            # Written before the mode was recorded: which one is unknown.
            "Fairness": self._entry("Fairness", provider="gemini-3.5-flash"),
        }

        assert reusable_cached_gaps(cached, self.NOW, "w") == {}

    def test_a_failed_dimension_is_never_reused(self):
        from src.tasks import reusable_cached_gaps

        cached = {"Privacy": {**self._entry("Privacy", **self.NOW), "status": "failed"}}

        assert reusable_cached_gaps(cached, self.NOW, "w") == {}
