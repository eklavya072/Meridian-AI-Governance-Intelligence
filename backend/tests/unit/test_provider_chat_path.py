"""generate_text_with_retry — the chat path's own retry ladder.

Chat shares the analysis path's quota discipline but not its patience. The
analysis ladder will wait 120 seconds on a 429 because losing a run costs
more than the wait; on a chat turn someone is watching a spinner, so a reply
that arrives after two minutes is worse than an honest degraded one.
"""

import threading

import pytest

from src import provider_router as pr
from src.key_health import KeyHealthRegistry
from src.llm_provider import QuotaExceededError, RetryableError


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pr, "GEMINI_RPD_FILE", str(tmp_path / "rpd.json"))
    monkeypatch.setattr(pr, "_daily_gemini_requests", 0)
    registry = KeyHealthRegistry(path=tmp_path / "health.json")
    monkeypatch.setattr(pr, "get_registry", lambda: registry)
    yield


class FakeGemini(pr.GeminiProvider):
    def __init__(self, keys=2, script=None):
        self.api_keys = [f"key-{i}" for i in range(keys)]
        self.current_key_index = 0
        self._rotation_lock = threading.Lock()
        self.model_name_str = "fake-flash"
        self.script = list(script or [])
        self.calls = []

    def generate_text(self, prompt, system_prompt=None, key_index=None, max_output_tokens=None):
        self.calls.append({"key_index": key_index, "max_output_tokens": max_output_tokens})
        outcome = self.script.pop(0) if self.script else "a reply"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _chat(provider, **kw):
    return pr.generate_text_with_retry(provider=provider, prompt="question", operation="chat", **kw)


class TestHappyPath:
    def test_a_reply_is_returned(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)

        assert _chat(FakeGemini()) == "a reply"

    def test_the_chat_output_cap_is_applied(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)
        provider = FakeGemini()

        _chat(provider)

        # Chat prompts ask for ~140 words; the analysis path's 8192-token
        # budget is pure latency here.
        assert provider.calls[0]["max_output_tokens"] == pr.CHAT_MAX_OUTPUT_TOKENS

    def test_chat_shares_the_daily_budget_rather_than_bypassing_it(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)

        _chat(FakeGemini())

        # Calling provider.generate_text directly would make chat invisible
        # to the RPD counter that /readyz reports.
        assert pr.quota_status()["requests_today"] == 1

    def test_an_exhausted_daily_budget_refuses_before_calling(self, monkeypatch):
        monkeypatch.setattr(pr, "GEMINI_RPD_LIMIT", 1)
        monkeypatch.setattr(pr, "_daily_gemini_requests", 99)
        provider = FakeGemini()

        with pytest.raises(RuntimeError, match="daily request budget"):
            _chat(provider)

        assert provider.calls == []


class TestDeadline:
    def test_a_turn_past_its_budget_raises_rather_than_hanging(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)
        provider = FakeGemini(keys=1, script=[RetryableError("503")] * 5)

        with pytest.raises((pr.ChatDeadlineExceeded, RuntimeError)):
            _chat(provider, deadline_seconds=0.0001)

    def test_a_sleep_that_leaves_no_room_for_its_retry_is_refused(self, monkeypatch):
        slept = []
        monkeypatch.setattr(pr.time, "sleep", lambda s: slept.append(s))
        provider = FakeGemini(keys=1, script=[RetryableError("503")] * 5)

        with pytest.raises((pr.ChatDeadlineExceeded, RuntimeError)):
            _chat(provider, deadline_seconds=1.0)

        # A sleep that cannot be followed by an attempt is pure delay.
        assert sum(slept) < 10

    def test_the_caller_can_widen_the_budget(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)
        provider = FakeGemini(keys=1, script=[RetryableError("503")])

        assert _chat(provider, deadline_seconds=120) == "a reply"

    def test_no_deadline_means_no_ceiling(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)
        provider = FakeGemini(keys=1, script=[RetryableError("503")])

        assert _chat(provider, deadline_seconds=0) == "a reply"


class TestQuotaOnChat:
    def test_a_429_rotates_and_can_still_answer(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)
        provider = FakeGemini(keys=3, script=[QuotaExceededError("429 quota")])

        assert _chat(provider) == "a reply"
        assert len(provider.calls) == 2

    def test_every_credential_exhausted_raises_a_clear_error(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)
        provider = FakeGemini(keys=2, script=[QuotaExceededError("429 quota")] * 10)

        with pytest.raises((RuntimeError, pr.ChatDeadlineExceeded)) as exc:
            _chat(provider)

        # The caller degrades to its template reply; a silent hang or a bare
        # failure is what this replaces.
        assert str(exc.value)


class TestRetryBudget:
    def test_a_transient_failure_is_retried(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)
        provider = FakeGemini(keys=1, script=[RetryableError("503")])

        assert _chat(provider) == "a reply"

    def test_attempts_are_bounded(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)
        provider = FakeGemini(keys=1, script=[RetryableError("503")] * 20)

        with pytest.raises((RuntimeError, pr.ChatDeadlineExceeded)):
            _chat(provider)

        assert len(provider.calls) <= 10

    def test_max_attempts_can_be_overridden(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)
        provider = FakeGemini(keys=1, script=[RetryableError("503")] * 20)

        with pytest.raises((RuntimeError, pr.ChatDeadlineExceeded)):
            _chat(provider, max_attempts=2)

        assert len(provider.calls) <= 2


class TestResetProvider:
    def test_reset_clears_the_cached_provider_and_counters(self, monkeypatch):
        monkeypatch.setattr(pr.time, "sleep", lambda *_: None)
        _chat(FakeGemini())
        assert pr.quota_status()["requests_today"] == 1

        pr.reset_provider()

        # An explicit dev/test reset must start from a known-zero state,
        # including the persisted file.
        assert pr.quota_status()["requests_today"] == 0
