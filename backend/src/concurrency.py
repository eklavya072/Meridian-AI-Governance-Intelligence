"""Bounded analysis concurrency, backpressure and graceful shutdown.

The analysis worker runs in-process via FastAPI BackgroundTasks. Three
consequences that were never handled:

  * No global bound. The run endpoint returns 409 for a workspace already
    PROCESSING, but ten different workspaces start ten pipelines, each with
    its own ThreadPoolExecutor of ANALYSIS_MAX_CONCURRENCY (default 8)
    dimension workers. That is 80 concurrent LLM calls competing for a
    per-credential ceiling of ~10 requests/minute, on a host with 8GB.
  * No backpressure. Work was accepted regardless, so saturation showed up
    as everything getting slower rather than as a clear refusal — the worst
    shape for an operator, because nothing is obviously wrong.
  * No graceful shutdown. SIGTERM dropped in-flight runs with no chance to
    persist what had finished, which is what the startup orphan sweep exists
    to clean up after.

A semaphore is the whole mechanism. What matters is that it REFUSES rather
than queues: a caller that waits behind a full queue holds an HTTP
connection open until it times out, and the user learns nothing. 429 with a
retry hint is the honest answer.
"""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()

# Concurrent ANALYSES, not dimension workers. Each analysis internally runs
# up to ANALYSIS_MAX_CONCURRENCY dimension calls, so the real ceiling on
# in-flight provider requests is this times that.
MAX_CONCURRENT_ANALYSES = int(os.getenv("MAX_CONCURRENT_ANALYSES", "2"))

# How long a shutdown waits for in-flight work before abandoning it. Longer
# than a dimension call, shorter than a full run: finishing what is nearly
# done is worth waiting for, restarting a whole run is not.
SHUTDOWN_GRACE_SECONDS = float(os.getenv("SHUTDOWN_GRACE_SECONDS", "30"))


class CapacityFull(RuntimeError):
    """Every analysis slot is taken. Carries how many, so the caller can say so."""

    def __init__(self, in_flight: int, limit: int) -> None:
        self.in_flight = in_flight
        self.limit = limit
        super().__init__(f"{in_flight} of {limit} analysis slots in use. Retry shortly.")


@dataclass
class AnalysisSlots:
    """Admission control for the in-process analysis worker."""

    limit: int = MAX_CONCURRENT_ANALYSES
    _in_flight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _draining: bool = False
    _idle: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        self._idle.set()

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight

    @property
    def available(self) -> int:
        with self._lock:
            return max(self.limit - self._in_flight, 0)

    @property
    def draining(self) -> bool:
        with self._lock:
            return self._draining

    def acquire(self) -> None:
        """Take a slot, or refuse. Never blocks.

        Blocking here would hold the HTTP request open until it timed out,
        and the caller would learn nothing about why.
        """
        with self._lock:
            if self._draining:
                raise CapacityFull(self._in_flight, self.limit)
            if self._in_flight >= self.limit:
                logger.warning(
                    "analysis_capacity_full", in_flight=self._in_flight, limit=self.limit
                )
                raise CapacityFull(self._in_flight, self.limit)
            self._in_flight += 1
            self._idle.clear()

    def release(self) -> None:
        with self._lock:
            self._in_flight = max(self._in_flight - 1, 0)
            if self._in_flight == 0:
                self._idle.set()

    def begin_drain(self) -> None:
        """Stop admitting work. In-flight runs are left to finish."""
        with self._lock:
            if not self._draining:
                logger.info("analysis_draining_started", in_flight=self._in_flight)
            self._draining = True

    async def wait_for_idle(self, timeout: float = SHUTDOWN_GRACE_SECONDS) -> bool:
        """Wait for in-flight work, up to `timeout`. True if it all finished.

        Returns rather than raises on timeout: abandoning work is a
        legitimate outcome, and the startup sweep reclaims whatever was
        left. What matters is that the log says which happened.
        """
        loop = asyncio.get_running_loop()
        finished = await loop.run_in_executor(None, self._idle.wait, timeout)
        if finished:
            logger.info("analysis_drain_complete")
        else:
            logger.warning(
                "analysis_drain_timeout",
                in_flight=self.in_flight,
                timeout_seconds=timeout,
                detail="Abandoning in-flight analyses; the startup sweep will reclaim them.",
            )
        return bool(finished)

    def snapshot(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "in_flight": self._in_flight,
                "limit": self.limit,
                "available": max(self.limit - self._in_flight, 0),
                "draining": self._draining,
            }


_slots: AnalysisSlots | None = None


def get_slots() -> AnalysisSlots:
    global _slots
    if _slots is None:
        _slots = AnalysisSlots()
    return _slots


def reset_slots() -> None:
    global _slots
    _slots = None
