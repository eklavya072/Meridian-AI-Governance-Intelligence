"""Provider construction and error mapping, with the SDKs faked.

The classifier lives in provider_errors and is tested there. What matters
here is that each provider class wires its own exceptions into the router's
three outcomes, and that credential discovery does not quietly configure
something the operator did not intend.
"""

import sys
import types

import pytest
from pydantic import BaseModel

from src.llm_provider import (
    GEMINI_BATCH_REQUEST_TIMEOUT_SECONDS,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    GEMINI_SEED,
    GeminiProvider,
    QuotaExceededError,
    RetryableError,
    TerminalProviderError,
    _as_provider_error,
)


class Reply(BaseModel):
    answer: str


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for i in range(2, 10):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    yield


class TestCredentialDiscovery:
    def test_a_single_key_is_found(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "primary")

        assert GeminiProvider().api_keys == ["primary"]

    def test_numbered_keys_are_collected_in_order(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "one")
        monkeypatch.setenv("GEMINI_API_KEY_2", "two")
        monkeypatch.setenv("GEMINI_API_KEY_3", "three")

        assert GeminiProvider().api_keys == ["one", "two", "three"]

    def test_a_gap_in_the_numbering_stops_nothing_silently(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "one")
        monkeypatch.setenv("GEMINI_API_KEY_3", "three")

        # KEY_2 is absent. Whatever the scan does, it must not invent a
        # credential or drop one it did find.
        keys = GeminiProvider().api_keys
        assert "one" in keys and "three" in keys

    def test_no_key_at_all_fails_loudly_at_construction(self):
        # Constructing a provider with no credential and discovering it on
        # the first analysis would waste a run.
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            GeminiProvider()

    def test_the_model_name_comes_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-9.9-imaginary")

        assert GeminiProvider().model_name == "gemini-9.9-imaginary"

    def test_the_tier_is_primary(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")

        assert GeminiProvider().tier == "primary"


class TestKeyRotation:
    def _provider(self, monkeypatch, n=3):
        monkeypatch.setenv("GEMINI_API_KEY", "one")
        for i in range(2, n + 1):
            monkeypatch.setenv(f"GEMINI_API_KEY_{i}", f"key{i}")
        return GeminiProvider()

    def test_next_key_cycles_through_every_credential(self, monkeypatch):
        provider = self._provider(monkeypatch, n=3)

        seen = {provider.next_key() for _ in range(9)}

        assert seen == {0, 1, 2}

    def test_next_key_wraps_rather_than_running_off_the_end(self, monkeypatch):
        provider = self._provider(monkeypatch, n=2)

        indices = [provider.next_key() for _ in range(5)]

        assert all(0 <= i < 2 for i in indices)

    def test_the_api_key_property_returns_the_current_credential(self, monkeypatch):
        provider = self._provider(monkeypatch, n=2)
        provider.current_key_index = 1

        assert provider.api_key == "key2"


class TestErrorMapping:
    @pytest.mark.parametrize(
        "message,expected",
        [
            ("429 RESOURCE_EXHAUSTED", QuotaExceededError),
            ("quota exceeded for this project", QuotaExceededError),
            ("503 Service Unavailable", RetryableError),
            ("deadline exceeded", RetryableError),
            ("404 model not found", TerminalProviderError),
            ("API key not valid", TerminalProviderError),
            ("400 invalid argument", TerminalProviderError),
        ],
    )
    def test_provider_exceptions_map_to_the_routers_three_outcomes(self, message, expected):
        assert isinstance(_as_provider_error(Exception(message)), expected)

    def test_an_unrecognised_error_is_retryable_not_terminal(self):
        # Losing a run to one unclassified blip is worse than one extra retry.
        assert isinstance(_as_provider_error(Exception("weird")), RetryableError)


class TestGeminiCalls:
    @pytest.fixture
    def fake_genai(self, monkeypatch):
        """A stand-in for google.genai that records what it was asked."""
        calls = {}

        class _Models:
            def generate_content(self, model, contents, config):
                calls["model"] = model
                calls["contents"] = contents
                calls["config"] = config
                part = types.SimpleNamespace(text='{"answer": "ok"}')
                content = types.SimpleNamespace(parts=[part])
                return types.SimpleNamespace(candidates=[types.SimpleNamespace(content=content)])

        class _Client:
            def __init__(self, api_key=None, http_options=None):
                calls["api_key"] = api_key
                calls["http_options"] = http_options
                self.models = _Models()

        genai = types.ModuleType("google.genai")
        genai.Client = _Client
        genai_types = types.ModuleType("google.genai.types")
        genai_types.ThinkingConfig = lambda **kw: kw
        genai_types.GenerateContentConfig = lambda **kw: kw
        genai_types.HttpOptions = lambda **kw: kw
        genai.types = genai_types

        google = types.ModuleType("google")
        monkeypatch.setitem(sys.modules, "google", google)
        monkeypatch.setitem(sys.modules, "google.genai", genai)
        monkeypatch.setitem(sys.modules, "google.genai.types", genai_types)
        return calls

    def test_a_structured_call_parses_into_the_schema(self, monkeypatch, fake_genai):
        monkeypatch.setenv("GEMINI_API_KEY", "k1")

        result = GeminiProvider().generate_structured("prompt", Reply)

        assert result.answer == "ok"

    def test_the_explicit_key_index_selects_the_credential(self, monkeypatch, fake_genai):
        monkeypatch.setenv("GEMINI_API_KEY", "k1")
        monkeypatch.setenv("GEMINI_API_KEY_2", "k2")

        GeminiProvider().generate_structured("prompt", Reply, key_index=1)

        # The throttle reserves a slot on ONE key and passes its index in;
        # reading the shared current_key_index here would race under
        # concurrency and use a different credential than was reserved.
        assert fake_genai["api_key"] == "k2"

    def test_every_call_carries_a_request_timeout(self, monkeypatch, fake_genai):
        """The SDK sets none, and a call with no ceiling cannot be retried.

        A brief loss of connectivity held one request for 781 seconds before
        "[Errno 65] No route to host" surfaced; the dimension behind it waited
        the whole time and the retry ladder never got a turn. The timeout is
        what turns that into an ordinary retryable failure.
        """
        monkeypatch.setenv("GEMINI_API_KEY", "k1")

        GeminiProvider().generate_text("prompt")

        # The SDK takes milliseconds.
        assert fake_genai["http_options"]["timeout"] == int(GEMINI_REQUEST_TIMEOUT_SECONDS * 1000)

    def test_a_batched_call_gets_the_longer_ceiling(self, monkeypatch, fake_genai):
        """Eight dimensions in one reply take far longer than 180s allows.

        Cutting one off would waste the model's work and still spend the
        request from the day's quota.
        """
        monkeypatch.setenv("GEMINI_API_KEY", "k1")

        GeminiProvider().generate_structured("prompt", Reply, max_output_tokens=65536)

        assert fake_genai["http_options"]["timeout"] == int(
            GEMINI_BATCH_REQUEST_TIMEOUT_SECONDS * 1000
        )
        assert fake_genai["config"]["max_output_tokens"] == 65536

    def test_every_call_pins_the_sampling_seed(self, monkeypatch, fake_genai):
        """Same prompt, same text — the part temperature alone does not buy.

        Measured on this workload: three identical prompts at temperature 0.1
        with no seed returned three different answers, the closest pair 31%
        similar; with the seed set they came back byte-identical. The verdict
        never depended on the model, but the brief a reader sees did, and a
        re-run that rewords itself looks like a tool changing its mind.
        """
        monkeypatch.setenv("GEMINI_API_KEY", "k1")

        GeminiProvider().generate_text("prompt")

        assert fake_genai["config"]["seed"] == GEMINI_SEED

    def test_a_text_call_returns_the_raw_text(self, monkeypatch, fake_genai):
        monkeypatch.setenv("GEMINI_API_KEY", "k1")

        assert GeminiProvider().generate_text("prompt") == '{"answer": "ok"}'

    def test_the_chat_path_can_lower_the_output_cap(self, monkeypatch, fake_genai):
        monkeypatch.setenv("GEMINI_API_KEY", "k1")

        GeminiProvider().generate_text("prompt", max_output_tokens=1024)

        # Chat replies are ~140 words; the analysis path's 8192-token budget
        # is pure latency on a turn someone is watching.
        assert fake_genai["config"]["max_output_tokens"] == 1024

    def test_the_default_output_cap_is_generous_for_analysis(self, monkeypatch, fake_genai):
        monkeypatch.setenv("GEMINI_API_KEY", "k1")

        GeminiProvider().generate_structured("prompt", Reply)

        # The combined Module 1+2 JSON routinely exceeds 4096 tokens, and
        # truncation turned real dimensions into "Insufficient Evidence".
        assert fake_genai["config"]["max_output_tokens"] == 8192


class TestMalformedReplies:
    """A reply that does not fit the schema is the model's answer, not a provider fault.

    It used to be pushed through the provider-error classifier, which matches
    substrings of the error text — and pydantic's error text echoes the start of
    the reply. A truncated Safety answer therefore matched the terminal marker
    "safety", failed with no retry and benched a healthy credential, while every
    other dimension was re-sent verbatim. The router's shrink-and-retry repair
    never ran for Gemini at all.
    """

    TRUNCATED_SAFETY = '{"dimension": "Safety", "coverage": "Partial", "reason_flagged": "The doc'

    def test_a_truncated_reply_surfaces_as_a_validation_error(self, monkeypatch):
        from pydantic import ValidationError

        monkeypatch.setenv("GEMINI_API_KEY", "k1")
        provider = GeminiProvider()
        monkeypatch.setattr(provider, "_call_gemini", lambda **kw: (self.TRUNCATED_SAFETY, None))

        with pytest.raises(ValidationError):
            provider.generate_structured("prompt", Reply)

    def test_the_router_repairs_it_instead_of_benching_the_key(self, monkeypatch):
        from src import provider_router as pr
        from src.key_health import KeyHealthRegistry

        monkeypatch.setenv("GEMINI_API_KEY", "k1")
        provider = GeminiProvider()
        prompts: list[str] = []

        def fake_call(prompt, **kw):
            prompts.append(prompt)
            text = self.TRUNCATED_SAFETY if len(prompts) == 1 else '{"answer": "ok"}'
            return text, None

        monkeypatch.setattr(provider, "_call_gemini", fake_call)
        registry = KeyHealthRegistry(path=pr.Path(pr.GEMINI_RPD_FILE).with_name("kh.json"))
        monkeypatch.setattr(pr, "get_registry", lambda: registry)
        monkeypatch.setattr(pr, "_persist_daily_requests", lambda count: None)

        result = pr.generate_with_retry(provider, "prompt", Reply, operation="module1_2_safety")

        assert result.answer == "ok"
        assert len(prompts) == 2
        assert "KEEPING IT SHORT AND VALID" in prompts[1]
        assert registry.snapshot()["open"] == 0

    def test_a_blocked_reply_is_terminal_and_an_empty_one_retryable(self):
        from src.llm_provider import _response_text

        blocked = types.SimpleNamespace(
            candidates=[
                types.SimpleNamespace(
                    finish_reason=types.SimpleNamespace(name="SAFETY"),
                    content=types.SimpleNamespace(parts=[]),
                )
            ]
        )
        empty = types.SimpleNamespace(candidates=[])
        with pytest.raises(TerminalProviderError):
            _response_text(blocked)
        with pytest.raises(RetryableError):
            _response_text(empty)

    def test_multi_part_replies_are_joined(self):
        from src.llm_provider import _response_text

        parts = [types.SimpleNamespace(text='{"answer": '), types.SimpleNamespace(text='"ok"}')]
        reply = types.SimpleNamespace(
            candidates=[types.SimpleNamespace(content=types.SimpleNamespace(parts=parts))]
        )
        assert _response_text(reply) == '{"answer": "ok"}'


class TestOverloadFallback:
    """An overloaded model hands the request on; nothing else does."""

    @pytest.fixture
    def genai_with(self, monkeypatch):
        """A fake SDK whose answer depends on the model asked."""

        def install(behaviour):
            asked = []

            class _Models:
                def generate_content(self, model, contents, config):
                    asked.append(model)
                    outcome = behaviour.get(model, "ok")
                    if outcome != "ok":
                        raise Exception(outcome)
                    part = types.SimpleNamespace(text='{"answer": "ok"}')
                    content = types.SimpleNamespace(parts=[part])
                    return types.SimpleNamespace(
                        candidates=[types.SimpleNamespace(content=content)]
                    )

            class _Client:
                def __init__(self, api_key=None, http_options=None):
                    self.models = _Models()

            genai = types.ModuleType("google.genai")
            genai.Client = _Client
            genai_types = types.ModuleType("google.genai.types")
            genai_types.ThinkingConfig = lambda **kw: kw
            genai_types.GenerateContentConfig = lambda **kw: kw
            genai_types.HttpOptions = lambda **kw: kw
            genai.types = genai_types
            monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
            monkeypatch.setitem(sys.modules, "google.genai", genai)
            monkeypatch.setitem(sys.modules, "google.genai.types", genai_types)
            monkeypatch.setenv("GEMINI_API_KEY", "k1")
            monkeypatch.setenv("GEMINI_MODEL", "primary-model")
            monkeypatch.setattr(
                "src.llm_provider.GEMINI_FALLBACK_MODELS", ["second-model", "third-model"]
            )
            return asked

        return install

    OVERLOADED = "503 UNAVAILABLE. This model is currently experiencing high demand."

    def test_an_overloaded_model_hands_the_request_to_the_next(self, genai_with):
        asked = genai_with({"primary-model": self.OVERLOADED})

        assert GeminiProvider().generate_structured("prompt", Reply).answer == "ok"
        assert asked == ["primary-model", "second-model"]

    def test_the_run_records_which_model_answered(self, genai_with):
        from collections import Counter

        from src.llm_provider import MODELS_SERVED

        genai_with({"primary-model": self.OVERLOADED})
        served = Counter()
        token = MODELS_SERVED.set(served)
        try:
            GeminiProvider().generate_text("prompt")
            GeminiProvider().generate_text("prompt")
        finally:
            MODELS_SERVED.reset(token)

        assert served == Counter({"second-model": 2})

    def test_a_quota_refusal_is_not_handed_on(self, genai_with):
        # A 429 belongs to the router's per-key circuit breaker; moving it to
        # another model would hide a spent credential.
        asked = genai_with({"primary-model": "429 RESOURCE_EXHAUSTED quota"})

        with pytest.raises(QuotaExceededError):
            GeminiProvider().generate_text("prompt")
        assert asked == ["primary-model"]

    def test_every_model_overloaded_is_still_an_error(self, genai_with):
        asked = genai_with(
            dict.fromkeys(("primary-model", "second-model", "third-model"), self.OVERLOADED)
        )

        with pytest.raises(RetryableError):
            GeminiProvider().generate_text("prompt")
        assert asked == ["primary-model", "second-model", "third-model"]
