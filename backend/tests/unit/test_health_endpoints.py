"""Liveness and readiness must fail independently.

The point of splitting them is that /healthz stays up when a dependency is
down — otherwise an orchestrator restarts a healthy process because Chroma
is slow, which is the failure this project has already lived through once.
"""

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    # No lifespan: the app's startup opens Postgres and warms the vector
    # store, neither of which a unit test should need. main._engine stays
    # None, which is itself one of the states /readyz has to report on.
    return TestClient(main.app)


class _FakeStore:
    def __init__(self, chunks=1234, boom=False):
        self._chunks = chunks
        self._boom = boom

    def count_chunks(self):
        if self._boom:
            raise RuntimeError("HNSW segment unreadable")
        return self._chunks


def test_healthz_touches_no_dependencies(client, monkeypatch):
    def _explode():
        raise AssertionError("liveness must not call the vector store")

    monkeypatch.setattr(main, "get_vector_store", _explode)

    r = client.get("/healthz")

    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_healthz_stays_up_when_readyz_is_down(client, monkeypatch):
    monkeypatch.setattr(main, "get_vector_store", lambda: _FakeStore(boom=True))

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503


def test_readyz_reports_503_with_no_database(client, monkeypatch):
    monkeypatch.setattr(main, "get_vector_store", lambda: _FakeStore())
    monkeypatch.setattr(main, "_engine", None)

    r = client.get("/readyz")
    body = r.json()

    assert r.status_code == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["ok"] is False


def test_readyz_reports_the_failing_dependency_by_name(client, monkeypatch):
    monkeypatch.setattr(main, "get_vector_store", lambda: _FakeStore(boom=True))

    body = client.get("/readyz").json()

    assert body["checks"]["vector_store"]["ok"] is False
    assert "HNSW" in body["checks"]["vector_store"]["error"]


def test_readyz_is_not_ready_when_the_daily_budget_is_spent(client, monkeypatch):
    monkeypatch.setattr(main, "get_vector_store", lambda: _FakeStore())
    monkeypatch.setattr(
        "src.provider_router.quota_status",
        lambda: {
            "requests_today": 1000,
            "daily_limit": 1000,
            "remaining": 0,
            "has_headroom": False,
            "date": "2026-08-30",
        },
    )

    r = client.get("/readyz")

    # Accepting an analysis with no headroom means failing partway through
    # it, which is worse than refusing traffic now.
    assert r.status_code == 503
    assert r.json()["checks"]["llm_provider"]["ok"] is False


def test_readyz_counts_chunks_when_the_store_is_healthy(client, monkeypatch):
    monkeypatch.setattr(main, "get_vector_store", lambda: _FakeStore(chunks=15468))

    body = client.get("/readyz").json()

    assert body["checks"]["vector_store"] == {"ok": True, "chunks": 15468}
