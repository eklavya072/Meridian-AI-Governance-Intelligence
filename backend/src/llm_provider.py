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

#: Per-request ceiling, in seconds. The SDK sets no timeout of its own, so a
#: request that stalls below the HTTP layer blocks its thread until the OS
#: gives up. One brief loss of connectivity held a single call for 781
#: seconds — "[Errno 65] No route to host", surfaced thirteen minutes after
#: the fact — and the dimension behind it waited the whole time. Retries
#: cannot help a call that never returns.
#:
#: Observed latency on this workload is 8-40s at thinking_level=low, so this
#: is ~4x the slowest real call: long enough never to cut one short, short
#: enough that a stall becomes an ordinary retryable failure the existing
#: ladder already knows how to handle.
GEMINI_REQUEST_TIMEOUT_SECONDS = float(os.getenv("GEMINI_REQUEST_TIMEOUT", "180"))

#: The same ceiling for a batched request (gap_analyzer.BATCH_LLM_CALLS),
#: which writes up to eight dimensions' answers in one reply and so runs up
#: to eight times as long as a single call. At 180s a slow batch would be
#: cut off after the model had done the work, and the request would still
#: count against the day's quota. Only the batched path asks for more than
#: the default output budget, so that is what selects it.
GEMINI_BATCH_REQUEST_TIMEOUT_SECONDS = float(os.getenv("GEMINI_BATCH_REQUEST_TIMEOUT", "600"))

#: Output budget of one call unless the caller sets another.
DEFAULT_MAX_OUTPUT_TOKENS = 8192

#: Fixed sampling seed, so the same prompt returns the same text.
#:
#: temperature=0.1 alone does not do this. The model still samples, and the
#: floating-point reduction order inside the inference kernels varies with
#: whatever batch the request lands in — which depends on other traffic on a
#: shared endpoint, not on anything we control. Measured on this workload:
#: three identical prompts at temperature 0.1 returned three different
#: answers, the closest pair only 31% similar. With a seed set, the same
#: three calls came back byte-identical.
#:
#: This matters beyond tidiness. The verdict is computed from the document
#: and never from the model (see gap_analyzer._compute_deterministic_verdict),
#: so scores were already reproducible — but the NARRATIVE a ministry reads
#: was not. Re-running the same document produced a differently worded brief,
#: which reads like the tool changed its mind when nothing had changed.
#:
#: Google documents this as best effort, not a guarantee, so it is a large
#: reduction in variance rather than a promise of none. Nothing downstream
#: depends on it holding.
GEMINI_SEED = int(os.getenv("GEMINI_SEED", "20260919"))


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


#: Finish reasons that mean the provider refused the content itself. Resending
#: the same prompt cannot change the answer.
_BLOCKED_FINISH_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}


def _response_text(response: Any) -> str:
    """The reply's text, or a classified error when there is none.

    Reading `candidates[0].content.parts[0].text` assumed exactly one part and
    raised a bare IndexError/AttributeError when the reply was blocked or
    empty — which the router could only log as "unclassified". Every text part
    is joined, and an empty reply says why it was empty.
    """
    candidates = getattr(response, "candidates", None) or []
    parts = []
    finish = ""
    if candidates:
        candidate = candidates[0]
        reason = getattr(candidate, "finish_reason", None)
        finish = str(getattr(reason, "name", reason or ""))
        content = getattr(candidate, "content", None)
        parts = [
            p.text
            for p in (getattr(content, "parts", None) or [])
            if getattr(p, "text", None) and not getattr(p, "thought", False)
        ]
    text = "".join(parts)
    if text:
        return text
    feedback = getattr(response, "prompt_feedback", None)
    block = getattr(getattr(feedback, "block_reason", None), "name", "") or ""
    if block or finish.upper() in _BLOCKED_FINISH_REASONS:
        raise TerminalProviderError(f"reply blocked by the provider ({block or finish})")
    raise RetryableError(f"empty reply from the provider (finish_reason={finish or 'none'})")


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
        # Flash-Lite, deliberately. On the free tier every full Flash model
        # allows 20 requests a day per project and 5 a minute; an analysis is
        # about ten, so a demo is spent after two runs. Flash-Lite allows 500
        # and 15, and on 28 Sep it was the model still answering while every
        # full Flash model returned 503 "high demand" for hours.
        self.model_name_str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

        logger.info("gemini_provider_ready", keys=len(self.api_keys), model=self.model_name_str)

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

    def next_key(self) -> int:
        """Round-robin to the next key for the NEXT request.

        Advances on every call, so the concurrent analysis workers spread across ALL
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
        budget = max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS
        timeout = (
            GEMINI_BATCH_REQUEST_TIMEOUT_SECONDS
            if budget > DEFAULT_MAX_OUTPUT_TOKENS
            else GEMINI_REQUEST_TIMEOUT_SECONDS
        )
        client = genai.Client(
            api_key=key,
            # The SDK takes milliseconds.
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )

        config_kwargs: dict = {
            "temperature": 0.1,
            "seed": GEMINI_SEED,
            # 8192: the combined Module 1+2 JSON (with citations) routinely
            # exceeds 4096 tokens — truncation produced invalid JSON that
            # failed schema validation and turned real dimensions into
            # "Insufficient Evidence" gaps.
            "max_output_tokens": budget,
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
        return _response_text(response), None

    def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
        key_index: int | None = None,
        max_output_tokens: int | None = None,
    ) -> T:
        try:
            text, _ = self._call_gemini(
                prompt=prompt,
                system_prompt=system_prompt,
                schema=schema,
                key_index=key_index,
                max_output_tokens=max_output_tokens,
            )
        except (QuotaExceededError, RetryableError, TerminalProviderError):
            raise
        except Exception as exc:
            raise _as_provider_error(exc) from exc
        # Validated OUTSIDE the provider-error translation, deliberately. A reply
        # that does not fit the schema is the model's answer being malformed, not
        # the provider failing, and the router has a specific repair for it (a
        # shrink-and-retry, or a split for a batch). Translated, the pydantic
        # error was substring-classified instead — and since it echoes the start
        # of the reply, a truncated Safety answer matched the terminal marker
        # "safety" and benched a healthy key, while every other dimension was
        # re-sent verbatim three times.
        return schema.model_validate_json(text)

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
        except (QuotaExceededError, RetryableError, TerminalProviderError):
            raise
        except Exception as exc:
            raise _as_provider_error(exc) from exc
