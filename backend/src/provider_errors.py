"""One place that decides what a provider failure means.

The classification was duplicated across four call sites in llm_provider.py
as ad-hoc substring checks, and they disagreed in ways that mattered:

  - A 404 ("model not found", "is no longer available") was raised as
    QuotaExceededError. That is a TERMINAL error — the model name is wrong,
    or the model was retired — but the router treats QuotaExceededError as
    "this key is spent", so it rotated through every configured key, then
    fell through to the Groq fallback, and reported the whole thing as
    exhausted quota. The operator sees "all keys exhausted" when the actual
    fix is one line in .env. That happened here already: llama-3.3-70b was
    retired from Groq's catalog and every quota exhaustion fell through to a
    dead fallback.
  - "rate" matched anything containing the substring, including the word
    "accurate" in a model's own error prose.
  - A 400 (malformed request, prompt too long, safety block) fell through to
    the bare `raise`, which the router's generic handler then retried
    MAX_RETRIES times against an identical request that could not succeed.

Retry-After is read from the exception's response headers where the SDK
exposes them, and only falls back to scraping the message text. The previous
code only ever scraped, so a provider that answered properly was ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class FailureKind(str, Enum):
    """What the caller should do about it."""

    QUOTA = "quota"  # this credential is spent; try another
    RETRYABLE = "retryable"  # transient; back off and retry the same credential
    TERMINAL = "terminal"  # retrying cannot help; surface it


@dataclass(frozen=True)
class ProviderFailure:
    kind: FailureKind
    reason: str
    status_code: int | None = None
    retry_after_seconds: float | None = None

    @property
    def is_retryable(self) -> bool:
        return self.kind is not FailureKind.TERMINAL


# Ordered most-specific first. A 404 must be tested before the generic 4xx
# rule, and "quota" before "rate", or the wrong branch wins.
_STATUS_RE = re.compile(r"\b(4\d{2}|5\d{2})\b")

_TERMINAL_MARKERS = (
    "model not found",
    "model_not_found",
    "is no longer available",
    "was not found",
    "api key not valid",
    "api_key_invalid",
    "permission denied",
    "unauthorized",
    "invalid argument",
    "safety",
)

_QUOTA_MARKERS = (
    "quota",
    "resource_exhausted",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "too many requests",
)

_RETRYABLE_MARKERS = (
    "timeout",
    "timed out",
    "deadline exceeded",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "service unavailable",
    "internal error",
    "unavailable",
)

_TERMINAL_STATUS = {400, 401, 403, 404, 405, 409, 413, 422}
_RETRYABLE_STATUS = {408, 425, 500, 502, 503, 504}


def _status_code(exc: BaseException, text: str) -> int | None:
    """Prefer a real status attribute; fall back to scraping the message."""
    for attr in ("status_code", "code", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    match = _STATUS_RE.search(text)
    return int(match.group(1)) if match else None


def _retry_after(exc: BaseException, text: str) -> float | None:
    """Honour the provider's own instruction before guessing at a backoff.

    Reads the Retry-After header where the SDK exposes a response, which is
    the authoritative answer, and only then falls back to the "retry in Ns"
    prose the previous implementation relied on exclusively.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            raw = headers.get("Retry-After") or headers.get("retry-after")
        except Exception:
            raw = None
        if raw is not None:
            try:
                return max(float(str(raw).strip()), 0.0)
            except (TypeError, ValueError):
                pass  # HTTP-date form; the prose fallback below still applies

    match = re.search(r"retry\s+(?:in|after)\s+([\d.]+)\s*s", text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"['\"]?retryDelay['\"]?\s*[:=]\s*['\"]?([\d.]+)s", text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def classify(exc: BaseException) -> ProviderFailure:
    """Decide what a provider exception means for the retry loop."""
    text = str(exc)
    lowered = text.lower()
    status = _status_code(exc, text)
    retry_after = _retry_after(exc, text)

    # Terminal markers first: a retired model reports 404, and treating that
    # as spent quota burns every key before surfacing a one-line config fix.
    for marker in _TERMINAL_MARKERS:
        if marker in lowered:
            return ProviderFailure(FailureKind.TERMINAL, f"terminal: {marker}", status, retry_after)

    # 429 is quota regardless of prose. Checked before the status sets below
    # so a "rate limit" message without a parseable code still lands here.
    if status == 429 or any(m in lowered for m in _QUOTA_MARKERS):
        return ProviderFailure(FailureKind.QUOTA, "quota or rate limit", status, retry_after)

    if status in _TERMINAL_STATUS:
        return ProviderFailure(
            FailureKind.TERMINAL, f"terminal status {status}", status, retry_after
        )

    if status in _RETRYABLE_STATUS or any(m in lowered for m in _RETRYABLE_MARKERS):
        return ProviderFailure(
            FailureKind.RETRYABLE, "transient provider error", status, retry_after
        )

    # Unknown failures are retryable but bounded by the caller's retry budget.
    # Treating them as terminal would turn one flaky network blip into a lost
    # analysis; treating them as quota would burn a credential that is fine.
    return ProviderFailure(
        FailureKind.RETRYABLE, "unclassified provider error", status, retry_after
    )
