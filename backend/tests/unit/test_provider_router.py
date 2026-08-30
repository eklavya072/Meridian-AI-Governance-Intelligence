"""The retry loop itself, driven end to end against fake providers.

test_provider_resilience.py covers the classifier and the breaker in
isolation. This covers what the router does with them: which credential a
call lands on, when it rotates, when it falls back, when it gives up, and
what it says when it does.

Every sleep is patched out. A test suite that actually waits out an
exponential backoff is a test suite people skip.
"""

import threading

import pytest
from pydantic import BaseModel

from src import provider_router as pr
from src.key_health import BREAKER_FAILURE_THRESHOLD, KeyHealthRegistry
from src.llm_provider import (
    QuotaExceededError,
    RetryableError,
    TerminalProviderError,
)


class Reply(BaseModel):
    answer: str


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch, tmp_path):
    """Patch out every wait, and isolate the persisted counters."""
    monkeypatch.setattr(pr.time, "sleep", lambda *_: None)
    monkeypatch.setattr(pr, "GEMINI_RPD_FILE", str(tmp_path / "rpd.json"))
    monkeypatch.setattr(pr, "_daily_gemini_requests", 0)
    # ONE registry for the test, not a fresh one per call — otherwise writes
    # and reads land on different instances and every breaker assertion
    # silently passes against empty state.
    registry = KeyHealthRegistry(path=tmp_path / "health.json")
    monkeypatch.setattr(pr, "get_registry", lambda: registry)
    pr._debug_stats["primary_requests"].clear()
    yield


class FakeGemini(pr.GeminiProvider):
    """A GeminiProvider that never touches the network.

    Subclassed rather than mocked because the router branches on
    isinstance(provider, GeminiProvider) in a dozen places; a duck-typed
    stand-in would take different paths through the code than production.
    """

    def __init__(self, keys=2, script=None):
        self.api_keys = [f"key-{i}" for i in range(keys)]
        self.current_key_index = 0
        self._rotation_lock = threading.Lock()
        self.model_name_str = "fake-flash"
        # One entry consumed per call; an Exception is raised, anything else
        # is returned.
        self.script = list(script or [])
        self.calls: list[int | None] = []

    def _next_scripted(self):
        return self.script.pop(0) if self.script else Reply(answer="ok")

    def generate_structured(self, prompt, schema, system_prompt=None, key_index=None):
        self.calls.append(key_index)
        outcome = self._next_scripted()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def generate_text(self, prompt, system_prompt=None, key_index=None, max_output_tokens=None):
        self.calls.append(key_index)
        outcome = self._next_scripted()
        if isinstance(outcome, Exception):
            raise outcome
        return "ok"


def _call(provider, **kw):
    return pr.generate_with_retry(
        provider=provider, prompt="p", schema=Reply, operation="test", **kw
    )


class TestHappyPath:
    def test_a_successful_call_returns_the_parsed_schema(self):
        result = _call(FakeGemini())

        assert result.answer == "ok"

    def test_requests_spread_across_credentials(self):
        provider = FakeGemini(keys=3)

        for _ in range(6):
            _call(provider)

        # Round-robin, not "ride key #1 until it rate-limits".
        assert len(set(provider.calls)) == 3

    def test_the_daily_counter_increments_and_persists(self, tmp_path):
        _call(FakeGemini())

        assert pr.quota_status()["requests_today"] == 1
        assert (tmp_path / "rpd.json").exists()

    def test_per_credential_accounting_records_the_key_that_served(self):
        provider = FakeGemini(keys=2)

        _call(provider)

        snap = pr.get_registry().snapshot(pr.key_ids_for(provider))
        assert snap["total_requests"] == 1


class TestQuotaRotation:
    def test_a_429_rotates_to_another_credential_and_succeeds(self):
        provider = FakeGemini(keys=2, script=[QuotaExceededError("429 quota")])

        result = _call(provider)

        assert result.answer == "ok"
        # Two attempts: the 429 on the first credential, then a retry.
        assert len(provider.calls) == 2

    def test_a_storm_across_every_credential_raises_rather_than_looping(self):
        provider = FakeGemini(keys=2, script=[QuotaExceededError("429 quota")] * 12)

        with pytest.raises(RuntimeError):
            _call(provider)

        # Bounded: the loop must not keep re-asking exhausted credentials
        # until the process is killed.
        assert len(provider.calls) <= 12

    def test_capacity_exhausted_is_raised_before_any_call_when_all_are_open(self, tmp_path):
        provider = FakeGemini(keys=2)
        registry = pr.get_registry()
        for key_id in pr.key_ids_for(provider):
            for _ in range(BREAKER_FAILURE_THRESHOLD):
                registry.record_failure(key_id, pr.FailureKind.QUOTA, "429")

        with pytest.raises(pr.CapacityExhausted) as exc:
            _call(provider)

        # No provider call at all — the whole point of the breaker.
        assert provider.calls == []
        assert "Retry after" in str(exc.value) or "retry tomorrow" in str(exc.value).lower()


class TestTerminalFailures:
    def test_a_terminal_error_is_raised_immediately(self):
        provider = FakeGemini(keys=3, script=[TerminalProviderError("404 model not found")])

        with pytest.raises(TerminalProviderError):
            _call(provider)

        # One attempt. A retired model must not burn every credential
        # pretending to be exhausted quota.
        assert len(provider.calls) == 1

    def test_a_terminal_error_opens_that_credentials_circuit(self):
        provider = FakeGemini(keys=2, script=[TerminalProviderError("API key not valid")])

        with pytest.raises(TerminalProviderError):
            _call(provider)

        snap = pr.get_registry().snapshot(pr.key_ids_for(provider))
        assert snap["open"] == 1

    def test_a_terminal_error_never_reaches_the_groq_fallback(self, monkeypatch):
        called = []
        monkeypatch.setattr(pr, "_try_groq_fallback", lambda **kw: called.append(1))
        provider = FakeGemini(keys=2, script=[TerminalProviderError("404 model not found")])

        with pytest.raises(TerminalProviderError):
            _call(provider)

        assert called == []


class TestRetryableFailures:
    def test_a_transient_error_is_retried_and_can_succeed(self):
        provider = FakeGemini(keys=1, script=[RetryableError("503 unavailable")])

        assert _call(provider).answer == "ok"
        assert len(provider.calls) == 2

    def test_retries_are_bounded(self):
        provider = FakeGemini(keys=1, script=[RetryableError("503")] * 20)

        with pytest.raises(RuntimeError):
            _call(provider)

        assert len(provider.calls) <= pr.MAX_RETRIES + 1

    def test_backoff_grows_between_attempts(self, monkeypatch):
        waits = []
        monkeypatch.setattr(pr.time, "sleep", lambda s: waits.append(s))
        provider = FakeGemini(keys=1, script=[RetryableError("503")] * 2)

        _call(provider)

        # Exponential, and jittered — so assert on the trend, not on values.
        assert len(waits) >= 2
        assert waits[-1] > waits[0]


class TestSchemaRepair:
    def test_a_truncated_response_is_retried_with_a_shrink_instruction(self):
        from pydantic import ValidationError

        try:
            Reply.model_validate_json("{")
        except ValidationError as exc:
            err = exc

        provider = FakeGemini(keys=1, script=[err])

        # Retrying an identical prompt reproduces an identical truncation, so
        # the retry has to change the request. This is what stops a long
        # dimension degrading into "Insufficient Evidence".
        assert _call(provider).answer == "ok"
        assert len(provider.calls) == 2


class TestDailyBudget:
    def test_an_exhausted_daily_budget_raises_before_calling(self, monkeypatch):
        monkeypatch.setattr(pr, "GEMINI_RPD_LIMIT", 1)
        monkeypatch.setattr(pr, "_daily_gemini_requests", 5)
        provider = FakeGemini()

        with pytest.raises(RuntimeError, match="daily request budget"):
            _call(provider)

        assert provider.calls == []

    def test_quota_status_reports_headroom_honestly(self, monkeypatch):
        monkeypatch.setattr(pr, "GEMINI_RPD_LIMIT", 10)
        monkeypatch.setattr(pr, "_daily_gemini_requests", 10)

        status = pr.quota_status()

        assert status["remaining"] == 0
        assert status["has_headroom"] is False

    def test_remaining_never_goes_negative(self, monkeypatch):
        monkeypatch.setattr(pr, "GEMINI_RPD_LIMIT", 10)
        monkeypatch.setattr(pr, "_daily_gemini_requests", 99)

        # A negative "remaining" rendered on a dashboard reads as a bug in the
        # dashboard rather than an exhausted budget.
        assert pr.quota_status()["remaining"] == 0


class TestKeyIdentity:
    def test_key_ids_never_contain_the_credential(self):
        provider = FakeGemini(keys=2)

        ids = pr.key_ids_for(provider)

        # These strings reach logs, /readyz and /metrics.
        assert all("key-" not in i for i in ids)
        assert len(set(ids)) == 2

    def test_key_ids_cover_every_configured_credential(self):
        assert len(pr.key_ids_for(FakeGemini(keys=5))) == 5


class TestThrottles:
    def test_the_request_throttle_paces_a_full_window(self, monkeypatch):
        slept = []
        monkeypatch.setattr(pr.time, "sleep", lambda s: slept.append(s))
        throttle = pr.RequestThrottle(limit=2, window=60)

        for _ in range(2):
            throttle.wait()
            throttle.record()
        throttle.wait()

        assert slept, "a full window must pace the next request"

    def test_the_token_throttle_sleeps_when_the_window_is_full(self, monkeypatch):
        slept = []
        monkeypatch.setattr(pr.time, "sleep", lambda s: slept.append(s))
        throttle = pr.TokenThrottle(limit=1000, window=60)
        throttle.record(900)

        throttle.wait(estimated_input=500)

        assert slept

    def test_reset_clears_the_window(self):
        throttle = pr.TokenThrottle(limit=100, window=60)
        throttle.record(50)
        throttle.reset()

        assert throttle.total_used == 0


class TestRetryDelayExtraction:
    def test_reads_a_delay_from_prose(self):
        assert pr._extract_retry_delay("please retry in 42s") == 42.0

    def test_returns_none_when_absent(self):
        assert pr._extract_retry_delay("something went wrong") is None


class TestDebugSummary:
    def test_printing_a_summary_never_raises_on_an_empty_run(self, capsys):
        pr._debug_stats["primary_requests"].clear()

        pr.print_debug_summary()

        assert "LLM ANALYSIS SUMMARY" in capsys.readouterr().out

    def test_printing_a_summary_after_a_real_call(self, capsys):
        _call(FakeGemini())

        pr.print_debug_summary()

        assert "Successful" in capsys.readouterr().out
