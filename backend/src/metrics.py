"""Prometheus metrics — the RED signals, plus the ones specific to Meridian.

Request rate, error rate and latency are table stakes and say nothing about
whether this system is doing its job. The metrics that matter here are the
ones that would catch a silent quality regression: a run that completes but
cites chunks that no longer resolve, a dimension whose verdicts suddenly all
move one way, an ingestion that indexes a fraction of the chunks it used to.
Those failures never raise; they just quietly make the output wrong, which is
exactly the failure mode this instrument cannot afford.

Everything is registered on the default registry and exposed by `/metrics`.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any

import structlog
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

logger = structlog.get_logger()


# ── Pipeline throughput ───────────────────────────────────────────────────
analysis_runs = Counter(
    "meridian_analysis_runs_total",
    "Analysis runs by terminal outcome.",
    ["outcome"],
)

documents_ingested = Counter(
    "meridian_documents_ingested_total",
    "Documents ingested by outcome.",
    ["outcome"],
)

chunks_indexed = Counter(
    "meridian_chunks_indexed_total",
    "Chunks written to the vector store.",
)

# Stage duration rather than request duration: a run is a background task, so
# request latency says nothing about where the time actually goes.
stage_seconds = Histogram(
    "meridian_stage_duration_seconds",
    "Wall-clock seconds per pipeline stage.",
    ["stage"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),
)


# ── Output quality ────────────────────────────────────────────────────────
# The verdict distribution is the cheapest available regression alarm: if a
# code change moves every dimension one way at once, it shows here before
# anybody reads a brief.
coverage_verdicts = Counter(
    "meridian_coverage_verdicts_total",
    "Coverage verdicts by dimension.",
    ["verdict", "dimension"],
)

citations_checked = Counter(
    "meridian_citations_checked_total",
    "Citation verification outcomes, by dimension where known.",
    ["result", "dimension"],
)

citation_pass_rate = Gauge(
    "meridian_citation_pass_rate",
    "Share of citations that passed verification on the most recent run.",
)


# ── Provider health ───────────────────────────────────────────────────────
provider_failover = Counter(
    "meridian_provider_failover_total",
    "Provider failover events by kind.",
    ["event"],
)

provider_keys_healthy = Gauge(
    "meridian_provider_keys_healthy",
    "API keys currently considered healthy.",
)

provider_quota_remaining = Gauge(
    "meridian_provider_quota_remaining",
    "Requests remaining in the current provider quota window.",
)


@contextmanager
def timed_stage(stage: str):
    """Record how long a pipeline stage took.

    Observes on the way out even when the stage raises — a stage that fails
    after four minutes is exactly the one worth seeing in the histogram, and
    swallowing its timing would hide the slowest failures.
    """
    started = time.monotonic()
    try:
        yield
    finally:
        stage_seconds.labels(stage=stage).observe(time.monotonic() - started)


def record_citation_results(
    results: Iterable[dict[str, Any]], dimension: str = "all"
) -> None:
    """Count verification outcomes and refresh the pass-rate gauge.

    Takes the verified-evidence dicts produced by
    `verify.verify_gap_analysis_citations`, each carrying a `verified` bool.
    """
    passed = failed = 0
    for r in results or []:
        if r.get("verified"):
            passed += 1
        else:
            failed += 1
    if passed:
        citations_checked.labels(result="verified", dimension=dimension).inc(passed)
    if failed:
        citations_checked.labels(result="rejected", dimension=dimension).inc(failed)
    total = passed + failed
    if total:
        citation_pass_rate.set(passed / total)


def refresh_provider_gauges(healthy: int | None = None, quota_remaining: int | None = None) -> None:
    """Point-in-time provider state, refreshed on scrape rather than on every
    call — the values are cheap to read and there is no reason to pay for the
    update on a hot path nobody is scraping."""
    if healthy is not None:
        provider_keys_healthy.set(healthy)
    if quota_remaining is not None:
        provider_quota_remaining.set(quota_remaining)


def render() -> tuple[bytes, str]:
    """Exposition payload and its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
