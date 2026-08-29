"""Provider failure handling, against a mocked provider.

Every scenario the brief names — a 429 storm, one credential exhausted, all
credentials exhausted, a timeout mid-analysis — plus the classification bug
that made a retired model look like spent quota.

No network, no quota, deterministic.
"""

import time

import pytest

from src.key_health import (
    BREAKER_FAILURE_THRESHOLD,
    CircuitState,
    KeyHealthRegistry,
)
from src.provider_errors import FailureKind, classify


class _Response:
    def __init__(self, status_code=None, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class _ProviderError(Exception):
    """Shaped like a real SDK exception: message plus an optional response."""

    def __init__(self, message, status_code=None, headers=None):
        super().__init__(message)
        self.response = _Response(status_code, headers)
        self.status_code = status_code


# ── classification ──────────────────────────────────────────────────────


class TestClassification:
    def test_429_is_quota(self):
        assert classify(_ProviderError("429 Too Many Requests", 429)).kind is FailureKind.QUOTA

    def test_resource_exhausted_is_quota_without_a_status(self):
        assert classify(Exception("RESOURCE_EXHAUSTED: quota met")).kind is FailureKind.QUOTA

    def test_retired_model_is_terminal_not_quota(self):
        # The bug this file exists for. A 404 was raised as QuotaExceededError,
        # so the router rotated through every credential, fell through to the
        # fallback, and reported "all keys exhausted" — when the real fix is
        # one line in .env.
        failure = classify(_ProviderError("404 model not found: llama-3.3-70b", 404))

        assert failure.kind is FailureKind.TERMINAL
        assert not failure.is_retryable

    def test_invalid_api_key_is_terminal(self):
        assert classify(Exception("API key not valid")).kind is FailureKind.TERMINAL

    def test_bad_request_is_terminal_not_retried_forever(self):
        # A 400 used to fall through to the generic handler and get retried
        # MAX_RETRIES times against a request that could never succeed.
        assert classify(_ProviderError("400 invalid argument", 400)).kind is FailureKind.TERMINAL

    def test_5xx_is_retryable(self):
        assert (
            classify(_ProviderError("503 Service Unavailable", 503)).kind is FailureKind.RETRYABLE
        )

    def test_timeout_is_retryable(self):
        assert classify(Exception("deadline exceeded")).kind is FailureKind.RETRYABLE

    def test_unknown_failure_is_retryable_not_quota(self):
        # Burning a healthy credential on an unrecognised error is the worse
        # of the two mistakes; the caller's retry budget still bounds it.
        assert classify(Exception("something odd happened")).kind is FailureKind.RETRYABLE

    def test_the_word_accurate_is_not_a_rate_limit(self):
        # The old check was `"rate" in error_str.lower()`.
        assert classify(Exception("Response was not accurate")).kind is not FailureKind.QUOTA


class TestRetryAfter:
    def test_header_is_preferred_over_prose(self):
        failure = classify(_ProviderError("429 slow down, retry in 99s", 429, {"Retry-After": "7"}))

        # The provider's own header is authoritative; the previous code only
        # ever scraped the message and ignored it.
        assert failure.retry_after_seconds == 7.0

    def test_prose_is_used_when_no_header_exists(self):
        assert classify(Exception("429: retry in 12.5s")).retry_after_seconds == 12.5

    def test_google_retry_delay_form_is_read(self):
        assert classify(Exception("{'retryDelay': '30s'}")).retry_after_seconds == 30.0

    def test_absent_retry_after_is_none_not_zero(self):
        # None means "no instruction, use our backoff"; 0.0 would mean
        # "retry immediately", which is a different and much worse answer.
        assert classify(Exception("429 too many requests")).retry_after_seconds is None


# ── circuit breaker ─────────────────────────────────────────────────────


@pytest.fixture
def registry(tmp_path):
    return KeyHealthRegistry(path=tmp_path / "health.json")


class TestCircuitBreaker:
    def test_a_single_429_does_not_drop_a_credential(self, registry):
        # One 429 is ordinary free-tier behaviour, not a sick credential.
        registry.record_failure("k1", FailureKind.QUOTA, "429")

        assert registry.is_available("k1")

    def test_repeated_failures_open_the_circuit(self, registry):
        for _ in range(BREAKER_FAILURE_THRESHOLD):
            registry.record_failure("k1", FailureKind.QUOTA, "429")

        assert not registry.is_available("k1")
        assert registry.snapshot(["k1"])["keys"][0]["state"] == CircuitState.OPEN.value

    def test_a_terminal_failure_opens_the_circuit_immediately(self, registry):
        # No point spending two more attempts proving the key is still invalid.
        registry.record_failure("k1", FailureKind.TERMINAL, "API key not valid")

        assert not registry.is_available("k1")

    def test_success_resets_the_failure_run(self, registry):
        registry.record_failure("k1", FailureKind.QUOTA, "429")
        registry.record_failure("k1", FailureKind.QUOTA, "429")
        registry.record_success("k1")
        registry.record_failure("k1", FailureKind.QUOTA, "429")

        # Three failures total, but not three consecutively.
        assert registry.is_available("k1")

    def test_cooldown_admits_exactly_one_probe(self, registry, monkeypatch):
        for _ in range(BREAKER_FAILURE_THRESHOLD):
            registry.record_failure("k1", FailureKind.TERMINAL, "boom")
        assert not registry.is_available("k1")

        # monotonic() is seconds since boot, not epoch — advancing the wall
        # clock has to start from the wall clock.
        future = time.time() + 10_000
        monkeypatch.setattr(time, "time", lambda: future)

        assert registry.is_available("k1"), "cooldown elapsed, one probe expected"
        # A second caller must not also get through — that would be a storm,
        # not a probe.
        assert not registry.is_available("k1")

    def test_a_successful_probe_returns_the_credential_to_rotation(self, registry, monkeypatch):
        for _ in range(BREAKER_FAILURE_THRESHOLD):
            registry.record_failure("k1", FailureKind.QUOTA, "429")
        future = time.time() + 10_000
        monkeypatch.setattr(time, "time", lambda: future)
        registry.is_available("k1")  # take the probe

        registry.record_success("k1")

        assert registry.is_available("k1")
        assert registry.snapshot(["k1"])["keys"][0]["state"] == CircuitState.CLOSED.value

    def test_provider_retry_after_extends_the_cooldown(self, registry):
        registry.record_failure("k1", FailureKind.TERMINAL, "429", retry_after=3600)

        # Our default cooldown is 60s; the provider asked for an hour, and its
        # instruction wins.
        assert registry.snapshot(["k1"])["keys"][0]["seconds_until_probe"] > 60


class TestRotation:
    def test_one_credential_exhausted_routes_to_the_others(self, registry):
        keys = ["k1", "k2", "k3"]
        for _ in range(BREAKER_FAILURE_THRESHOLD):
            registry.record_failure("k1", FailureKind.QUOTA, "429")

        chosen = registry.next_available(keys, start=0)

        assert chosen in ("k2", "k3")
        assert registry.available_keys(keys) == ["k2", "k3"]

    def test_a_429_storm_does_not_re_ask_a_dropped_credential(self, registry):
        keys = ["k1", "k2"]
        # Every credential 429s repeatedly, as in a real storm.
        for _ in range(BREAKER_FAILURE_THRESHOLD):
            for k in keys:
                registry.record_failure(k, FailureKind.QUOTA, "429")

        # Before the breaker, round-robin would keep handing these back and
        # the retry budget would be spent re-asking exhausted credentials.
        assert registry.available_keys(keys) == []
        assert registry.next_available(keys) is None

    def test_all_credentials_exhausted_reports_when_to_retry(self, registry):
        keys = ["k1", "k2"]
        for _ in range(BREAKER_FAILURE_THRESHOLD):
            for k in keys:
                registry.record_failure(k, FailureKind.QUOTA, "429", retry_after=45)

        wait = registry.seconds_until_any_available(keys)

        # "Capacity exhausted, retry after X" needs a real X — a silent hang
        # or a bare failure is what this replaces.
        assert 0 < wait < 3600

    def test_a_spent_daily_budget_is_not_a_timer(self, tmp_path):
        registry = KeyHealthRegistry(path=tmp_path / "h.json", daily_limit=2)
        registry.record_success("k1")
        registry.record_success("k1")

        assert not registry.is_available("k1")
        # It does not come back after a cooldown; it comes back tomorrow.
        assert registry.seconds_until_any_available(["k1"]) == float("inf")


class TestQuotaAccountingPersistence:
    def test_counts_survive_a_restart(self, tmp_path):
        path = tmp_path / "health.json"
        first = KeyHealthRegistry(path=path)
        first.record_success("k1", tokens=1200)
        first.record_success("k2", tokens=800)

        # A new process, mid-day.
        second = KeyHealthRegistry(path=path)
        snap = second.snapshot(["k1", "k2"])

        assert snap["total_requests"] == 2
        assert snap["total_tokens"] == 2000

    def test_counts_are_per_credential_not_pooled(self, tmp_path):
        registry = KeyHealthRegistry(path=tmp_path / "h.json")
        registry.record_success("k1", tokens=100)
        registry.record_success("k1", tokens=100)
        registry.record_success("k2", tokens=50)

        by_id = {k["key_id"]: k for k in registry.snapshot(["k1", "k2"])["keys"]}

        # The old global counter could not answer this question at all.
        assert by_id["k1"]["requests"] == 2
        assert by_id["k2"]["requests"] == 1
        assert by_id["k1"]["tokens"] == 200

    def test_a_new_day_starts_clean(self, tmp_path, monkeypatch):
        path = tmp_path / "health.json"
        first = KeyHealthRegistry(path=path)
        first.record_success("k1", tokens=999)

        monkeypatch.setattr(time, "strftime", lambda *a, **k: "2099-01-01")
        second = KeyHealthRegistry(path=path)

        assert second.snapshot(["k1"])["total_requests"] == 0

    def test_a_corrupt_health_file_does_not_crash_startup(self, tmp_path):
        path = tmp_path / "health.json"
        path.write_text("{not json at all")

        registry = KeyHealthRegistry(path=path)

        # Losing today's counts is bad; refusing to boot is worse.
        assert registry.snapshot([])["total_requests"] == 0


class TestConcurrency:
    def test_concurrent_accounting_loses_no_requests(self, tmp_path):
        import threading

        registry = KeyHealthRegistry(path=tmp_path / "h.json")

        def worker():
            for _ in range(50):
                registry.record_success("k1", tokens=1)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # The analysis pipeline runs dimensions concurrently; an unguarded
        # read-modify-write silently loses requests from the daily tally.
        assert registry.snapshot(["k1"])["total_requests"] == 200
