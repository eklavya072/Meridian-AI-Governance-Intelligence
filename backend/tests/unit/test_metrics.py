"""Metrics must carry real values, and readiness must read them.

A /metrics endpoint that exposes nothing but zeros is worse than none: it
looks like observability on a dashboard screenshot and answers no question.
"""

import pytest
from fastapi.testclient import TestClient

import main
from src import metrics
from src.key_health import BREAKER_FAILURE_THRESHOLD, KeyHealthRegistry
from src.provider_errors import FailureKind


@pytest.fixture
def client():
    return TestClient(main.app)


def _scrape(client) -> str:
    response = client.get("/metrics")
    assert response.status_code == 200
    return response.text


class TestExposition:
    def test_metrics_endpoint_serves_prometheus_text(self, client):
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]

    def test_domain_metrics_are_present_not_just_process_metrics(self, client):
        body = _scrape(client)

        # These are the ones that would catch a silent quality regression.
        for name in (
            "meridian_citations_checked_total",
            "meridian_coverage_verdicts_total",
            "meridian_provider_failover_total",
            "meridian_stage_duration_seconds",
        ):
            assert name in body, name

    def test_a_provider_failure_does_not_break_the_scrape(self, client, monkeypatch):
        def _explode():
            raise RuntimeError("no provider configured")

        monkeypatch.setattr("src.provider_router.get_provider", _explode)

        # A scrape that fails when the provider is unavailable takes the
        # dashboard down at exactly the moment it is needed.
        assert client.get("/metrics").status_code == 200


class TestCitationMetrics:
    def test_pass_and_reject_are_counted_separately(self, client):
        metrics.record_citation_results(
            [{"verified": True}, {"verified": True}, {"verified": False}],
            dimension="Transparency",
        )

        body = _scrape(client)

        assert 'dimension="Transparency"' in body
        assert 'result="verified"' in body
        assert 'result="rejected"' in body

    def test_pass_rate_is_a_ratio_not_a_count(self, client):
        metrics.record_citation_results([{"verified": True}] * 3 + [{"verified": False}])

        line = next(
            ln for ln in _scrape(client).splitlines()
            if ln.startswith("meridian_citation_pass_rate ")
        )

        assert abs(float(line.split()[1]) - 0.75) < 1e-9

    def test_no_results_leaves_the_gauge_alone(self, client):
        metrics.citation_pass_rate.set(0.9)
        metrics.record_citation_results([])

        line = next(
            ln for ln in _scrape(client).splitlines()
            if ln.startswith("meridian_citation_pass_rate ")
        )

        # A run with nothing to verify must not read as a 0% pass rate — that
        # would page someone for a run that had no citations to check.
        assert float(line.split()[1]) == 0.9


class TestStageTiming:
    def test_a_timed_stage_records_a_duration(self, client):
        with metrics.timed_stage("verify"):
            pass

        body = _scrape(client)

        assert 'meridian_stage_duration_seconds_count{stage="verify"} 1.0' in body

    def test_a_raising_stage_is_still_recorded(self, client):
        with pytest.raises(ValueError), metrics.timed_stage("embed"):
            raise ValueError("boom")

        # A stage that dominates latency by failing slowly is exactly the one
        # worth measuring.
        assert 'meridian_stage_duration_seconds_count{stage="embed"} 1.0' in _scrape(client)


class TestReadinessReflectsCredentialHealth:
    def test_not_ready_when_every_credential_is_circuit_open(self, client, monkeypatch, tmp_path):
        registry = KeyHealthRegistry(path=tmp_path / "health.json")
        for _ in range(BREAKER_FAILURE_THRESHOLD):
            registry.record_failure("geminiprovider:0", FailureKind.QUOTA, "429")

        from src.provider_router import key_ids_for

        class _Provider:
            api_keys = ["k1"]

        provider = _Provider()
        # Ask for the ids the router itself would use, rather than hand-rolling
        # the string — the two drifting apart is what this indirection removes.
        for key_id in key_ids_for(provider):
            for _ in range(BREAKER_FAILURE_THRESHOLD):
                registry.record_failure(key_id, FailureKind.QUOTA, "429")

        monkeypatch.setattr(main, "get_vector_store", lambda: _Store())
        monkeypatch.setattr("src.provider_router.get_provider", lambda: provider)
        monkeypatch.setattr(main, "get_key_registry", lambda: registry)
        monkeypatch.setattr(
            "src.provider_router.quota_status",
            lambda: {
                "requests_today": 3,
                "daily_limit": 1000,
                "remaining": 997,
                "has_headroom": True,
                "date": "2026-08-30",
            },
        )

        response = client.get("/readyz")

        # Daily headroom is untouched, but nothing can actually serve. Before
        # credential health reached readiness this reported 200.
        assert response.status_code == 503
        provider = response.json()["checks"]["llm_provider"]
        assert provider["has_headroom"] is True
        assert provider["credentials_healthy"] == 0
        assert provider["ok"] is False


class _Store:
    def count_chunks(self):
        return 0
