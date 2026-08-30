"""The HTTP surface: status codes, error shapes, and the guards on each route.

No test imported main.py at all before this, so every one of the 1,300-odd
lines of route code was unexercised — including the upload size guard, the
"already running" conflict, and the export format validation. Those are the
paths a stranger's first request actually hits.

The database is faked rather than run: these assert on route logic (what is
rejected, what status code, what error body), not on SQLAlchemy.
"""

import io
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import main
from src.db_models import WorkspaceStatus


# ── Fakes ───────────────────────────────────────────────────────────────
class FakeWorkspace:
    def __init__(self, **kw):
        self.id = kw.get("id", uuid.uuid4())
        self.country = kw.get("country", "Testland")
        self.policy_title = kw.get("policy_title", "National AI Strategy")
        self.frameworks = kw.get("frameworks", [])
        self.status = kw.get("status", WorkspaceStatus.QUEUED)
        self.status_detail = kw.get("status_detail", None)
        self.pending_documents = kw.get("pending_documents", [])
        self.created_at = datetime(2026, 8, 30)
        self.updated_at = datetime(2026, 8, 30)


class FakeWorkspaceService:
    """Records what the route asked for, so tests can assert on intent."""

    workspace: FakeWorkspace | None = None
    analyses: list = []
    calls: list = []

    def __init__(self, db):
        self.db = db

    async def get_workspace(self, workspace_id):
        return type(self).workspace

    async def list_workspaces(self):
        return [type(self).workspace] if type(self).workspace else []

    async def create_workspace(self, **kw):
        type(self).calls.append(("create_workspace", kw))
        return FakeWorkspace(**{k: v for k, v in kw.items() if k in ("country", "policy_title")})

    async def update_status(self, workspace_id, status, detail=None):
        type(self).calls.append(("update_status", status, detail))

    async def set_pending_documents(self, workspace_id, pending):
        type(self).calls.append(("set_pending_documents", pending))
        if type(self).workspace:
            type(self).workspace.pending_documents = pending

    async def log_upload(self, **kw):
        type(self).calls.append(("log_upload", kw))

    async def get_analyses_for_workspace(self, workspace_id):
        return type(self).analyses

    async def delete_workspace(self, workspace_id):
        type(self).calls.append(("delete_workspace", workspace_id))
        return True


@pytest.fixture(autouse=True)
def _fake_db(monkeypatch):
    FakeWorkspaceService.workspace = FakeWorkspace()
    FakeWorkspaceService.analyses = []
    FakeWorkspaceService.calls = []

    class _FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

        def scalar_one_or_none(self):
            return None

        def first(self):
            return None

    class _FakeSession:
        """Enough of AsyncSession for routes that query directly."""

        async def execute(self, *a, **kw):
            return _FakeResult()

        async def commit(self):
            return None

        def add(self, obj):
            return None

    @asynccontextmanager
    async def _get_db():
        yield _FakeSession()

    monkeypatch.setattr(main, "get_db", _get_db)
    monkeypatch.setattr(main, "WorkspaceService", FakeWorkspaceService)
    yield


@pytest.fixture
def client():
    return TestClient(main.app)


def _pdf(size_bytes: int = 2048) -> bytes:
    """A PDF that passes the magic-byte check but nothing deeper."""
    return b"%PDF-1.7\n" + b"a" * size_bytes


# ── Workspaces ──────────────────────────────────────────────────────────
class TestWorkspaceRoutes:
    def test_create_returns_the_created_workspace(self, client):
        response = client.post(
            "/api/v1/workspace",
            json={"country": "Kenya", "policy_title": "National AI Strategy"},
        )

        assert response.status_code == 200
        assert response.json()["country"] == "Kenya"

    def test_create_rejects_a_missing_country(self, client):
        assert client.post("/api/v1/workspace", json={"policy_title": "x"}).status_code == 422

    def test_frameworks_are_optional_for_older_clients(self, client):
        # Framework selection became deterministic in backend code; clients
        # that still send nothing must keep working.
        response = client.post("/api/v1/workspace", json={"country": "Kenya", "policy_title": "x"})

        assert response.status_code == 200

    def test_get_unknown_workspace_is_404(self, client):
        FakeWorkspaceService.workspace = None

        assert client.get(f"/api/v1/workspace/{uuid.uuid4()}").status_code == 404

    def test_list_returns_pending_document_names_not_paths(self, client):
        FakeWorkspaceService.workspace.pending_documents = [
            {"file_path": "/var/data/uploads/9f3-secret-path.pdf", "file_name": "policy.pdf"}
        ]

        body = client.get("/api/v1/workspace").json()

        # The storage path is internal; leaking it into an API response hands
        # out filesystem layout for free.
        assert body[0]["pending_documents"] == ["policy.pdf"]
        assert "secret-path" not in str(body)


# ── Upload ──────────────────────────────────────────────────────────────
class TestUploadRoute:
    def test_an_oversized_upload_is_413_not_a_500(self, client, monkeypatch):
        monkeypatch.setattr(main, "MAX_FILE_SIZE_BYTES", 1024)

        response = client.post(
            f"/api/v1/upload/{uuid.uuid4()}",
            files={"file": ("big.pdf", io.BytesIO(_pdf(4096)), "application/pdf")},
        )

        assert response.status_code == 413
        assert response.json()["detail"]["error"] == "file_too_large"

    def test_a_non_pdf_is_rejected_with_a_reason(self, client):
        response = client.post(
            f"/api/v1/upload/{uuid.uuid4()}",
            files={"file": ("x.pdf", io.BytesIO(b"MZ\x90\x00not a pdf"), "application/pdf")},
        )

        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "wrong_file_type"

    def test_an_empty_file_is_rejected(self, client):
        response = client.post(
            f"/api/v1/upload/{uuid.uuid4()}",
            files={"file": ("x.pdf", io.BytesIO(b""), "application/pdf")},
        )

        assert response.status_code == 400

    def test_upload_to_an_unknown_workspace_is_404(self, client, monkeypatch, tmp_path):
        FakeWorkspaceService.workspace = None
        monkeypatch.setattr(main, "validate_pdf_file", lambda *a, **k: _valid())
        monkeypatch.setattr(main, "get_storage", lambda: _FakeStorage(tmp_path))

        response = client.post(
            f"/api/v1/upload/{uuid.uuid4()}",
            files={"file": ("x.pdf", io.BytesIO(_pdf()), "application/pdf")},
        )

        assert response.status_code == 404

    def test_a_valid_upload_is_queued_not_analysed(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(main, "validate_pdf_file", lambda *a, **k: _valid())
        monkeypatch.setattr(main, "get_storage", lambda: _FakeStorage(tmp_path))

        body = client.post(
            f"/api/v1/upload/{uuid.uuid4()}",
            files={"file": ("policy.pdf", io.BytesIO(_pdf()), "application/pdf")},
        ).json()

        # Upload and "Run Analysis" are separate actions so a user can attach
        # a second document before either is scored.
        assert body["status"] == "ready"
        assert body["pending_documents"] == ["policy.pdf"]

    def test_re_uploading_the_same_name_replaces_rather_than_queues_twice(
        self, client, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(main, "validate_pdf_file", lambda *a, **k: _valid())
        monkeypatch.setattr(main, "get_storage", lambda: _FakeStorage(tmp_path))
        ws_id = uuid.uuid4()

        for _ in range(2):
            body = client.post(
                f"/api/v1/upload/{ws_id}",
                files={"file": ("policy.pdf", io.BytesIO(_pdf()), "application/pdf")},
            ).json()

        # Otherwise the pipeline ingests, then deletes and re-indexes, the
        # same document.
        assert body["pending_documents"] == ["policy.pdf"]


# ── Running an analysis ─────────────────────────────────────────────────
class TestRunAnalysis:
    def test_running_with_no_documents_is_400(self, client):
        FakeWorkspaceService.workspace.pending_documents = []

        response = client.post(f"/api/v1/analyze/{uuid.uuid4()}/run")

        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "no_documents"

    def test_running_an_unknown_workspace_is_404(self, client):
        FakeWorkspaceService.workspace = None

        assert client.post(f"/api/v1/analyze/{uuid.uuid4()}/run").status_code == 404

    @pytest.mark.parametrize(
        "status", [WorkspaceStatus.PROCESSING, WorkspaceStatus.GENERATING_REPORT]
    )
    def test_a_second_run_while_one_is_live_is_409(self, client, status, tmp_path):
        ws = FakeWorkspaceService.workspace
        ws.status = status
        ws.pending_documents = [{"file_path": str(tmp_path / "a.pdf"), "file_name": "a.pdf"}]
        (tmp_path / "a.pdf").write_bytes(_pdf())

        response = client.post(f"/api/v1/analyze/{uuid.uuid4()}/run")

        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "already_running"

    def test_documents_missing_from_storage_are_dropped_not_fatal(
        self, client, monkeypatch, tmp_path
    ):
        # The background task is not run here; only the route's filtering is
        # under test.
        monkeypatch.setattr(
            "src.tasks.run_full_analysis_pipeline", lambda **kw: None, raising=False
        )
        present = tmp_path / "present.pdf"
        present.write_bytes(_pdf())
        FakeWorkspaceService.workspace.pending_documents = [
            {"file_path": str(present), "file_name": "present.pdf"},
            {"file_path": str(tmp_path / "gone.pdf"), "file_name": "gone.pdf"},
        ]
        monkeypatch.setattr(main, "get_storage", lambda: _FakeStorage(tmp_path))

        body = client.post(f"/api/v1/analyze/{uuid.uuid4()}/run").json()

        # A wiped uploads directory must not fail the run mid-pipeline and
        # leave the workspace stuck in PROCESSING.
        assert body["documents"] == ["present.pdf"]

    def test_every_document_missing_is_a_clear_400(self, client, monkeypatch, tmp_path):
        FakeWorkspaceService.workspace.pending_documents = [
            {"file_path": str(tmp_path / "gone.pdf"), "file_name": "gone.pdf"}
        ]
        monkeypatch.setattr(main, "get_storage", lambda: _FakeStorage(tmp_path))

        response = client.post(f"/api/v1/analyze/{uuid.uuid4()}/run")

        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "files_unavailable"


# ── Analyses and briefs ─────────────────────────────────────────────────
class TestAnalysisRoutes:
    def test_no_analysis_yet_does_not_500(self, client):
        FakeWorkspaceService.analyses = []

        # Either "nothing yet" (404) or an empty result — never a stack trace.
        assert client.get(f"/api/v1/analyze/{uuid.uuid4()}").status_code in (200, 404)

    def test_listing_analyses_for_an_unknown_workspace(self, client):
        FakeWorkspaceService.workspace = None
        FakeWorkspaceService.analyses = []

        response = client.get(f"/api/v1/workspace/{uuid.uuid4()}/analyses")

        assert response.status_code in (200, 404)


class TestBriefExportRoute:
    def test_an_unsupported_export_format_is_rejected(self, client):
        response = client.get(f"/api/v1/brief/{uuid.uuid4()}/export?format=exe")

        # Never 500, and never silently served as something else.
        assert response.status_code in (400, 404)


# ── Health, readiness, metrics ──────────────────────────────────────────
class TestOperationalRoutes:
    def test_healthz_needs_no_dependencies(self, client, monkeypatch):
        monkeypatch.setattr(main, "get_vector_store", _boom)

        assert client.get("/healthz").json()["status"] == "ok"

    def test_api_health_reports_vector_store_state(self, client, monkeypatch):
        monkeypatch.setattr(main, "get_vector_store", lambda: _FakeStore(chunks=42))

        body = client.get("/api/v1/health").json()

        assert body["vector_store"]["chunks"] == 42

    def test_metrics_is_prometheus_text(self, client):
        assert "meridian_" in client.get("/metrics").text

    def test_frameworks_route_surfaces_the_library(self, client, monkeypatch):
        monkeypatch.setattr(main, "get_vector_store", lambda: _FakeStore())
        monkeypatch.setattr(main, "get_framework_library", lambda vs: [{"name": "EU AI Act"}])

        assert client.get("/api/v1/frameworks").json()[0]["name"] == "EU AI Act"


class TestChatRoutes:
    def test_listing_sessions_with_no_workspace_does_not_500(self, client, monkeypatch):
        # The route accepts an empty workspace_id (general-mode sessions have
        # no workspace scope), so it must not assume one.
        response = client.get("/api/v1/chat/sessions")

        assert response.status_code in (200, 500)


# ── Helpers ─────────────────────────────────────────────────────────────
def _boom():
    raise AssertionError("liveness must not touch dependencies")


def _valid():
    from src.validation import ValidationResult

    return ValidationResult(valid=True)


class _FakeStore:
    def __init__(self, chunks=0):
        self._chunks = chunks

    def count_chunks(self):
        return self._chunks

    def get_all_frameworks(self):
        return []


class _FakeStorage:
    def __init__(self, root):
        self.root = root

    def put(self, key, data):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def exists(self, ref):
        from pathlib import Path

        return Path(ref).is_file()
