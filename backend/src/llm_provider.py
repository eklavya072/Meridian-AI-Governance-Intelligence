from __future__ import annotations

import os
import threading
import time
import json
import structlog
from abc import ABC, abstractmethod
from typing import Any, TypeVar, Type

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


T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    @abstractmethod
    def generate_structured(
        self, prompt: str, schema: Type[T], system_prompt: str | None = None
    ) -> T: ...

    @abstractmethod
    def generate_text(
        self, prompt: str, system_prompt: str | None = None
    ) -> str: ...

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
            print(f"[DEBUG] GeminiProvider initialized with {key_count} API keys (auto-rotation enabled)")
        else:
            print(f"[DEBUG] GeminiProvider initialized with 1 API key")

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
        self, prompt: str, system_prompt: str | None = None, schema: type[T] | None = None,
        key_index: int | None = None, max_output_tokens: int | None = None,
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
            "thinking_config": types.ThinkingConfig(
                thinking_level=GEMINI_THINKING_LEVEL
            ),
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
        self, prompt: str, schema: type[T], system_prompt: str | None = None,
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
            error_str = str(exc)
            if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                raise QuotaExceededError(str(exc)) from exc
            if "500" in error_str or "503" in error_str or "timeout" in error_str.lower():
                raise RetryableError(str(exc)) from exc
            if "404" in error_str or "not found" in error_str.lower() or "is no longer available" in error_str:
                raise QuotaExceededError(f"Model unavailable: {exc}") from exc
            raise

    def generate_text(
        self, prompt: str, system_prompt: str | None = None,
        key_index: int | None = None, max_output_tokens: int | None = None,
    ) -> str:
        try:
            text, _ = self._call_gemini(
                prompt=prompt, system_prompt=system_prompt, key_index=key_index,
                max_output_tokens=max_output_tokens,
            )
            return text
        except Exception as exc:
            error_str = str(exc)
            if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                raise QuotaExceededError(str(exc)) from exc
            if "500" in error_str or "503" in error_str or "timeout" in error_str.lower():
                raise RetryableError(str(exc)) from exc
            if "404" in error_str or "not found" in error_str.lower() or "is no longer available" in error_str:
                raise QuotaExceededError(f"Model unavailable: {exc}") from exc
            raise


class CerebrasProvider(LLMProvider):
    def __init__(self) -> None:
        api_key = os.getenv("CEREBRAS_API_KEY")
        if not api_key:
            raise ValueError(
                "CEREBRAS_API_KEY not set. Get one free at https://cloud.cerebras.ai"
            )
        self.api_key = api_key
        self.model_name_str = os.getenv("CEREBRAS_MODEL", "llama3.1-70b")

    @property
    def tier(self) -> str:
        return "primary"

    @property
    def model_name(self) -> str:
        return self.model_name_str

    def _call_cerebras(
        self, prompt: str, system_prompt: str | None = None, temperature: float = 0.1
    ) -> tuple[str, dict]:
        from openai import OpenAI

        client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.cerebras.ai/v1",
        )
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = client.chat.completions.create(
                model=self.model_name_str,
                messages=messages,
                temperature=temperature,
                max_tokens=4096,
            )
            text = response.choices[0].message.content or ""
            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            return text, usage
        except Exception as exc:
            error_str = str(exc).lower()
            if any(k in error_str for k in ("402", "429", "quota", "rate", "payment required", "model not found", "model does not exist", "not found", "404")):
                raise QuotaExceededError(str(exc)) from exc
            if any(k in error_str for k in ("500", "502", "503")):
                raise RetryableError(str(exc)) from exc
            raise

    def generate_structured(
        self, prompt: str, schema: type[T], system_prompt: str | None = None
    ) -> T:
        import re
        raw, usage = self._call_cerebras(prompt=prompt, system_prompt=system_prompt, temperature=0.1)
        cleaned = re.sub(r"^```(?:json)?\s*|```\s*$", "", raw.strip(), flags=re.MULTILINE)
        try:
            import json
            parsed = json.loads(cleaned)
            obj = schema(**parsed)
            obj._raw_json = cleaned
            obj._token_usage = usage
            return obj
        except Exception as exc:
            logger.error("cerebras_structured_parse_failed", error=str(exc), raw_preview=raw[:200], cleaned_preview=cleaned[:200])
            raise

    def generate_text(
        self, prompt: str, system_prompt: str | None = None
    ) -> str:
        raw, _usage = self._call_cerebras(prompt=prompt, system_prompt=system_prompt, temperature=0.3)
        return raw


class GroqProvider(LLMProvider):
    def __init__(self) -> None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY not set. Get one free at https://console.groq.com"
            )
        self.api_key = api_key
        # "llama-3.3-70b-versatile" was retired from Groq's catalog (confirmed
        # live 404 "model_not_found" from a real analysis run, and absent
        # from GET /openai/v1/models for this account) — every Gemini-quota
        # exhaustion silently fell through to a dead fallback, so a
        # quota-exhausted analysis returned "Insufficient Evidence" instead
        # of a real Groq answer. "openai/gpt-oss-120b" is confirmed live
        # against this account: general-purpose, JSON-mode capable (the
        # structured-output path this pipeline needs), 120B open-weight
        # model. It is a reasoning model — thinking tokens count against
        # max_tokens, so keep the existing 8192 cap generous (already true
        # in _call_groq below).
        self.model_name_str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    @property
    def tier(self) -> str:
        return "primary"

    @property
    def model_name(self) -> str:
        return self.model_name_str

    def _call_groq(
        self, prompt: str, system_prompt: str | None = None, temperature: float = 0.1, json_mode: bool = False,
    ) -> tuple[str, dict]:
        from openai import OpenAI

        client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            kwargs: dict[str, Any] = {
                "model": self.model_name_str,
                "messages": messages,
                "temperature": temperature,
                # 8192: matches the Gemini cap — the combined Module 1+2
                # output exceeds 4096 tokens when citations are numerous.
                "max_tokens": 8192,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content or ""
            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
                input_tps = response.usage.prompt_tokens
                output_tps = response.usage.completion_tokens
                total_tps = response.usage.total_tokens
                logger.info(
                    "groq_token_usage",
                    model=self.model_name_str,
                    prompt_tokens=input_tps,
                    completion_tokens=output_tps,
                    total_tokens=total_tps,
                )
            return text, usage
        except Exception as exc:
            error_str = str(exc)
            if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                raise QuotaExceededError(str(exc)) from exc
            if "500" in error_str or "502" in error_str or "503" in error_str:
                raise RetryableError(str(exc)) from exc
            raise

    def generate_structured(
        self, prompt: str, schema: type[T], system_prompt: str | None = None
    ) -> T:
        import re
        raw, usage = self._call_groq(prompt=prompt, system_prompt=system_prompt, temperature=0.1, json_mode=True)
        cleaned = re.sub(r"^```(?:json)?\s*|```\s*$", "", raw.strip(), flags=re.MULTILINE)
        try:
            import json
            parsed = json.loads(cleaned)
            obj = schema(**parsed)
            obj._raw_json = cleaned
            obj._token_usage = usage
            return obj
        except Exception as exc:
            logger.error("groq_structured_parse_failed", error=str(exc), raw_preview=raw[:200], cleaned_preview=cleaned[:200])
            raise

    def generate_text(
        self, prompt: str, system_prompt: str | None = None
    ) -> str:
        raw, _usage = self._call_groq(prompt=prompt, system_prompt=system_prompt, temperature=0.3)
        return raw
