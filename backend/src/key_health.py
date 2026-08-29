"""Per-credential quota accounting and a circuit breaker.

What existed before: one global counter of requests made today, persisted to
a date-keyed JSON file. It could not answer "which credential is spent",
"which one is failing", or "when does this one recover" — so a credential
that 429'd was skipped for exactly one call and put straight back into
rotation by the next round-robin pick. Under a sustained 429 storm the
router spent its whole retry budget re-asking credentials it had just been
told were exhausted.

Two mechanisms here, both per credential:

  * Quota accounting — requests and tokens, with a reset boundary, persisted
    across restart so a mid-day restart does not silently forget what has
    already been spent.
  * A circuit breaker — CLOSED, OPEN, HALF_OPEN. Repeated failures open the
    circuit and drop the credential from rotation; after a cooldown a single
    probe is allowed through, and one success closes it again.

The breaker deliberately counts quota and transient failures separately from
terminal ones. A terminal failure (bad key, retired model) opens the circuit
immediately — retrying is pointless and the operator needs to see it — while
a 429 opens it only after repeated hits, because one 429 is normal
free-tier behaviour rather than a sick credential.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

from src.provider_errors import FailureKind

logger = structlog.get_logger()

# Consecutive non-terminal failures before a credential is dropped from
# rotation. One 429 is ordinary on a free tier; three in a row is a pattern.
BREAKER_FAILURE_THRESHOLD = int(os.getenv("PROVIDER_BREAKER_THRESHOLD", "3"))
# How long a credential stays out before a single probe is allowed through.
BREAKER_COOLDOWN_SECONDS = float(os.getenv("PROVIDER_BREAKER_COOLDOWN", "60"))


class CircuitState(str, Enum):
    CLOSED = "closed"  # healthy, in rotation
    OPEN = "open"  # dropped from rotation until cooldown elapses
    HALF_OPEN = "half_open"  # one probe permitted


@dataclass
class KeyHealth:
    """Everything known about one credential."""

    key_id: str
    requests: int = 0
    tokens: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    state: CircuitState = CircuitState.CLOSED
    opened_at: float | None = None
    last_error: str | None = None
    # Set from a provider's own Retry-After, so the cooldown reflects what it
    # actually asked for rather than our default guess.
    retry_after_until: float | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "requests": self.requests,
            "tokens": self.tokens,
            "failures": self.failures,
            "consecutive_failures": self.consecutive_failures,
            "state": self.state.value,
            "last_error": self.last_error,
            "seconds_until_probe": self.seconds_until_probe(),
        }

    def seconds_until_probe(self) -> float:
        if self.state is not CircuitState.OPEN:
            return 0.0
        deadline = self.opened_at or 0.0
        cooldown = BREAKER_COOLDOWN_SECONDS
        if self.retry_after_until:
            deadline = max(deadline + cooldown, self.retry_after_until)
        else:
            deadline = deadline + cooldown
        return max(deadline - time.time(), 0.0)


class KeyHealthRegistry:
    """Thread-safe health and quota state for every configured credential.

    The analysis pipeline runs dimensions concurrently, so every mutation is
    guarded. Persistence is date-keyed: the file records which day the counts
    belong to, and a load on a different day starts clean rather than
    carrying yesterday's spend forward.
    """

    def __init__(self, path: str | Path | None = None, daily_limit: int | None = None) -> None:
        self._lock = threading.RLock()
        self._keys: dict[str, KeyHealth] = {}
        self._path = Path(path or os.getenv("PROVIDER_HEALTH_FILE", "./data/provider_health.json"))
        self._daily_limit = daily_limit
        self._load()

    # ── persistence ─────────────────────────────────────────────────────
    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d")

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if data.get("date") != self._today():
            # A new day resets spend. Breaker state is not restored either:
            # a credential that was failing yesterday deserves a fresh probe,
            # not permanent exile from a file.
            return
        for key_id, raw in (data.get("keys") or {}).items():
            self._keys[key_id] = KeyHealth(
                key_id=key_id,
                requests=int(raw.get("requests", 0)),
                tokens=int(raw.get("tokens", 0)),
                failures=int(raw.get("failures", 0)),
            )

    def _persist_locked(self) -> None:
        payload = {
            "date": self._today(),
            "keys": {
                k: {"requests": h.requests, "tokens": h.tokens, "failures": h.failures}
                for k, h in self._keys.items()
            },
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self._path)
        except OSError as exc:
            logger.warning("provider_health_persist_failed", error=str(exc))

    # ── accounting ──────────────────────────────────────────────────────
    def _health(self, key_id: str) -> KeyHealth:
        health = self._keys.get(key_id)
        if health is None:
            health = KeyHealth(key_id=key_id)
            self._keys[key_id] = health
        return health

    def record_success(self, key_id: str, tokens: int = 0) -> None:
        with self._lock:
            health = self._health(key_id)
            health.requests += 1
            health.tokens += tokens
            health.consecutive_failures = 0
            if health.state is not CircuitState.CLOSED:
                logger.info("provider_circuit_closed", key_id=key_id, previous=health.state.value)
            # One success closes the circuit — that is the point of the probe.
            health.state = CircuitState.CLOSED
            health.opened_at = None
            health.retry_after_until = None
            self._persist_locked()

    def record_failure(
        self, key_id: str, kind: FailureKind, reason: str = "", retry_after: float | None = None
    ) -> None:
        with self._lock:
            health = self._health(key_id)
            health.failures += 1
            health.consecutive_failures += 1
            health.last_error = reason[:200] or kind.value
            if retry_after:
                health.retry_after_until = time.time() + retry_after

            # A terminal failure is not a flaky moment: the key is invalid or
            # the model is gone. Retrying it wastes the budget of every
            # analysis that follows, so it leaves rotation immediately.
            immediate = kind is FailureKind.TERMINAL
            if immediate or health.consecutive_failures >= BREAKER_FAILURE_THRESHOLD:
                if health.state is not CircuitState.OPEN:
                    logger.warning(
                        "provider_circuit_opened",
                        key_id=key_id,
                        kind=kind.value,
                        reason=health.last_error,
                        consecutive_failures=health.consecutive_failures,
                        immediate=immediate,
                    )
                health.state = CircuitState.OPEN
                health.opened_at = time.time()
            self._persist_locked()

    # ── rotation ────────────────────────────────────────────────────────
    def is_available(self, key_id: str) -> bool:
        """True when this credential may serve the next request."""
        with self._lock:
            health = self._health(key_id)
            if self._daily_limit and health.requests >= self._daily_limit:
                return False
            if health.state is CircuitState.CLOSED:
                return True
            if health.state is CircuitState.HALF_OPEN:
                # A probe is already in flight; do not send a second.
                return False
            if health.seconds_until_probe() <= 0:
                health.state = CircuitState.HALF_OPEN
                logger.info("provider_circuit_half_open", key_id=key_id)
                return True
            return False

    def available_keys(self, key_ids: list[str]) -> list[str]:
        return [k for k in key_ids if self.is_available(k)]

    def next_available(self, key_ids: list[str], start: int = 0) -> str | None:
        """Round-robin over healthy credentials only, starting at `start`."""
        if not key_ids:
            return None
        with self._lock:
            for offset in range(len(key_ids)):
                candidate = key_ids[(start + offset) % len(key_ids)]
                if self.is_available(candidate):
                    return candidate
        return None

    def seconds_until_any_available(self, key_ids: list[str]) -> float:
        """How long until something can serve — for an honest error message."""
        with self._lock:
            waits = []
            for key_id in key_ids:
                health = self._health(key_id)
                if self._daily_limit and health.requests >= self._daily_limit:
                    continue  # a spent daily budget does not recover on a timer
                waits.append(health.seconds_until_probe())
            return min(waits) if waits else float("inf")

    # ── reporting ───────────────────────────────────────────────────────
    def snapshot(self, key_ids: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            ids = key_ids if key_ids is not None else list(self._keys)
            keys = [self._health(k).snapshot() for k in ids]
            return {
                "date": self._today(),
                "keys": keys,
                "total_requests": sum(k["requests"] for k in keys),
                "total_tokens": sum(k["tokens"] for k in keys),
                "healthy": sum(1 for k in keys if k["state"] == "closed"),
                "open": sum(1 for k in keys if k["state"] == "open"),
            }

    def reset(self) -> None:
        with self._lock:
            self._keys.clear()
            self._persist_locked()


_registry: KeyHealthRegistry | None = None


def get_registry() -> KeyHealthRegistry:
    global _registry
    if _registry is None:
        limit_raw = os.getenv("GEMINI_RPD_LIMIT_PER_KEY", "").strip()
        _registry = KeyHealthRegistry(daily_limit=int(limit_raw) if limit_raw else None)
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None
