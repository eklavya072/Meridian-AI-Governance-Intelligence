from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

# Gemini 3 "thinking" level for every structured-extraction call this
# pipeline makes. "low" (not "minimal") — see the call site in
# GeminiProvider._call_gemini for why. Env-tunable per model/deployment.
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "low")


class QuotaExceededError(Exception):
    pass


class RetryableError(Exception):
    pass


class TerminalProviderError(Exception):
    """Retrying cannot help: bad credential, retired model, malformed request.

    Previously these were raised as QuotaExceededError, so the router rotated
    through every configured credential and then reported exhausted quota for
    what was actually a one-line configuration fix.
    """


def _as_provider_error(exc: Exception) -> Exception:
    """Map a provider exception onto the router's three outcomes."""
    from src.provider_errors import FailureKind, classify

    failure = classify(exc)
    if failure.kind in (FailureKind.QUOTA, FailureKind.QUOTA_DAILY):
        # Both reach the router's 429 branch; it re-classifies to tell a
        # credential that recovers in seconds from one that is done for the day.
        return QuotaExceededError(str(exc))
    if failure.kind is FailureKind.TERMINAL:
        return TerminalProviderError(f"{failure.reason}: {exc}")
    return RetryableError(str(exc))


T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    @abstractmethod
    def generate_structured(
        self, prompt: str, schema: type[T], system_prompt: str | None = None
    ) -> T: ...

    @abstractmethod
    def generate_text(self, prompt: str, system_prompt: str | None = None) -> str: ...

    @property
    @abstractmethod
    def tier(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...


class GeminiProvider(LLMProvider):
    def __init__(self) -> None:
        # Collect all available Gemini API keys for automatic rotation on quota exhaustion
        self.api_keys: list[str] = []
        primary_key = os.getenv("GEMINI_API_KEY")
        if primary_key:
            self.api_keys.append(primary_key)
        # Additional keys from GEMINI_API_KEY_2, GEMINI_API_KEY_3, ...
        for i in range(2, 10):
            key = os.getenv(f"GEMINI_API_KEY_{i}")
            if key:
                self.api_keys.append(key)

        if not self.api_keys:
            raise ValueError(
                "GEMINI_API_KEY not set. Set it in .env to use the Gemini provider, "
                "or add GEMINI_API_KEY_2, GEMINI_API_KEY_3 etc. for key rotation."
            )

        self.current_key_index = 0
        # Guards key rotation: the parallel analysis loop runs dimension LLM
        # calls concurrently, so two threads hitting 429 must not race the
        # index forward past a usable key.
        self._rotation_lock = threading.Lock()
        self.model_name_str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

        key_count = len(self.api_keys)
        if key_count > 1:
            print(
                f"[DEBUG] GeminiProvider initialized with {key_count} API keys (auto-rotation enabled)"
            )
        else:
            print("[DEBUG] GeminiProvider initialized with 1 API key")

    @property
    def api_key(self) -> str:
        with self._rotation_lock:
            return self.api_keys[self.current_key_index]

    @property
    def tier(self) -> str:
        return "primary"

    @property
    def model_name(self) -> str:
        return self.model_name_str

    def rotate_key(self) -> bool:
        """Rotate to the next Gemini API key. Returns True if another key is available, False if all exhausted."""
        with self._rotation_lock:
            if self.current_key_index < len(self.api_keys) - 1:
                self.current_key_index += 1
                print(
                    f"[DEBUG] Rotating Gemini API key #{self.current_key_index + 1}/{len(self.api_keys)}"
                )
                return True
            print(f"[DEBUG] All {len(self.api_keys)} Gemini API keys exhausted")
            return False

    def next_key(self) -> int:
        """Round-robin to the next key for the NEXT request.

        Unlike `rotate_key` (which only advances on a 429), this advances on
        every call, so the concurrent analysis workers spread across ALL
        configured keys instead of riding key #1 until it rate-limits. The
        returned index is the key the next generate_* call must use — the
        caller passes it through to `generate_structured` / `generate_text`
        so the throttle for that key and the call itself can never race (the
        global `current_key_index` alone is not safe under concurrency: two
        workers could both read it and hit the same key).
        """
        with self._rotation_lock:
            self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
            return self.current_key_index

    @property
    def keys_remaining(self) -> int:
        return len(self.api_keys) - self.current_key_index - 1

    def _call_gemini(
        self,
        prompt: str,
        system_prompt: str | None = None,
        schema: type[T] | None = None,
        key_index: int | None = None,
        max_output_tokens: int | None = None,
    ) -> tuple[str, Any | None]:
        """Make a single Gemini API call with the current (or explicitly
        selected) key. `key_index` is set by provider_router's per-key
        throttle path so the request uses EXACTLY the key its throttle
        reserved — the shared `current_key_index` is not safe to read here
        under concurrency. `max_output_tokens` overrides the default 8192
        (used by the chat path, whose replies are deliberately short)."""
        import google.genai as genai
        from google.genai import types

        key = self.api_keys[key_index] if key_index is not None else self.api_key
        client = genai.Client(api_key=key)

        config_kwargs: dict = {
            "temperature": 0.1,
            # 8192: the combined Module 1+2 JSON (with citations) routinely
            # exceeds 4096 tokens — truncation produced invalid JSON that
            # failed schema validation and turned real dimensions into
            # "Insufficient Evidence" gaps.
            "max_output_tokens": max_output_tokens or 8192,
            # Gemini 3 models think-by-default (thinking_level="medium"),
            # which is real wall-clock latency spent on an internal
            # reasoning pass BEFORE the visible output starts generating —
            # the single largest lever on total analysis time, and doesn't
            # touch the visible answer's content. This pipeline's calls are
            # structured extraction against an already highly-prescriptive
            # prompt (read these labeled context chunks, fill this exact
            # JSON schema) — not open-ended multi-step reasoning — so "low"
            # (still a real reasoning pass, per Google's own docs, just a
            # lighter one) is the safe cut: faster without the quality risk
            # of "minimal", which skips the pass that catches nuance.
            # Env-tunable if a future model needs recalibrating.
            "thinking_config": types.ThinkingConfig(thinking_level=GEMINI_THINKING_LEVEL),
        }
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt
        if schema:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = schema

        response = client.models.generate_content(
            model=self.model_name_str,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        text = response.candidates[0].content.parts[0].text
        return text, None

    def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
        key_index: int | None = None,
    ) -> T:
        try:
            text, _ = self._call_gemini(
                prompt=prompt, system_prompt=system_prompt, schema=schema, key_index=key_index
            )
            result = schema.model_validate_json(text)
            result._raw_json = text
            return result
        except Exception as exc:
            raise _as_provider_error(exc) from exc

    def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        key_index: int | None = None,
        max_output_tokens: int | None = None,
    ) -> str:
        try:
            text, _ = self._call_gemini(
                prompt=prompt,
                system_prompt=system_prompt,
                key_index=key_index,
                max_output_tokens=max_output_tokens,
            )
            return text
        except Exception as exc:
            raise _as_provider_error(exc) from exc
