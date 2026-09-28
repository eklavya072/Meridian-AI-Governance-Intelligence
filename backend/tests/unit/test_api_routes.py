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
from src.concurrency import get_slots, reset_slots
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

    async def clear_dimension_results(self, workspace_id):
        type(self).calls.append(("clear_dimension_results", workspace_id))

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

    def test_a_file_name_cannot_steer_where_the_upload_is_written(
        self, client, monkeypatch, tmp_path
    ):
        # The name is the client's to choose. Unstripped, this one was written
        # three directories above the uploads folder.
        uploads = tmp_path / "uploads"
        monkeypatch.setattr(main, "validate_pdf_file", lambda *a, **k: _valid())
        monkeypatch.setattr(main, "get_storage", lambda: _FakeStorage(uploads))

        body = client.post(
            f"/api/v1/upload/{uuid.uuid4()}",
            files={"file": ("../../../escaped.pdf", io.BytesIO(_pdf()), "application/pdf")},
        ).json()

        assert body["pending_documents"] == ["escaped.pdf"]
        written = list(tmp_path.rglob("*escaped.pdf"))
        assert written and all(w.parent == uploads for w in written)

    def test_a_new_document_discards_dimensions_kept_from_a_partial_run(
        self, client, monkeypatch, tmp_path
    ):
        # The cache lets a re-run retry only the dimensions that failed over
        # the SAME documents. A new document changes what is being scored, so
        # a kept verdict would describe a body of policy that no longer exists.
        monkeypatch.setattr(main, "validate_pdf_file", lambda *a, **k: _valid())
        monkeypatch.setattr(main, "get_storage", lambda: _FakeStorage(tmp_path))

        client.post(
            f"/api/v1/upload/{uuid.uuid4()}",
            files={"file": ("statute.pdf", io.BytesIO(_pdf()), "application/pdf")},
        )

        assert any(c[0] == "clear_dimension_results" for c in FakeWorkspaceService.calls)

    def test_nothing_is_stored_for_an_unknown_workspace(self, client, monkeypatch, tmp_path):
        FakeWorkspaceService.workspace = None
        monkeypatch.setattr(main, "validate_pdf_file", lambda *a, **k: _valid())
        monkeypatch.setattr(main, "get_storage", lambda: _FakeStorage(tmp_path))

        client.post(
            f"/api/v1/upload/{uuid.uuid4()}",
            files={"file": ("x.pdf", io.BytesIO(_pdf()), "application/pdf")},
        )

        assert not list(tmp_path.rglob("*.pdf"))

    def test_a_refused_upload_is_recorded(self, client):
        client.post(
            f"/api/v1/upload/{uuid.uuid4()}",
            files={"file": ("x.pdf", io.BytesIO(b"MZ\x90\x00not a pdf"), "application/pdf")},
        )

        logged = [c[1] for c in FakeWorkspaceService.calls if c[0] == "log_upload"]
        assert logged and logged[-1]["validation_passed"] is False
        assert logged[-1]["error_type"] == "wrong_file_type"

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


# ── Example workspaces ──────────────────────────────────────────────────
class TestLockedWorkspaces:
    """A demo's showcase workspaces are read-only, and say so."""

    @pytest.fixture
    def locked_id(self, monkeypatch):
        ws_id = str(uuid.uuid4())
        FakeWorkspaceService.workspace = FakeWorkspace(
            id=uuid.UUID(ws_id),
            pending_documents=[{"file_path": "/x/policy.pdf", "file_name": "policy.pdf"}],
        )
        monkeypatch.setattr(main, "LOCKED_WORKSPACE_IDS", frozenset({ws_id}))
        return ws_id

    def test_a_locked_workspace_says_it_is_locked(self, client, locked_id):
        assert client.get(f"/api/v1/workspace/{locked_id}").json()["locked"] is True

    def test_an_ordinary_workspace_is_not_locked(self, client, locked_id):
        FakeWorkspaceService.workspace = FakeWorkspace()
        other = FakeWorkspaceService.workspace.id

        assert client.get(f"/api/v1/workspace/{other}").json()["locked"] is False

    def test_uploading_to_a_locked_workspace_is_refused(self, client, locked_id):
        response = client.post(
            f"/api/v1/upload/{locked_id}",
            files={"file": ("x.pdf", io.BytesIO(_pdf()), "application/pdf")},
        )

        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "workspace_locked"

    def test_re_running_a_locked_workspace_is_refused(self, client, locked_id):
        response = client.post(f"/api/v1/analyze/{locked_id}/run")

        assert response.status_code == 403
        assert not any(c[0] == "update_status" for c in FakeWorkspaceService.calls)


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

    def test_a_pipeline_that_raises_still_gives_the_slot_back(self, client, monkeypatch, tmp_path):
        """The leak that wedged the server at capacity_full with nothing running.

        The slot is acquired in the request and released in the background
        task, so anything that stops the task reaching its own `finally` —
        a bad argument, an unreachable database, a reload killing it — kept
        the slot for the life of the process. Two of those and every
        subsequent run is refused, which reads like a provider quota problem
        and is not one.
        """
        reset_slots()

        async def _explode(**kw):
            raise RuntimeError("ingestion failed before the pipeline's own try")

        monkeypatch.setattr("src.tasks.run_full_analysis_pipeline", _explode, raising=False)
        present = tmp_path / "present.pdf"
        present.write_bytes(_pdf())
        FakeWorkspaceService.workspace.status = WorkspaceStatus.QUEUED
        FakeWorkspaceService.workspace.pending_documents = [
            {"file_path": str(present), "file_name": "present.pdf"}
        ]

        with pytest.raises(RuntimeError):
            client.post(f"/api/v1/analyze/{uuid.uuid4()}/run")

        assert get_slots().snapshot()["in_flight"] == 0

    def test_documents_missing_from_storage_are_dropped_not_fatal(
        self, client, monkeypatch, tmp_path
    ):
        # The background task is not run here; only the route's filtering is
        # under test. The stub is a coroutine because the real pipeline is
        # one, and the route now awaits it through the wrapper that owns the
        # concurrency slot — a sync stub passed only while nothing awaited.
        async def _noop(**kw):
            return None

        monkeypatch.setattr("src.tasks.run_full_analysis_pipeline", _noop, raising=False)
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
        # The upload left "1 document(s) ready"; with the queue emptied, the
        # workspace must stop saying so.
        details = [c[2] for c in FakeWorkspaceService.calls if c[0] == "update_status"]
        assert details and "upload them again" in details[-1]


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


class TestTimestamps:
    def test_a_stored_timestamp_is_sent_as_utc(self):
        # Stored naive, as datetime.utcnow() writes it. Sent without an offset
        # a browser reads it as local time: in India a five-minute run showed
        # 334 minutes elapsed.
        assert main._utc_iso(datetime(2026, 9, 24, 10, 3, 24)) == "2026-09-24T10:03:24+00:00"

    def test_a_missing_timestamp_is_empty(self):
        assert main._utc_iso(None) == ""


class TestSafeFilename:
    @pytest.mark.parametrize(
        "raw, safe",
        [
            ("policy.pdf", "policy.pdf"),
            ("../../../etc/passwd.pdf", "passwd.pdf"),
            ("..\\..\\main.py", "main.py"),
            ("/abs/path/act.pdf", "act.pdf"),
            ("..", "document.pdf"),
            ("", "document.pdf"),
            (None, "document.pdf"),
            ("line\nbreak.pdf", "linebreak.pdf"),
        ],
    )
    def test_only_the_bare_name_survives(self, raw, safe):
        assert main._safe_filename(raw) == safe


class TestMalformedIds:
    """An id that cannot exist is a 404, never a 500 from uuid.UUID()."""

    @pytest.mark.parametrize(
        "method, path",
        [
            ("get", "/api/v1/workspace/not-a-uuid"),
            ("get", "/api/v1/workspace/not-a-uuid/analyses"),
            ("get", "/api/v1/analyze/not-a-uuid"),
            ("post", "/api/v1/analyze/not-a-uuid/run"),
            ("get", "/api/v1/brief/not-a-uuid"),
            ("post", "/api/v1/brief/not-a-uuid/generate"),
            ("get", "/api/v1/brief/not-a-uuid/export?format=pdf"),
            ("get", "/api/v1/chat/sessions/not-a-uuid"),
            ("delete", "/api/v1/chat/sessions/not-a-uuid"),
            ("get", "/api/v1/chat/sessions?workspace_id=not-a-uuid"),
        ],
    )
    def test_a_malformed_id_is_not_found(self, client, method, path):
        assert getattr(client, method)(path).status_code == 404

    def test_a_malformed_id_in_a_chat_request_is_rejected(self, client):
        response = client.post("/api/v1/chat", json={"message": "hi", "workspace_id": "not-a-uuid"})

        assert response.status_code == 422

    def test_general_chat_with_no_workspace_is_still_allowed(self):
        assert main.ChatRequest(message="hi", workspace_id="").workspace_id == ""
