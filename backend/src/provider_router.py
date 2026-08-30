from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from src import metrics
from src.key_health import get_registry
from src.llm_provider import (
    GeminiProvider,
    GroqProvider,
    LLMProvider,
    QuotaExceededError,
    RetryableError,
    TerminalProviderError,
)
from src.provider_errors import FailureKind, classify

logger = structlog.get_logger()

MAX_RETRIES = int(os.getenv("PROVIDER_MAX_RETRIES", "3"))
RETRY_BACKOFF_SECONDS = float(os.getenv("PROVIDER_RETRY_BACKOFF", "2.0"))


def _jittered_wait(base: float, spread: float = 0.5) -> float:
    """Backoff with jitter: base * uniform(1 - spread, 1 + spread).

    Jittered retries de-synchronize concurrent dimension threads (the
    parallel analysis loop) so they don't all retry at the same instant
    and re-collide on the same quota window.
    """
    low = base * (1.0 - spread)
    high = max(base * (1.0 + spread), low + 0.01)
    return random.uniform(low, high)


GROQ_TPM_LIMIT = int(os.getenv("GROQ_TPM_LIMIT", "12000"))
GROQ_TPM_WINDOW = float(os.getenv("GROQ_TPM_WINDOW", "60"))

# ── Gemini free-tier throttle (generalized from the Groq-only throttle) ──
# Gemini free tier limits PER KEY (confirmed from Google AI Studio docs):
# flash-tier models are ~10-15 RPM / 250k-1M TPM / 250-1500 RPD per key.
# The primary provider is Gemini with N rotating keys, so we throttle:
#   - RPM: ONE rolling 60s request-count window PER KEY, sized conservatively
#     to the LOWEST documented flash-tier RPM (10) so it is safe for any flash
#     model the env may select (gemini-2.x-flash / 2.5-flash). Each key gets
#     its own throttle and requests round-robin across keys (GeminiProvider.
#     next_key), so the pool's real headroom is N keys x per-key RPM — a
#     single shared throttle (the old design) capped the whole pool at ONE
#     key's RPM even with 4 keys configured, which was the single biggest
#     wall-clock cost in an analysis run.
#   - RPD: daily request counter across ALL keys (the binding constraint on
#     a full 16-call analysis run; Gemini enforces RPD per project/key, and
#     with 4 keys a full run is well inside the combined budget).
# Both are env-tunable like the Groq throttle. Token-level TPM is not the
# binding constraint for flash-tier free quotas (250k-1M TPM vs 10-15 RPM),
# so RPM + RPD cover the realistic 429 sources.
GEMINI_RPM_LIMIT = int(os.getenv("GEMINI_RPM_LIMIT", "10"))
GEMINI_RPM_WINDOW = float(os.getenv("GEMINI_RPM_WINDOW", "60"))
GEMINI_RPD_LIMIT = int(os.getenv("GEMINI_RPD_LIMIT", "1000"))
GEMINI_RPD_WARNING_PCT = float(os.getenv("GEMINI_RPD_WARNING_PCT", "0.8"))

# RPD counter persistence — a date-keyed JSON file so a server restart mid-day
# does NOT silently reset how much of the daily Gemini quota has been used.
# Without this the in-memory counter believed it enforced a daily cap while a
# restart wiped the count (the real enforcement remains Gemini's own 429 +
# key rotation + Groq fallback, but the RPD hard-stop is only honest if the
# count survives restarts).
GEMINI_RPD_FILE = os.getenv("GEMINI_RPD_FILE", "./data/gemini_rpd.json")

# Guards the in-memory counter + file read-modify-write. uvicorn BackgroundTasks
# can run multiple analysis pipelines concurrently; without a lock, two tasks
# could both read count=N, increment to N+1, and the second write overwrites
# the first — silently losing one request from the daily tally.
_rpd_lock = threading.Lock()


def _rpd_date_key() -> str:
    return time.strftime("%Y-%m-%d")


def _load_daily_requests() -> int:
    """Load today's persisted request count (0 when absent/stale/corrupt)."""
    try:
        data = json.loads(Path(GEMINI_RPD_FILE).read_text(encoding="utf-8"))
        if data.get("date") == _rpd_date_key():
            return int(data.get("count", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return 0


def _persist_daily_requests(count: int) -> None:
    """Atomically write today's count (tmp + replace, never partial)."""
    try:
        path = Path(GEMINI_RPD_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"date": _rpd_date_key(), "count": count}),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as exc:
        logger.warning("rpd_persist_failed", error=str(exc))


def key_ids_for(provider: LLMProvider) -> list[str]:
    """Every credential id this provider can serve from.

    Exported so readiness and the metrics scrape ask the same question the
    router does. Both previously rebuilt the id from the class name inline,
    which meant a rename in one place silently made them look at a different
    (and always-healthy) set of records.
    """
    count = len(getattr(provider, "api_keys", []) or [1])
    return [_key_id(provider, i) for i in range(count)]


def _key_id(provider: LLMProvider, key_index: int | None) -> str:
    """A stable, non-secret label for one credential.

    Never the key itself: this string reaches logs, /readyz and the metrics
    endpoint. The index is enough to tell credentials apart operationally.
    """
    if key_index is None:
        return f"{type(provider).__name__.lower()}:default"
    return f"{type(provider).__name__.lower()}:{key_index}"


class TokenThrottle:
    """Rolling-window token throttle to stay under a provider's TPM limit.

    Tracks (timestamp, tokens) pairs in a sliding window. Before each call,
    estimates whether the next call would exceed the limit; if so, sleeps
    until the oldest entry falls out of the window. Actual tokens consumed
    are recorded on success to keep the window accurate.
    """

    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self._entries: list[tuple[float, int]] = []

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        self._entries = [(t, n) for t, n in self._entries if t > cutoff]

    def wait(self, estimated_input: int, output_buffer: int = 500) -> None:
        now = time.time()
        self._prune(now)
        window_total = sum(n for _, n in self._entries)
        estimated_total = estimated_input + output_buffer
        available = self.limit - window_total
        if estimated_total > available and self._entries:
            oldest_ts = self._entries[0][0]
            wait = (oldest_ts + self.window) - now
            if wait > 0:
                pct = window_total / self.limit * 100
                print(
                    f"[THROTTLE] Groq TPM: {window_total}/{self.limit} ({pct:.0f}%) "
                    f"in last {self.window:.0f}s. "
                    f"Next call needs ~{estimated_total} tokens, "
                    f"only {available} available. "
                    f"Sleeping {wait:.1f}s..."
                )
                time.sleep(wait)
                self._prune(time.time())

    def record(self, tokens: int) -> None:
        now = time.time()
        self._prune(now)
        self._entries.append((now, tokens))

    @property
    def total_used(self) -> int:
        now = time.time()
        self._prune(now)
        return sum(n for _, n in self._entries)

    def reset(self) -> None:
        self._entries.clear()


_groq_throttle = TokenThrottle(limit=GROQ_TPM_LIMIT, window=GROQ_TPM_WINDOW)


class RequestThrottle:
    """Rolling-window REQUEST-COUNT throttle (RPM), for providers whose
    binding constraint is requests/minute rather than tokens/minute (Gemini
    flash free tier: ~10-15 RPM vs 250k-1M TPM).

    Tracks request timestamps in a sliding window; before each call, sleeps
    until a slot frees when the window is full. record() is called on
    success. Same shape as TokenThrottle so both are interchangeable.
    """

    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self._timestamps: list[float] = []
        # The parallel analysis loop runs dimension LLM calls concurrently;
        # the lock makes wait()/record() an atomic pacing queue so N workers
        # can never all pass the check and burst past the RPM ceiling.
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def wait(self) -> None:
        with self._lock:
            now = time.time()
            self._prune(now)
            if len(self._timestamps) >= self.limit and self._timestamps:
                oldest_ts = self._timestamps[0]
                wait = (oldest_ts + self.window) - now
                if wait > 0:
                    pct = len(self._timestamps) / self.limit * 100
                    print(
                        f"[THROTTLE] Gemini RPM: {len(self._timestamps)}/{self.limit} "
                        f"requests in last {self.window:.0f}s ({pct:.0f}%). "
                        f"Sleeping {wait:.1f}s to stay under the free-tier RPM limit..."
                    )
                    time.sleep(wait)
                    self._prune(time.time())

    def record(self) -> None:
        with self._lock:
            now = time.time()
            self._prune(now)
            self._timestamps.append(now)

    def reset(self) -> None:
        with self._lock:
            self._timestamps.clear()


# One RequestThrottle per configured Gemini key, built lazily once the
# provider (and therefore the key count) exists. Requests round-robin across
# the throttles via GeminiProvider.next_key(), and the chosen key is passed
# into the call itself so the throttle and the actual key can never race.
_gemini_rpm_throttles: list[RequestThrottle] = []


def _gemini_throttles(provider: LLMProvider | None = None) -> list[RequestThrottle]:
    """Per-key RPM throttles, sized to the key count of the provider in use.

    Each Gemini key has its own free-tier RPM ceiling, so the pool's real
    headroom is keys x per-key RPM.

    `provider` is an argument rather than the module-global `_provider` for a
    reason. generate_with_retry indexes the returned list with a key index
    derived from the provider it was HANDED, while this used to size the list
    from the global. Whenever the two differed the index ran off the end and
    the call died with an IndexError mid-analysis instead of degrading —
    reachable whenever a caller holds a provider reference across a
    reset_provider(), and reliably in any test that constructs its own.
    """
    global _gemini_rpm_throttles
    n = 1
    provider = provider if provider is not None else _provider
    if isinstance(provider, GeminiProvider) and provider.api_keys:
        n = len(provider.api_keys)
    if len(_gemini_rpm_throttles) != n:
        _gemini_rpm_throttles = [
            RequestThrottle(limit=GEMINI_RPM_LIMIT, window=GEMINI_RPM_WINDOW) for _ in range(n)
        ]
    return _gemini_rpm_throttles


# Initialised from the persisted file (date-keyed), NOT from zero: a server
# restart mid-day must keep counting today's already-consumed quota.
_daily_gemini_requests = _load_daily_requests()


def quota_status() -> dict[str, Any]:
    """Daily Gemini request budget, for the readiness probe.

    Reports the same counter `_check_gemini_daily_budget` enforces, so a
    readiness probe and the pipeline can never disagree about whether there
    is headroom left. `date` is the counter's own key: the budget resets
    when the local date rolls over, not on a rolling 24h window.

    Note this is Meridian's own accounting, not a reading of Google's
    quota — the authoritative limit is still enforced provider-side by a
    429. It answers "will this process accept an analysis right now", which
    is the question a readiness probe is asking.
    """
    with _rpd_lock:
        used = _daily_gemini_requests
    remaining = max(GEMINI_RPD_LIMIT - used, 0)
    return {
        "requests_today": used,
        "daily_limit": GEMINI_RPD_LIMIT,
        "remaining": remaining,
        "has_headroom": remaining > 0,
        "date": _rpd_date_key(),
    }


def _check_gemini_daily_budget() -> None:
    """Enforce the Gemini free-tier RPD budget with an early warning.

    Called before every primary Gemini call. Warns at GEMINI_RPD_WARNING_PCT
    of the daily limit; hard-stops with a clear, actionable error when the
    limit is exhausted (the same messaging the 429 path uses). The counter
    is in-memory per process — the real enforcement is still Gemini's own
    429 + key rotation + Groq fallback.
    """
    global _daily_gemini_requests
    pct = _daily_gemini_requests / GEMINI_RPD_LIMIT if GEMINI_RPD_LIMIT > 0 else 0
    if _daily_gemini_requests >= GEMINI_RPD_LIMIT:
        raise RuntimeError(
            f"Gemini free-tier daily request budget exhausted "
            f"({_daily_gemini_requests}/{GEMINI_RPD_LIMIT} requests today). "
            f"The RPD cap protects against the free tier's daily limit — "
            f"raise GEMINI_RPD_LIMIT in .env if you have a higher plan, or "
            f"continue tomorrow when the quota resets."
        )
    if pct >= GEMINI_RPD_WARNING_PCT:
        print(
            f"[WARN] Gemini daily request budget at {pct:.0%}: "
            f"{_daily_gemini_requests}/{GEMINI_RPD_LIMIT} used today."
        )


DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
DEV_TOKEN_CAP = int(os.getenv("DEV_TOKEN_CAP", "20000"))
_daily_live_tokens: int = 0

_provider: LLMProvider | None = None
_original_provider: str | None = None

_request_counter = 0
_debug_stats: dict[str, Any] = {
    "primary_requests": [],
    "total_primary": 0,
    "successful": 0,
    "failed": 0,
    "quota_errors": 0,
    "retries": 0,
    "fallbacks": 0,
}

# Groq fallback provider — initialized lazily on first need
_groq_fallback_provider: GroqProvider | None = None


def _init_groq_fallback() -> GroqProvider | None:
    """Initialize Groq as fallback. Called when all Gemini keys are exhausted."""
    global _groq_fallback_provider
    if _groq_fallback_provider is not None:
        return _groq_fallback_provider
    try:
        _groq_fallback_provider = GroqProvider()
        print(f"[DEBUG] Groq fallback ready: model={_groq_fallback_provider.model_name}")
        return _groq_fallback_provider
    except Exception as exc:
        print(f"[DEBUG] Groq fallback not available: {exc}")
        return None


def get_provider() -> LLMProvider:
    global _provider, _original_provider

    if _provider is not None:
        return _provider

    # Checked before anything reads a credential, so replay mode works with
    # no key configured at all — which is the point: CI and load tests must
    # not need one.
    from src.replay import ReplayProvider, is_replay_enabled

    if is_replay_enabled():
        _provider = ReplayProvider()
        _original_provider = "replay"
        return _provider

    preferred = os.getenv("LLM_PROVIDER", "gemini").lower()

    if preferred == "gemini":
        _provider = GeminiProvider()
        keys = len(getattr(_provider, "api_keys", [1]))
        print(f"[DEBUG] Provider: gemini (primary, {keys} key(s), model={_provider.model_name})")
    elif preferred == "groq":
        _provider = GroqProvider()
        print(f"[DEBUG] Provider: groq (primary, model={_provider.model_name})")
    else:
        print(f"[DEBUG] Provider: unknown '{preferred}', defaulting to gemini")
        _provider = GeminiProvider()

    _original_provider = preferred
    return _provider


class CapacityExhausted(RuntimeError):
    """No credential can serve right now, and we know roughly when one can.

    Deliberately distinct from "all keys exhausted": that message was
    produced by both a genuinely spent quota AND a mistyped model name, so
    it told an operator nothing about which had happened.
    """


def _pick_healthy_key(provider: GeminiProvider) -> int | None:
    """Round-robin across credentials the circuit breaker still trusts.

    next_key() alone put a credential that had just 429'd straight back into
    rotation on the following call, so a 429 storm spent the whole retry
    budget re-asking keys already known to be exhausted.
    """
    registry = get_registry()
    total = len(provider.api_keys)
    start = provider.next_key()
    for offset in range(total):
        index = (start + offset) % total
        if registry.is_available(_key_id(provider, index)):
            return index
    return None


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _extract_retry_delay(error_str: str) -> float | None:
    """Extract 'retry in X seconds' from a Gemini 429 error."""
    import re

    m = re.search(r"retry\s+in\s+([\d.]+)\s*s", error_str, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def _try_groq_fallback(
    prompt: str,
    schema: type,
    system_prompt: str | None,
    operation: str,
) -> Any:
    """Try Groq as a last-resort fallback when all Gemini keys are exhausted."""
    fallback = _init_groq_fallback()
    if fallback is None:
        raise RuntimeError(
            f"All Gemini keys exhausted and Groq fallback is not available "
            f"(check GROQ_API_KEY in .env). Operation: '{operation}'."
        )
    print(f"[DEBUG] Falling back to Groq for '{operation}'")
    _debug_stats["fallbacks"] += 1
    return fallback.generate_structured(prompt=prompt, schema=schema, system_prompt=system_prompt)


def generate_with_retry(
    provider: LLMProvider,
    prompt: str,
    schema: type,
    system_prompt: str | None = None,
    operation: str = "unknown",
    debug_ctx: dict[str, Any] | None = None,
) -> Any:
    global _request_counter
    _request_counter += 1
    req_num = _request_counter

    if debug_ctx is None:
        debug_ctx = {}

    if provider.tier != "primary":
        print(
            f"[DEBUG] REQ #{req_num} | {operation} | Using {provider.model_name} (tier={provider.tier}) directly"
        )
        return provider.generate_structured(
            prompt=prompt, schema=schema, system_prompt=system_prompt
        )

    prompt_chars = len(prompt) + (len(system_prompt) if system_prompt else 0)
    estimated_input_tokens = _estimate_tokens(prompt)
    n_chunks = debug_ctx.get("num_chunks", "?")
    n_frameworks = debug_ctx.get("num_frameworks", "?")

    # Track request info for the debug summary
    request_info: dict[str, Any] = {
        "req_num": req_num,
        "operation": operation,
        "model": provider.model_name,
        "provider": "gemini" if isinstance(provider, GeminiProvider) else "groq",
        "prompt_chars": prompt_chars,
        "estimated_input_tokens": estimated_input_tokens,
        "num_chunks": n_chunks,
        "num_frameworks": n_frameworks,
        "start_time": time.time(),
        "end_time": None,
        "latency": None,
        "status_code": None,
        "output_tokens": None,
        "error_response": None,
        "was_retried": False,
        "fell_back": False,
    }

    last_error: Exception | None = None
    start = 0.0

    # The daily RPD budget is checked ONCE, before the retry loop — if it is
    # exhausted, the error surfaces immediately instead of spinning through
    # MAX_RETRIES attempts that each re-raise the same RuntimeError. (The
    # RPM throttle below still runs per attempt; it only sleeps.)
    if isinstance(provider, GeminiProvider):
        _check_gemini_daily_budget()

    # Quota rotation needs one attempt per Gemini key; non-quota retries are
    # still capped by MAX_RETRIES (the RetryableError / generic branches check
    # `attempt < MAX_RETRIES`). Without this the rotation bug bites: with 4
    # keys and MAX_RETRIES=3, attempts 1-3 each rotate to the next key, key #4
    # is never tried, the all-keys-exhausted branch never runs (rotation keeps
    # returning True), Groq fallback never fires, and the loop falls out with
    # a misleading "generate_with_retry failed unexpectedly" instead of a
    # clear "all keys exhausted" error.
    max_attempts = max(
        MAX_RETRIES,
        len(getattr(provider, "api_keys", [1])) if isinstance(provider, GeminiProvider) else 1,
    )

    for attempt in range(1, max_attempts + 1):
        # ── Attempt the primary provider ──────────────────────────────
        # Per-key throttle + round-robin key pick BEFORE the call: with N
        # Gemini keys each call reserves a slot on ONE key's throttle and
        # passes that key index into the call, so the pool uses all N keys'
        # RPM headroom (N x 10-15/min) instead of one shared 10/min window.
        gemini_throttle: RequestThrottle | None = None
        key_index: int | None = None
        if isinstance(provider, GeminiProvider):
            # Generalized throttle: the Gemini free tier's binding limits
            # are RPM and RPD (10-15 RPM / 250-1500 RPD per key), not
            # TPM — so we throttle request-count, not tokens. The RPD
            # budget is checked once above (before the loop); the RPM
            # throttle paces each attempt so a full 16-call run stays under
            # the free tier instead of discovering the limit reactively on
            # a 429.
            throttles = _gemini_throttles(provider)
            key_index = _pick_healthy_key(provider)
            if key_index is None:
                # Every credential is either circuit-open or out of daily
                # budget. Degrade honestly with a time rather than spinning
                # through the retry budget re-asking keys we were just told
                # are spent.
                wait = get_registry().seconds_until_any_available(
                    [_key_id(provider, i) for i in range(len(provider.api_keys))]
                )
                raise CapacityExhausted(
                    f"Provider capacity exhausted for '{operation}'. "
                    + (
                        "Daily budget spent; retry tomorrow."
                        if wait == float("inf")
                        else f"Retry after {wait:.0f}s."
                    )
                )
            gemini_throttle = throttles[key_index]
            gemini_throttle.wait()
        elif isinstance(provider, GroqProvider):
            throttle_input = prompt_chars // 4
            _groq_throttle.wait(estimated_input=throttle_input, output_buffer=500)

        try:
            start = time.time()
            if isinstance(provider, GeminiProvider):
                result = provider.generate_structured(
                    prompt=prompt,
                    schema=schema,
                    system_prompt=system_prompt,
                    key_index=key_index,
                )
            else:
                result = provider.generate_structured(
                    prompt=prompt, schema=schema, system_prompt=system_prompt
                )
            latency = time.time() - start

            # Log token usage
            token_usage = getattr(result, "_token_usage", None)
            if isinstance(provider, GroqProvider) and token_usage:
                request_info["prompt_tokens_actual"] = token_usage.get("prompt_tokens", 0)
                request_info["completion_tokens_actual"] = token_usage.get("completion_tokens", 0)
                request_info["total_tokens_actual"] = token_usage.get("total_tokens", 0)
                token_str = (
                    f"prompt_tok={token_usage['prompt_tokens']} "
                    f"completion_tok={token_usage['completion_tokens']} "
                    f"total_tok={token_usage['total_tokens']}"
                )
                global _daily_live_tokens
                _daily_live_tokens += token_usage.get("total_tokens", 0)
                pct = _daily_live_tokens / DEV_TOKEN_CAP * 100 if DEV_TOKEN_CAP > 0 else 0
                if _daily_live_tokens >= DEV_TOKEN_CAP:
                    print(
                        f"[WARN] DEV CAP EXCEEDED: {_daily_live_tokens}/{DEV_TOKEN_CAP} "
                        f"live tokens used today ({pct:.0f}%)."
                    )
                elif _daily_live_tokens >= DEV_TOKEN_CAP * 0.8:
                    print(
                        f"[WARN] DEV CAP AT {pct:.0f}%: {_daily_live_tokens}/{DEV_TOKEN_CAP} "
                        f"live tokens used today."
                    )
            else:
                token_str = f"est_tok={estimated_input_tokens}"

            request_info["end_time"] = time.time()
            request_info["latency"] = latency
            request_info["status_code"] = 200
            request_info["was_retried"] = attempt > 1
            _debug_stats["successful"] += 1

            if isinstance(provider, GeminiProvider):
                global _daily_gemini_requests
                with _rpd_lock:
                    _daily_gemini_requests += 1
                    _persist_daily_requests(_daily_gemini_requests)
                if gemini_throttle is not None:
                    gemini_throttle.record()
                # Per-credential accounting, and a success closes this key's
                # circuit if a previous failure had opened it.
                if key_index is not None:
                    get_registry().record_success(
                        _key_id(provider, key_index),
                        tokens=estimated_input_tokens,
                    )

            print(
                f"[DEBUG] REQ #{req_num} | {operation} | "
                f"model={provider.model_name} "
                f"prompt={prompt_chars}chars {token_str} "
                f"chunks={n_chunks} frameworks={n_frameworks} "
                f"status=200 latency={latency:.2f}s "
                f"attempt={attempt}/{MAX_RETRIES}"
            )

            request_info["output_tokens"] = _estimate_tokens(str(result))
            _debug_stats["primary_requests"].append(request_info)

            if isinstance(provider, GroqProvider) and token_usage:
                actual = token_usage.get("total_tokens", 0)
                _groq_throttle.record(actual)
                print(f"[THROTTLE] Groq TPM window: {_groq_throttle.total_used}/{GROQ_TPM_LIMIT}")

            return result

        # ── 429 / Quota Exceeded ──────────────────────────────────────
        except QuotaExceededError as exc:
            latency = time.time() - start if start else 0
            error_str = str(exc)
            request_info["end_time"] = time.time()
            request_info["latency"] = latency
            request_info["status_code"] = 429
            request_info["error_response"] = error_str[:500]
            request_info["was_retried"] = attempt > 1

            _debug_stats["quota_errors"] += 1
            _debug_stats["failed"] += 1
            if isinstance(provider, GeminiProvider) and key_index is not None:
                failure = classify(exc)
                get_registry().record_failure(
                    _key_id(provider, key_index),
                    FailureKind.QUOTA,
                    error_str,
                    retry_after=failure.retry_after_seconds,
                )

            print(
                f"[DEBUG] REQ #{req_num} | {operation} | "
                f"model={provider.model_name} "
                f"status=429 latency={latency:.2f}s "
                f"attempt={attempt}/{max_attempts} "
                f"error={error_str[:200]}"
            )

            # ── Step 1: retry on another credential, if one is healthy ──
            #
            # This used to call provider.rotate_key(), whose "is another key
            # available" test is `current_key_index < len(api_keys) - 1`. That
            # made sense when the index only ever moved forward on a 429, but
            # _pick_healthy_key round-robins with next_key() BEFORE each call,
            # so the index is wherever the rotation happened to land. Landing
            # on the last one — a 1-in-N chance every call — made a single 429
            # report every credential exhausted while N-1 were untried, and
            # sent the run to a fallback that cannot serve analysis prompts.
            #
            # The circuit breaker already knows which credentials can serve, so
            # it decides. rotate_key() is left alone for callers that still use
            # it directly.
            if isinstance(provider, GeminiProvider):
                healthy = get_registry().available_keys(key_ids_for(provider))
                if healthy and attempt < max_attempts:
                    print(
                        f"[DEBUG] {len(healthy)} credential(s) still healthy, retrying on another"
                    )
                    _debug_stats["retries"] += 1
                    metrics.provider_failover.labels(event="key_rotation").inc()
                    time.sleep(_jittered_wait(RETRY_BACKOFF_SECONDS))
                    continue
                metrics.provider_failover.labels(event="capacity_exhausted").inc()

            # ── Step 2: All Gemini keys exhausted — try Groq fallback ──
            #    Skip retry_delay on exhausted keys — fall back immediately
            print(
                f"[DEBUG] REQ #{req_num} | {operation} | "
                f"All Gemini keys exhausted, attempting Groq fallback"
            )
            _debug_stats["fallbacks"] += 1
            request_info["fell_back"] = True
            _debug_stats["primary_requests"].append(request_info)

            try:
                return _try_groq_fallback(
                    prompt=prompt,
                    schema=schema,
                    system_prompt=system_prompt,
                    operation=operation,
                )
            except RuntimeError:
                raise
            except Exception as groq_exc:
                # Groq also failed — try retry_delay on Gemini as last resort
                retry_delay = _extract_retry_delay(error_str)
                if retry_delay is not None and retry_delay <= 120.0 and attempt < MAX_RETRIES:
                    wait = _jittered_wait(max(retry_delay, RETRY_BACKOFF_SECONDS))
                    print(
                        f"[DEBUG] Groq also failed. Gemini 429 has retry delay {retry_delay:.0f}s — "
                        f"waiting {wait:.0f}s then retrying Gemini (attempt {attempt + 1}/{max_attempts})"
                    )
                    _debug_stats["retries"] += 1
                    last_error = exc
                    time.sleep(wait)
                    continue
                raise RuntimeError(
                    f"All Gemini API keys exhausted and Groq fallback failed "
                    f"for '{operation}': {groq_exc}"
                ) from groq_exc

        # ── Terminal: retrying cannot help ────────────────────────────
        except TerminalProviderError as exc:
            if isinstance(provider, GeminiProvider) and key_index is not None:
                get_registry().record_failure(
                    _key_id(provider, key_index), FailureKind.TERMINAL, str(exc)
                )
            request_info["status_code"] = "terminal"
            request_info["error_response"] = str(exc)[:500]
            _debug_stats["failed"] += 1
            _debug_stats["primary_requests"].append(request_info)
            logger.error(
                "provider_terminal_failure",
                operation=operation,
                key_id=_key_id(provider, key_index),
                error=str(exc)[:200],
            )
            # No rotation, no backoff, no fallback: a retired model or an
            # invalid credential is not a capacity problem, and dressing it
            # up as one is what made "all keys exhausted" uninformative.
            raise

        # ── Retryable Error (5xx, timeout) ────────────────────────────
        except RetryableError as exc:
            latency = time.time() - start if start else 0
            error_str = str(exc)
            if isinstance(provider, GeminiProvider) and key_index is not None:
                get_registry().record_failure(
                    _key_id(provider, key_index), FailureKind.RETRYABLE, error_str
                )

            if attempt < MAX_RETRIES:
                wait = _jittered_wait(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                _debug_stats["retries"] += 1
                print(
                    f"[DEBUG] REQ #{req_num} | {operation} | "
                    f"model={provider.model_name} "
                    f"status=retryable({error_str[:100]}) "
                    f"latency={latency:.2f}s "
                    f"attempt={attempt}/{max_attempts} "
                    f"retrying in {wait:.1f}s"
                )
                time.sleep(wait)
                last_error = exc
            else:
                request_info["status_code"] = "retryable_maxed"
                request_info["error_response"] = error_str[:500]
                request_info["was_retried"] = True
                _debug_stats["failed"] += 1
                _debug_stats["primary_requests"].append(request_info)
                raise RuntimeError(
                    f"LLM call '{operation}' failed after {MAX_RETRIES} retries: {error_str[:200]}"
                ) from exc

        # ── Unexpected Error ──────────────────────────────────────────
        except Exception as exc:
            latency = time.time() - start if start else 0
            error_str = str(exc)
            last_error = exc
            _debug_stats["failed"] += 1

            # ── Schema-validation repair ──────────────────────────────
            # A pydantic ValidationError means the model returned JSON that
            # did not match the schema — typically TRUNCATED output (the
            # combined Module 1+2 response is long). Retrying the identical
            # prompt reproduces the identical truncation, so on validation
            # failures we retry with an instruction to shrink the output
            # instead of repeating the exact same call. This is what stops
            # long dimensions (e.g. Privacy) from degrading into
            # "Insufficient Evidence" gaps on truncation.
            if (
                isinstance(exc, ValidationError)
                and attempt < MAX_RETRIES
                and "KEEPING IT SHORT AND VALID" not in prompt
            ):
                prompt = (
                    prompt + "\n\nIMPORTANT: your previous response failed JSON schema "
                    "validation because it was incomplete or malformed. Return "
                    "the JSON object now, KEEPING IT SHORT AND VALID: trim the "
                    "verbatim quotes to at most 2-3 passages, drop the least "
                    "important citations, and output ONLY the JSON object."
                )
                print(
                    f"[DEBUG] REQ #{req_num} | {operation} | schema validation "
                    f"failed (truncated/invalid JSON) — retrying with shrink "
                    f"instruction (attempt {attempt + 1}/{max_attempts})"
                )
                _debug_stats["retries"] += 1
                request_info["was_retried"] = True
                continue

            request_info["end_time"] = time.time()
            request_info["latency"] = latency
            request_info["status_code"] = "error"
            request_info["error_response"] = error_str[:500]
            request_info["was_retried"] = attempt > 1

            print(
                f"[DEBUG] REQ #{req_num} | {operation} | "
                f"model={provider.model_name} "
                f"status=error latency={latency:.2f}s "
                f"attempt={attempt}/{max_attempts} "
                f"error={error_str[:200]}"
            )

            if attempt == MAX_RETRIES:
                _debug_stats["primary_requests"].append(request_info)
                raise

    raise last_error or RuntimeError("generate_with_retry failed unexpectedly")


def print_debug_summary() -> None:
    primary_reqs = _debug_stats["primary_requests"]
    total = len(primary_reqs)
    successful = _debug_stats["successful"]
    failed = _debug_stats["failed"]
    quota_errors = _debug_stats["quota_errors"]
    retries = _debug_stats["retries"]
    fallbacks = _debug_stats["fallbacks"]

    total_input_tokens = sum(r.get("estimated_input_tokens", 0) for r in primary_reqs)
    total_output_tokens = sum(
        r.get("output_tokens", 0) for r in primary_reqs if r.get("output_tokens")
    )
    total_actual_input_tokens = sum(r.get("prompt_tokens_actual", 0) for r in primary_reqs)
    total_actual_output_tokens = sum(r.get("completion_tokens_actual", 0) for r in primary_reqs)
    total_actual_tokens = sum(r.get("total_tokens_actual", 0) for r in primary_reqs)
    prompt_chars_list = [r.get("prompt_chars", 0) for r in primary_reqs if r.get("prompt_chars")]
    avg_prompt_size = sum(prompt_chars_list) // len(prompt_chars_list) if prompt_chars_list else 0
    latencies = [r.get("latency", 0) for r in primary_reqs if r.get("latency") is not None]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    print()
    print("=" * 60)
    print("LLM ANALYSIS SUMMARY")
    print("=" * 60)
    print()
    print("Primary Provider Requests:")
    print(f"  Total:          {total}")
    print(f"  Successful:     {successful}")
    print(f"  Failed:         {failed}")
    print(f"  429 Errors:     {quota_errors}")
    print(f"  Key Rotations:  {retries}")
    print(f"  Groq Fallbacks: {fallbacks}")
    print(f"  Estimated Total Input Tokens:  {total_input_tokens}")
    print(f"  Estimated Total Output Tokens: {total_output_tokens}")
    print(f"  Gemini requests today:         {_daily_gemini_requests}/{GEMINI_RPD_LIMIT} (RPD)")
    if total_actual_tokens > 0:
        print(f"  Actual Groq Input Tokens:      {total_actual_input_tokens}")
        print(f"  Actual Groq Output Tokens:     {total_actual_output_tokens}")
        print(f"  Actual Groq Total Tokens:      {total_actual_tokens}")
    print(f"  Average Prompt Size:           {avg_prompt_size} chars")
    print(f"  Average Latency:               {avg_latency:.2f}s")
    print()
    print("=" * 60)


# Chat replies are deliberately concise (the prompts cap them at ~120 words),
# so chat calls don't need the analysis path's 8192-token generation budget.
# A smaller output cap makes flash-tier calls complete faster (the API has
# less output headroom to reserve), while remaining far above any real reply.
CHAT_MAX_OUTPUT_TOKENS = int(os.getenv("CHAT_MAX_OUTPUT_TOKENS", "1024"))

# Wall-clock budget for a single chat turn's LLM work. The retry ladder was
# written for the analysis pipeline, where a 120-second wait on a 429 is a
# reasonable trade for not losing a run. On a chat turn it is not: someone is
# watching a spinner, and a reply that arrives after two minutes is worse than
# an honest degraded one. Past the budget the call gives up and the caller
# falls back to its template response, which every chat path already handles.
CHAT_DEADLINE_SECONDS = float(os.getenv("CHAT_DEADLINE_SECONDS", "24"))


# Below this, a fresh attempt cannot plausibly finish, so spending the
# remaining budget on a backoff sleep just delays the same failure.
MIN_ATTEMPT_HEADROOM_SECONDS = float(os.getenv("CHAT_MIN_ATTEMPT_HEADROOM", "6"))


class ChatDeadlineExceeded(RuntimeError):
    """The turn's LLM budget ran out — caller should degrade, not retry."""


def generate_text_with_retry(
    provider: LLMProvider,
    prompt: str,
    system_prompt: str | None = None,
    operation: str = "chat",
    max_attempts: int | None = None,
    deadline_seconds: float | None = None,
) -> str:
    """Free-text sibling of generate_with_retry for chat calls.

    Chat is user-initiated and potentially high-frequency, so it must share
    the SAME Gemini RPD/RPM budget as the analysis pipeline — not bypass it
    by calling provider.generate_text() directly. Applies the identical
    discipline:
      - RPD daily-budget check before the first attempt
      - RPM rolling-window throttle before every primary attempt
      - key rotation on 429 (QuotaExceededError)
      - Groq fallback when all Gemini keys are exhausted
      - backoff retries on RetryableError (5xx/timeout)

    Returns the generated text; raises RuntimeError with a clear message when
    the budget is exhausted or every provider failed.
    """
    global _daily_gemini_requests
    # Same budget rule as generate_with_retry, INCLUDING the provider guard.
    # This line previously copied the formula but dropped the
    # `isinstance(provider, GeminiProvider)` check, so a non-Gemini provider
    # that happens to expose an api_keys attribute would silently get a
    # different retry budget here than on the structured path. The two
    # functions duplicate this logic; where they do, they must at least agree.
    attempts = max_attempts or max(
        MAX_RETRIES,
        len(getattr(provider, "api_keys", [1])) if isinstance(provider, GeminiProvider) else 1,
    )
    last_error: Exception | None = None

    budget = CHAT_DEADLINE_SECONDS if deadline_seconds is None else deadline_seconds
    deadline = time.time() + budget if budget > 0 else None

    def _remaining() -> float:
        return float("inf") if deadline is None else deadline - time.time()

    def _sleep_within_budget(wait: float) -> bool:
        """Sleep only if the turn can still afford it AND a retry after it."""
        if deadline is None:
            time.sleep(wait)
            return True
        # A sleep that leaves no room for the retry it precedes is pure delay.
        if wait + MIN_ATTEMPT_HEADROOM_SECONDS > _remaining():
            return False
        time.sleep(wait)
        return True

    if isinstance(provider, GeminiProvider):
        _check_gemini_daily_budget()

    for attempt in range(1, attempts + 1):
        if _remaining() <= 0:
            raise ChatDeadlineExceeded(
                f"Chat '{operation}' exceeded its {budget:.0f}s budget "
                f"after {attempt - 1} attempt(s)."
            )
        gemini_throttle: RequestThrottle | None = None
        key_index: int | None = None
        if isinstance(provider, GeminiProvider):
            throttles = _gemini_throttles(provider)
            key_index = provider.next_key()
            gemini_throttle = throttles[key_index]
            gemini_throttle.wait()
        elif isinstance(provider, GroqProvider):
            _groq_throttle.wait(estimated_input=len(prompt) // 4, output_buffer=400)

        try:
            start = time.time()
            if isinstance(provider, GeminiProvider):
                text = provider.generate_text(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    key_index=key_index,
                    max_output_tokens=CHAT_MAX_OUTPUT_TOKENS,
                )
            else:
                text = provider.generate_text(prompt=prompt, system_prompt=system_prompt)
            latency = time.time() - start

            if isinstance(provider, GeminiProvider):
                with _rpd_lock:
                    _daily_gemini_requests += 1
                    _persist_daily_requests(_daily_gemini_requests)
                if gemini_throttle is not None:
                    gemini_throttle.record()
                print(
                    f"[DEBUG] CHAT REQ | {operation} | model={provider.model_name} "
                    f"status=200 latency={latency:.2f}s attempt={attempt}/{attempts} "
                    f"RPD={_daily_gemini_requests}"
                )
            elif isinstance(provider, GroqProvider):
                _groq_throttle.record(len(text) // 4)

            _debug_stats["successful"] += 1
            return text

        except QuotaExceededError as exc:
            last_error = exc
            print(
                f"[DEBUG] CHAT REQ | {operation} | status=429 attempt={attempt}/{attempts} "
                f"error={str(exc)[:150]}"
            )
            if isinstance(provider, GeminiProvider) and provider.rotate_key():
                print(
                    f"[DEBUG] Chat rotated to Gemini key #{provider.current_key_index + 1}/"
                    f"{len(provider.api_keys)}, retrying"
                )
                if not _sleep_within_budget(_jittered_wait(RETRY_BACKOFF_SECONDS)):
                    raise ChatDeadlineExceeded(
                        f"Chat '{operation}' out of budget while rotating keys."
                    ) from exc
                continue
            try:
                return _try_groq_fallback_text(prompt, system_prompt, operation)
            except RuntimeError:
                raise
            except Exception as groq_exc:
                retry_delay = _extract_retry_delay(str(exc))
                if retry_delay is not None and retry_delay <= 120.0 and attempt < attempts:
                    wait = _jittered_wait(max(retry_delay, RETRY_BACKOFF_SECONDS))
                    print(
                        f"[DEBUG] Chat Gemini retry delay {retry_delay:.0f}s — waiting {wait:.0f}s"
                    )
                    if not _sleep_within_budget(wait):
                        raise ChatDeadlineExceeded(
                            f"Chat '{operation}' out of budget: provider asked for "
                            f"a {retry_delay:.0f}s wait."
                        ) from exc
                    continue
                raise RuntimeError(
                    f"Chat '{operation}' failed: all Gemini keys exhausted and "
                    f"Groq fallback failed: {groq_exc}"
                ) from groq_exc

        except RetryableError as exc:
            last_error = exc
            if attempt < attempts:
                wait = _jittered_wait(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                print(f"[DEBUG] CHAT REQ | {operation} | retryable, retrying in {wait:.1f}s")
                if not _sleep_within_budget(wait):
                    raise ChatDeadlineExceeded(
                        f"Chat '{operation}' out of budget after a retryable error."
                    ) from exc
                continue
            raise RuntimeError(
                f"Chat '{operation}' failed after {attempts} attempts: {str(exc)[:200]}"
            ) from exc

        except Exception as exc:
            last_error = exc
            _debug_stats["failed"] += 1
            print(f"[DEBUG] CHAT REQ | {operation} | error={str(exc)[:150]}")
            if attempt < attempts:
                continue
            raise

    raise last_error or RuntimeError(f"Chat '{operation}' failed unexpectedly")


def _try_groq_fallback_text(
    prompt: str,
    system_prompt: str | None,
    operation: str,
) -> str:
    """Groq fallback for free-text chat calls (no schema)."""
    fallback = _init_groq_fallback()
    if fallback is None:
        raise RuntimeError(
            f"All Gemini keys exhausted and Groq fallback is not available "
            f"(check GROQ_API_KEY in .env). Operation: '{operation}'."
        )
    print(f"[DEBUG] Chat falling back to Groq for '{operation}'")
    _debug_stats["fallbacks"] += 1
    return fallback.generate_text(prompt=prompt, system_prompt=system_prompt)


def reset_provider() -> None:
    global _provider, _original_provider, _daily_gemini_requests, _gemini_rpm_throttles
    _provider = None
    _original_provider = None
    _groq_throttle.reset()
    for t in _gemini_rpm_throttles:
        t.reset()
    _gemini_rpm_throttles = []
    with _rpd_lock:
        _daily_gemini_requests = 0
        # Explicit dev/test reset — clears the persisted counter too, so a
        # subsequent process start begins from a known-zero state.
        try:
            path = Path(GEMINI_RPD_FILE)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"date": _rpd_date_key(), "count": 0}),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError:
            pass
