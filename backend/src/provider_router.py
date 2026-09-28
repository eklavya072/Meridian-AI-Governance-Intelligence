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
from src.key_health import get_registry, quota_day
from src.llm_provider import (
    GeminiProvider,
    LLMProvider,
    QuotaExceededError,
    RetryableError,
    TerminalProviderError,
)
from src.provider_errors import FailureKind, classify

logger = structlog.get_logger()

MAX_RETRIES = int(os.getenv("PROVIDER_MAX_RETRIES", "3"))
RETRY_BACKOFF_SECONDS = float(os.getenv("PROVIDER_RETRY_BACKOFF", "2.0"))
# A cooldown shorter than this is waited out rather than failed on. The free
# tier's binding limit is per-MINUTE (20 requests on gemini-3.6-flash), and a
# full analysis is 16 calls, so every run trips it; the cooldowns that follow
# are tens of seconds. Longer than this and the caller deserves the error.
CAPACITY_WAIT_CEILING_SECONDS = float(os.getenv("PROVIDER_CAPACITY_WAIT", "90"))


def _honour_retry_after(retry_delay: float) -> float:
    """Wait at least as long as the provider asked, plus jitter.

    _jittered_wait draws from [0.5x, 1.5x], so jittering an explicit
    Retry-After can come back UNDER it — the log read "the API asked for 37s —
    waiting 27s", and a retry sent before the window reopens is another 429
    and one fewer attempt. Jitter still de-synchronises concurrent dimensions;
    it just adds now rather than scaling.
    """
    return retry_delay + random.uniform(0.5, max(2.0, retry_delay * 0.15))


def _jittered_wait(base: float, spread: float = 0.5) -> float:
    """Backoff with jitter: base * uniform(1 - spread, 1 + spread).

    Jittered retries de-synchronize concurrent dimension threads (the
    parallel analysis loop) so they don't all retry at the same instant
    and re-collide on the same quota window.
    """
    low = base * (1.0 - spread)
    high = max(base * (1.0 + spread), low + 0.01)
    return random.uniform(low, high)


# ── Gemini free-tier throttle ────────────────────────────────────────────
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
# Both are env-tunable. Token-level TPM is not the
# binding constraint for flash-tier free quotas (250k-1M TPM vs 10-15 RPM),
# so RPM + RPD cover the realistic 429 sources.
# PER KEY, and the pool multiplies it: 5 keys at 10 is 50 requests a minute.
# Measured against the live API, the free tier refuses at 20 — "limit: 20,
# model: gemini-3.6-flash" — and that ceiling is per PROJECT, not per key, so
# adding credentials buys daily headroom and no extra rate. A 16-call analysis
# therefore tripped the limit on every run, and the retries that followed made
# it worse. Sized so the whole pool stays under the project ceiling:
# GEMINI_RPM_LIMIT x credentials <= 20.
GEMINI_RPM_LIMIT = int(os.getenv("GEMINI_RPM_LIMIT", "4"))
GEMINI_RPM_WINDOW = float(os.getenv("GEMINI_RPM_WINDOW", "60"))
# An OPTIONAL self-imposed cap, off unless you set it. It used to default to
# 1000, which was a guess that matched no real Gemini quota: the counter read
# 49/1000 while three of five credentials were already being refused, so the
# one number an operator would check was the one number that could not be
# trusted. The authoritative limit is whatever the provider enforces, and the
# registry now learns it from the refusals themselves.
GEMINI_RPD_LIMIT = int(os.getenv("GEMINI_RPD_LIMIT", "0")) or None
GEMINI_RPD_WARNING_PCT = float(os.getenv("GEMINI_RPD_WARNING_PCT", "0.8"))

# RPD counter persistence — a date-keyed JSON file so a server restart mid-day
# does NOT silently reset how much of the daily Gemini quota has been used.
# Without this the in-memory counter believed it enforced a daily cap while a
# restart wiped the count (the real enforcement remains Gemini's own 429 +
# key rotation, but the RPD hard-stop is only honest if the
# count survives restarts).
GEMINI_RPD_FILE = os.getenv("GEMINI_RPD_FILE", "./data/gemini_rpd.json")

# Guards the in-memory counter + file read-modify-write. uvicorn BackgroundTasks
# can run multiple analysis pipelines concurrently; without a lock, two tasks
# could both read count=N, increment to N+1, and the second write overwrites
# the first — silently losing one request from the daily tally.
_rpd_lock = threading.Lock()


def _rpd_date_key() -> str:
    return quota_day()


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


def configured_gemini_keys() -> int:
    """How many credentials exist, not how many the registry has touched.

    The registry only knows a key once something has happened on it, so
    counting its records answers "keys we have used today" — which reads as
    "all credentials are spent" the moment the first one is refused.
    """
    count = 1 if os.getenv("GEMINI_API_KEY") else 0
    count += sum(1 for i in range(2, 10) if os.getenv(f"GEMINI_API_KEY_{i}"))
    return count


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


class RequestThrottle:
    """Rolling-window REQUEST-COUNT throttle (RPM), for providers whose
    binding constraint is requests/minute rather than tokens/minute (Gemini
    flash free tier: ~10-15 RPM vs 250k-1M TPM).

    Tracks request timestamps in a sliding window; before each call, sleeps
    until a slot frees when the window is full. record() is called on
    success.
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
                    logger.info(
                        "gemini_rpm_throttle",
                        in_window=len(self._timestamps),
                        limit=self.limit,
                        window_s=self.window,
                        sleep_s=round(wait, 1),
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

    Headroom is answered by the credentials themselves, not by a configured
    number: a key that the provider has refused on a per-day quota is spent
    whatever our own counter says. `daily_limit` is therefore what was
    OBSERVED — the largest number of requests any credential served before
    being refused — and is null until something is refused.
    """
    with _rpd_lock:
        used = _daily_gemini_requests
    configured = configured_gemini_keys()
    snap = get_registry().snapshot()
    exhausted = snap["daily_exhausted"]
    observed = snap["requests_at_exhaustion_all"]
    return {
        "requests_today": used,
        # NOT "the daily limit". This counter restarts whenever the health
        # record is cleared or the process starts fresh, so it is a LOWER
        # BOUND on what a credential served before being refused. Reported as
        # a limit once, it claimed 6 on a day the same keys served 68.
        "requests_before_refusal": max(observed) if observed else None,
        "self_imposed_cap": GEMINI_RPD_LIMIT,
        "credentials": configured,
        "credentials_daily_exhausted": exhausted,
        "has_headroom": configured == 0 or exhausted < configured,
        "date": _rpd_date_key(),
    }


def _check_gemini_daily_budget() -> None:
    """Enforce the Gemini free-tier RPD budget with an early warning.

    Called before every primary Gemini call. Stops on what the PROVIDER has
    said, not on a number we chose: if every configured credential has been
    refused on a per-day quota, the run cannot proceed and says so with the
    counts it measured. GEMINI_RPD_LIMIT remains available as a self-imposed
    cap for anyone who wants to spend less than the provider allows, but it
    is off by default and is no longer the thing that decides.
    """
    global _daily_gemini_requests
    configured = configured_gemini_keys()
    snap = get_registry().snapshot()
    exhausted = snap["daily_exhausted"]
    if configured and exhausted >= configured:
        raise RuntimeError(
            f"Every configured Gemini credential ({configured}) has been refused "
            f"on a quota with no usable retry window, after {_daily_gemini_requests} "
            f"requests today. A rate limit would have said when to come back; this "
            f"did not — add a credential, enable billing, or continue tomorrow."
        )

    if GEMINI_RPD_LIMIT:
        pct = _daily_gemini_requests / GEMINI_RPD_LIMIT
        if _daily_gemini_requests >= GEMINI_RPD_LIMIT:
            raise RuntimeError(
                f"Self-imposed GEMINI_RPD_LIMIT reached "
                f"({_daily_gemini_requests}/{GEMINI_RPD_LIMIT} requests today). "
                f"This is Meridian's own cap, not the provider's — raise or "
                f"unset GEMINI_RPD_LIMIT in .env to keep going."
            )
        if pct >= GEMINI_RPD_WARNING_PCT:
            logger.warning(
                "gemini_self_cap_near", used=_daily_gemini_requests, limit=GEMINI_RPD_LIMIT
            )


_provider: LLMProvider | None = None

_request_counter = 0
_debug_stats: dict[str, Any] = {
    "primary_requests": [],
    "total_primary": 0,
    "successful": 0,
    "failed": 0,
    "quota_errors": 0,
    "retries": 0,
}


def get_provider() -> LLMProvider:
    global _provider

    if _provider is not None:
        return _provider

    # Checked before anything reads a credential, so replay mode works with
    # no key configured at all — which is the point: CI and load tests must
    # not need one.
    from src.replay import ReplayProvider, is_replay_enabled

    if is_replay_enabled():
        _provider = ReplayProvider()
        return _provider

    preferred = os.getenv("LLM_PROVIDER", "gemini").lower()

    if preferred == "gemini":
        _provider = GeminiProvider()
        keys = len(getattr(_provider, "api_keys", [1]))
        logger.info(
            "llm_provider_selected", provider="gemini", keys=keys, model=_provider.model_name
        )
    else:
        logger.warning("llm_provider_unknown", requested=preferred, using="gemini")
        _provider = GeminiProvider()

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


def generate_with_retry(
    provider: LLMProvider,
    prompt: str,
    schema: type,
    system_prompt: str | None = None,
    operation: str = "unknown",
    debug_ctx: dict[str, Any] | None = None,
    max_output_tokens: int | None = None,
) -> Any:
    global _request_counter
    _request_counter += 1
    req_num = _request_counter

    if debug_ctx is None:
        debug_ctx = {}

    if provider.tier != "primary":
        logger.info(
            "llm_request_direct",
            req=req_num,
            operation=operation,
            model=provider.model_name,
            tier=provider.tier,
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
        "provider": "gemini",
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
    # returning True), the all-keys-exhausted branch never runs, and the loop
    # falls out with
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
                # budget. The registry knows how long until one returns, so
                # a SHORT cooldown is something to wait out, not to fail on:
                # the free tier's binding limit is per-minute, a 16-call run
                # trips it routinely, and failing the dimension over a 40s
                # wait threw away a whole analysis to save forty seconds.
                wait = get_registry().seconds_until_any_available(
                    [_key_id(provider, i) for i in range(len(provider.api_keys))]
                )
                if wait <= CAPACITY_WAIT_CEILING_SECONDS and attempt < max_attempts:
                    # A zero wait here does NOT mean "available now": a
                    # credential whose cooldown has elapsed is flipped to
                    # HALF_OPEN by the first caller that asks, and every other
                    # caller then sees it as unavailable with 0s to go until a
                    # probe it cannot send. Sleeping 0s on that burned all five
                    # attempts in milliseconds and failed eight dimensions at
                    # once. Wait at least one backoff so the probe can resolve.
                    pause = max(wait, RETRY_BACKOFF_SECONDS) + 1.0
                    logger.info(
                        "llm_credentials_cooling",
                        req=req_num,
                        operation=operation,
                        wait_s=round(pause),
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                    )
                    _debug_stats["retries"] += 1
                    time.sleep(pause)
                    continue
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

        try:
            start = time.time()
            if isinstance(provider, GeminiProvider):
                # Only passed when set, so a single-dimension call is sent
                # exactly as before.
                extra = {"max_output_tokens": max_output_tokens} if max_output_tokens else {}
                result = provider.generate_structured(
                    prompt=prompt,
                    schema=schema,
                    system_prompt=system_prompt,
                    key_index=key_index,
                    **extra,
                )
            else:
                result = provider.generate_structured(
                    prompt=prompt, schema=schema, system_prompt=system_prompt
                )
            latency = time.time() - start

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

            logger.info(
                "llm_request_ok",
                req=req_num,
                operation=operation,
                model=provider.model_name,
                prompt_chars=prompt_chars,
                tokens=token_str,
                chunks=n_chunks,
                frameworks=n_frameworks,
                latency_s=round(latency, 2),
                attempt=attempt,
            )

            request_info["output_tokens"] = _estimate_tokens(str(result))
            _debug_stats["primary_requests"].append(request_info)

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
                # The kind the classifier decided, not a hardcoded QUOTA: a
                # per-day refusal has to reach the registry as one, or the
                # credential stays "healthy" and every later attempt is spent
                # re-asking a key the provider has already finished with.
                get_registry().record_failure(
                    _key_id(provider, key_index),
                    failure.kind,
                    error_str,
                    retry_after=failure.retry_after_seconds,
                )

            logger.warning(
                "llm_request_quota",
                req=req_num,
                operation=operation,
                model=provider.model_name,
                latency_s=round(latency, 2),
                attempt=attempt,
                max_attempts=max_attempts,
                error=error_str[:200],
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
            # it decides. (rotate_key() has since been removed outright.)
            if isinstance(provider, GeminiProvider):
                healthy = get_registry().available_keys(key_ids_for(provider))
                if healthy and attempt < max_attempts:
                    logger.info("llm_retry_on_other_credential", healthy=len(healthy))
                    _debug_stats["retries"] += 1
                    metrics.provider_failover.labels(event="key_rotation").inc()
                    time.sleep(_jittered_wait(RETRY_BACKOFF_SECONDS))
                    continue
                metrics.provider_failover.labels(event="capacity_exhausted").inc()

            # ── Step 2: every key exhausted — honour the provider's own wait ──
            # There is no second provider to fall through to, so the only
            # thing left that can help is waiting as long as the API asked.
            _debug_stats["primary_requests"].append(request_info)
            retry_delay = _extract_retry_delay(error_str)
            if retry_delay is not None and retry_delay <= 120.0 and attempt < MAX_RETRIES:
                wait = _honour_retry_after(max(retry_delay, RETRY_BACKOFF_SECONDS))
                logger.info(
                    "llm_retry_after",
                    req=req_num,
                    operation=operation,
                    requested_s=round(retry_delay),
                    wait_s=round(wait),
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                )
                _debug_stats["retries"] += 1
                last_error = exc
                time.sleep(wait)
                continue
            raise RuntimeError(f"All Gemini API keys exhausted for '{operation}'.") from exc

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
                logger.warning(
                    "llm_request_retryable",
                    req=req_num,
                    operation=operation,
                    model=provider.model_name,
                    error=error_str[:100],
                    latency_s=round(latency, 2),
                    attempt=attempt,
                    max_attempts=max_attempts,
                    retry_in_s=round(wait, 1),
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
            # A whole batch is the exception. gap_analyzer._ask_batched
            # answers a malformed batch by splitting it in two at full
            # length; the shrink instruction would thin every dimension in
            # it, and a plain retry reproduces the same reply at the cost of
            # a request. The halves (operation "..._batch_part") get the
            # ordinary repair below, as a single dimension would.
            if isinstance(exc, ValidationError) and operation.endswith("_batch"):
                request_info["end_time"] = time.time()
                request_info["latency"] = latency
                request_info["status_code"] = "invalid_batch"
                request_info["error_response"] = error_str[:500]
                _debug_stats["primary_requests"].append(request_info)
                raise

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
                logger.warning(
                    "llm_reply_invalid_retrying_shorter",
                    req=req_num,
                    operation=operation,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                )
                _debug_stats["retries"] += 1
                request_info["was_retried"] = True
                continue

            request_info["end_time"] = time.time()
            request_info["latency"] = latency
            request_info["status_code"] = "error"
            request_info["error_response"] = error_str[:500]
            request_info["was_retried"] = attempt > 1

            logger.error(
                "llm_request_failed",
                req=req_num,
                operation=operation,
                model=provider.model_name,
                latency_s=round(latency, 2),
                attempt=attempt,
                max_attempts=max_attempts,
                error=error_str[:200],
            )

            if attempt == MAX_RETRIES:
                _debug_stats["primary_requests"].append(request_info)
                raise

    raise last_error or RuntimeError("generate_with_retry failed unexpectedly")


def log_run_summary() -> dict[str, Any]:
    """Provider usage for the run just finished, as one log event."""
    primary_reqs = _debug_stats["primary_requests"]
    prompt_chars_list = [r.get("prompt_chars", 0) for r in primary_reqs if r.get("prompt_chars")]
    latencies = [r.get("latency", 0) for r in primary_reqs if r.get("latency") is not None]
    snap = get_registry().snapshot()
    observed = snap["requests_at_exhaustion_all"]
    summary: dict[str, Any] = {
        "requests": len(primary_reqs),
        "successful": _debug_stats["successful"],
        "failed": _debug_stats["failed"],
        "quota_errors": _debug_stats["quota_errors"],
        "retries": _debug_stats["retries"],
        "estimated_input_tokens": sum(r.get("estimated_input_tokens", 0) for r in primary_reqs),
        "estimated_output_tokens": sum(
            r.get("output_tokens", 0) for r in primary_reqs if r.get("output_tokens")
        ),
        "actual_input_tokens": sum(r.get("prompt_tokens_actual", 0) for r in primary_reqs),
        "actual_output_tokens": sum(r.get("completion_tokens_actual", 0) for r in primary_reqs),
        "requests_today": _daily_gemini_requests,
        "observed_per_key_limit": max(observed) if observed else None,
        "credentials_spent": snap["daily_exhausted"],
        "credentials_configured": configured_gemini_keys(),
        "avg_prompt_chars": (
            sum(prompt_chars_list) // len(prompt_chars_list) if prompt_chars_list else 0
        ),
        "avg_latency_s": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
    }
    logger.info("llm_run_summary", **summary)
    return summary


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
            # Through the circuit breaker, like the analysis path. next_key()
            # alone handed chat credentials the analysis path had already
            # learned were spent for the day.
            key_index = _pick_healthy_key(provider)
            if key_index is None:
                raise ChatDeadlineExceeded(
                    f"Chat '{operation}': every credential is cooling down or spent for the day."
                )
            gemini_throttle = throttles[key_index]
            gemini_throttle.wait()

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
                if key_index is not None:
                    get_registry().record_success(
                        _key_id(provider, key_index), tokens=_estimate_tokens(prompt)
                    )
                logger.info(
                    "chat_request_ok",
                    operation=operation,
                    model=provider.model_name,
                    latency_s=round(latency, 2),
                    attempt=attempt,
                    max_attempts=attempts,
                    requests_today=_daily_gemini_requests,
                )

            _debug_stats["successful"] += 1
            return text

        except QuotaExceededError as exc:
            last_error = exc
            logger.warning(
                "chat_request_quota",
                operation=operation,
                attempt=attempt,
                max_attempts=attempts,
                error=str(exc)[:150],
            )
            # Chat shares the credentials, so a per-day refusal it discovers
            # has to reach the registry too — otherwise analysis walks back
            # into a key chat already learned was finished.
            if isinstance(provider, GeminiProvider) and key_index is not None:
                failure = classify(exc)
                get_registry().record_failure(
                    _key_id(provider, key_index),
                    failure.kind,
                    str(exc),
                    retry_after=failure.retry_after_seconds,
                )
            # Another credential the breaker still trusts, if there is one —
            # the same rule as the analysis path. rotate_key() only ever moved
            # forward from wherever the round-robin had landed, so a 429 on the
            # last index reported every credential spent while others were fine.
            if (
                isinstance(provider, GeminiProvider)
                and attempt < attempts
                and get_registry().available_keys(key_ids_for(provider))
            ):
                logger.info("chat_retry_on_other_credential")
                if not _sleep_within_budget(_jittered_wait(RETRY_BACKOFF_SECONDS)):
                    raise ChatDeadlineExceeded(
                        f"Chat '{operation}' out of budget while rotating keys."
                    ) from exc
                continue
            retry_delay = _extract_retry_delay(str(exc))
            if retry_delay is not None and retry_delay <= 120.0 and attempt < attempts:
                wait = _honour_retry_after(max(retry_delay, RETRY_BACKOFF_SECONDS))
                logger.info("chat_retry_after", requested_s=round(retry_delay), wait_s=round(wait))
                if not _sleep_within_budget(wait):
                    raise ChatDeadlineExceeded(
                        f"Chat '{operation}' out of budget: the API asked for "
                        f"a {retry_delay:.0f}s wait."
                    ) from exc
                continue
            raise RuntimeError(f"Chat '{operation}' failed: all Gemini keys exhausted.") from exc

        except RetryableError as exc:
            last_error = exc
            if isinstance(provider, GeminiProvider) and key_index is not None:
                get_registry().record_failure(
                    _key_id(provider, key_index), FailureKind.RETRYABLE, str(exc)
                )
            if attempt < attempts:
                wait = _jittered_wait(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                logger.warning(
                    "chat_request_retryable", operation=operation, retry_in_s=round(wait, 1)
                )
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
            logger.error("chat_request_failed", operation=operation, error=str(exc)[:150])
            if attempt < attempts:
                continue
            raise

    raise last_error or RuntimeError(f"Chat '{operation}' failed unexpectedly")


def reset_provider() -> None:
    global _provider, _daily_gemini_requests, _gemini_rpm_throttles
    _provider = None
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
