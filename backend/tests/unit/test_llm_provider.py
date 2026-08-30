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
    GeminiProvider,
    GroqProvider,
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
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
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

    def test_rotate_key_reports_exhaustion_at_the_last_credential(self, monkeypatch):
        provider = self._provider(monkeypatch, n=2)
        provider.current_key_index = 1

        assert provider.rotate_key() is False

    def test_rotate_key_advances_when_another_remains(self, monkeypatch):
        provider = self._provider(monkeypatch, n=3)
        provider.current_key_index = 0

        assert provider.rotate_key() is True
        assert provider.current_key_index == 1

    def test_keys_remaining_counts_down(self, monkeypatch):
        provider = self._provider(monkeypatch, n=3)
        provider.current_key_index = 0

        assert provider.keys_remaining == 2

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
            def __init__(self, api_key=None):
                calls["api_key"] = api_key
                self.models = _Models()

        genai = types.ModuleType("google.genai")
        genai.Client = _Client
        genai_types = types.ModuleType("google.genai.types")
        genai_types.ThinkingConfig = lambda **kw: kw
        genai_types.GenerateContentConfig = lambda **kw: kw
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


class TestGroqProvider:
    def test_no_key_fails_loudly(self):
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            GroqProvider()

    def test_the_model_default_is_a_live_one(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "g")

        # llama-3.3-70b was retired from Groq's catalog, and every quota
        # exhaustion silently fell through to a dead fallback.
        assert "llama-3.3-70b" not in GroqProvider().model_name

    def test_the_model_can_be_overridden(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "g")
        monkeypatch.setenv("GROQ_MODEL", "custom/model")

        assert GroqProvider().model_name == "custom/model"
