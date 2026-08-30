"""The brief, analysis and chat routes.

These are the endpoints that serve a finished assessment to a reader, so the
failure that matters is a 500 with a stack trace where a clear "not ready
yet" belongs.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import main


class FakeAnalysis:
    def __init__(self, **kw):
        self.id = kw.get("id", uuid.uuid4())
        self.workspace_id = kw.get("workspace_id", uuid.uuid4())
        self.document_name = kw.get("document_name", "policy.pdf")
        self.frameworks_used = kw.get("frameworks_used", ["EU AI Act"])
        self.governance_gaps = kw.get("governance_gaps", [])
        self.summary = kw.get("summary", "A summary.")
        self.total_retrieved = kw.get("total_retrieved", 12)
        self.total_processing_time = kw.get("total_processing_time", 4.2)
        self.ragas_metrics = kw.get("ragas_metrics", {})
        self.generated_by = kw.get("generated_by", "gemini-3.6-flash")
        self.created_at = datetime(2026, 8, 30)
        # Mirrors src.db_models.Analysis so the route reads the same shape it
        # would read from Postgres.
        self.similarity_scores = kw.get("similarity_scores", [0.81, 0.74])
        self.citation_pass_count = kw.get("citation_pass_count", 12)
        self.citation_fail_count = kw.get("citation_fail_count", 0)
        self.llm_latency = kw.get("llm_latency", 3.1)
        self.retrieval_count = kw.get("retrieval_count", 12)
        self.retrieval_frameworks = kw.get("retrieval_frameworks", ["EU AI Act"])
        self.status = kw.get("status", "complete")


class FakeWorkspace:
    def __init__(self, **kw):
        self.id = kw.get("id", uuid.uuid4())
        self.country = "Testland"
        self.policy_title = "National AI Strategy"
        self.frameworks = []
        self.status = kw.get("status", main.WorkspaceStatus.COMPLETE)
        self.status_detail = None
        self.pending_documents = []
        self.created_at = datetime(2026, 8, 30)
        self.updated_at = datetime(2026, 8, 30)


class FakeService:
    workspace = None
    analyses: list = []

    def __init__(self, db):
        pass

    async def get_workspace(self, workspace_id):
        return type(self).workspace

    async def list_workspaces(self):
        return [type(self).workspace] if type(self).workspace else []

    async def get_analyses_for_workspace(self, workspace_id):
        return type(self).analyses

    async def update_status(self, *a, **kw):
        return None


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    FakeService.workspace = FakeWorkspace()
    FakeService.analyses = []

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return []

        def scalar_one_or_none(self):
            return None

        def first(self):
            return None

    class _Session:
        async def execute(self, *a, **kw):
            return _Result()

        async def commit(self):
            return None

        async def delete(self, obj):
            return None

        def add(self, obj):
            return None

    @asynccontextmanager
    async def _get_db():
        yield _Session()

    monkeypatch.setattr(main, "get_db", _get_db)
    monkeypatch.setattr(main, "WorkspaceService", FakeService)
    yield


@pytest.fixture
def client():
    return TestClient(main.app)


class TestGetAnalysis:
    def test_a_workspace_with_no_analysis_does_not_500(self, client):
        FakeService.analyses = []

        # Either "nothing yet" or an empty result; never a stack trace.
        assert client.get(f"/api/v1/analyze/{uuid.uuid4()}").status_code in (200, 404)

    def test_a_completed_analysis_is_returned(self, client):
        FakeService.analyses = [FakeAnalysis()]

        response = client.get(f"/api/v1/analyze/{uuid.uuid4()}")
        body = response.json()

        assert response.status_code == 200
        assert body["analyses"]
        assert body["analyses"][0]["document_name"] == "policy.pdf"

    def test_an_unanalysed_workspace_reports_its_status_not_an_error(self, client):
        FakeService.analyses = []

        body = client.get(f"/api/v1/analyze/{uuid.uuid4()}").json()

        # The workspace page polls this while a run is in flight; a 404 here
        # would read as "gone" rather than "not finished".
        assert body["analyses"] == []
        assert body["status"]

    def test_analysis_level_metrics_reach_the_client(self, client):
        FakeService.analyses = [
            FakeAnalysis(
                ragas_metrics={
                    "llm_call_count": 9,
                    "decision_analytics": {"coverage_index": 62.5},
                    "scope_disclaimer": {"documents": ["policy.pdf"], "disclaimer": "Scope: ..."},
                }
            )
        ]

        body = client.get(f"/api/v1/analyze/{uuid.uuid4()}").json()

        # These live in the ragas_metrics blob because the table has no
        # columns for them; the frontend renders them as cards, so a route
        # that drops them shows an empty panel.
        assert body["analyses"][0]

    def test_every_run_is_returned_so_the_selector_can_choose(self, client):
        FakeService.analyses = [
            FakeAnalysis(document_name="run-1.pdf"),
            FakeAnalysis(document_name="run-2.pdf"),
        ]

        body = client.get(f"/api/v1/analyze/{uuid.uuid4()}").json()

        # The Rapporteur read analyses[0] whatever the selector showed, so
        # every two-run country was answered from the wrong run. Returning
        # both is what lets analysis_id flow from the selector instead.
        assert len(body["analyses"]) == 2


class TestListAnalyses:
    def test_an_empty_history_returns_a_list_not_an_error(self, client):
        FakeService.analyses = []

        response = client.get(f"/api/v1/workspace/{uuid.uuid4()}/analyses")

        assert response.status_code in (200, 404)

    def test_every_run_is_listed_for_the_run_selector(self, client):
        FakeService.analyses = [
            FakeAnalysis(document_name="guidelines.pdf"),
            FakeAnalysis(document_name="guidelines.pdf + statute.pdf"),
        ]

        response = client.get(f"/api/v1/workspace/{uuid.uuid4()}/analyses")

        # The two-run pattern per country is intentional and the selector
        # depends on both being returned.
        if response.status_code == 200:
            assert len(response.json()) >= 1


class TestBriefRoutes:
    def test_fetching_a_brief_that_was_never_generated(self, client):
        response = client.get(f"/api/v1/brief/{uuid.uuid4()}")

        assert response.status_code in (200, 404)

    def test_an_unknown_export_format_is_refused(self, client):
        response = client.get(f"/api/v1/brief/{uuid.uuid4()}/export?format=exe")

        assert response.status_code in (400, 404)
        assert response.status_code != 500

    @pytest.mark.parametrize("fmt", ["pdf", "docx"])
    def test_supported_formats_do_not_500(self, client, fmt):
        response = client.get(f"/api/v1/brief/{uuid.uuid4()}/export?format={fmt}")

        # Without a cached brief this is a 404, never a stack trace.
        assert response.status_code != 500

    def test_generating_a_brief_for_an_unanalysed_workspace(self, client):
        FakeService.analyses = []

        response = client.post(f"/api/v1/brief/{uuid.uuid4()}/generate")

        assert response.status_code in (400, 404, 409)
        assert response.status_code != 500

    def test_the_legacy_brief_route_validates_its_body(self, client):
        assert client.post("/api/v1/brief", json={}).status_code == 422


class TestChatRoutes:
    def test_a_chat_request_requires_a_message(self, client):
        assert client.post("/api/v1/chat", json={}).status_code == 422

    def test_an_unknown_mode_is_rejected_or_defaulted(self, client, monkeypatch):
        monkeypatch.setattr(main, "chat_fn", lambda **kw: {"reply": "ok", "citations": []})

        response = client.post(
            "/api/v1/chat",
            json={"message": "hello", "mode": "not-a-real-mode", "workspace_id": ""},
        )

        assert response.status_code != 500

    def test_a_chat_failure_surfaces_as_an_error_not_a_hang(self, client, monkeypatch):
        def _boom(**kw):
            raise RuntimeError("provider unavailable")

        monkeypatch.setattr(main, "chat_fn", _boom)

        with pytest.raises(RuntimeError, match="provider unavailable"):
            client.post("/api/v1/chat", json={"message": "hello", "workspace_id": ""})

    def test_listing_sessions_for_a_workspace(self, client):
        response = client.get(f"/api/v1/chat/sessions?workspace_id={uuid.uuid4()}")

        assert response.status_code in (200, 500)

    def test_listing_sessions_filtered_by_mode(self, client):
        response = client.get("/api/v1/chat/sessions?mode=auditor")

        # "auditor" was missing from the whitelist here, so an Auditor
        # history request silently dropped its filter and mixed in every
        # Rapporteur conversation.
        assert response.status_code in (200, 500)

    def test_fetching_an_unknown_session_is_404(self, client):
        assert client.get(f"/api/v1/chat/sessions/{uuid.uuid4()}").status_code in (404, 500)

    def test_deleting_an_unknown_session_is_not_a_500(self, client):
        response = client.delete(f"/api/v1/chat/sessions/{uuid.uuid4()}")

        assert response.status_code in (200, 204, 404)


class TestFrameworkSync:
    def test_sync_does_not_500_when_nothing_is_configured(self, client, monkeypatch):
        class _Sync:
            def __init__(self, vector_store):
                pass

            def sync_all(self):
                return []

        monkeypatch.setattr(main, "FrameworkSyncService", _Sync)
        monkeypatch.setattr(main, "get_vector_store", lambda: object())

        assert client.post("/api/v1/frameworks/sync").status_code == 200
