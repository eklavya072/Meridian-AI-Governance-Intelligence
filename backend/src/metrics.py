"""Prometheus metrics — the RED signals, plus the ones specific to Meridian.

Request rate, error rate and latency are table stakes and say nothing about
whether this system is doing its job. The metrics that matter here are the
ones that would catch a silent quality regression:

  * citations verified vs rejected — the evidence gate's own pass rate. If a
    prompt change starts producing citations that no longer resolve, this
    moves before anyone reads a brief.
  * coverage-ladder verdict distribution — the deterministic stage. Its
    output should only change when the code or the document changes, so a
    shift with neither is a bug.
  * provider failover events — circuit opens, key rotations, capacity
    exhaustion. Quota problems are the most common operational failure and
    were previously visible only as `print()` on stdout.

Everything is labelled by dimension where a dimension exists, because "the
citation pass rate dropped" is a much weaker signal than "the citation pass
rate dropped on Environmental Sustainability".
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# A dedicated registry rather than the global default: the default collects
# process and GC collectors from every import site, and tests that assert on
# counter values want a surface they control.
REGISTRY = CollectorRegistry()


# ── Pipeline ────────────────────────────────────────────────────────────
analysis_runs = Counter(
    "meridian_analysis_runs_total",
    "Analysis pipeline runs, by outcome.",
    ["outcome"],
    registry=REGISTRY,
)

# Buckets go out to 30 minutes: a full run is up to 16 LLM calls against a
# rate-limited free tier, so the default Prometheus buckets (max 10s) would
# put every single run in +Inf and tell us nothing.
stage_duration = Histogram(
    "meridian_stage_duration_seconds",
    "Wall-clock duration of one pipeline stage.",
    ["stage"],
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800),
    registry=REGISTRY,
)

documents_ingested = Counter(
    "meridian_documents_ingested_total",
    "Documents ingested, by outcome.",
    ["outcome"],
    registry=REGISTRY,
)

chunks_indexed = Counter(
    "meridian_chunks_indexed_total",
    "Chunks written to the vector store.",
    registry=REGISTRY,
)


# ── The evidence gate ───────────────────────────────────────────────────
citations_checked = Counter(
    "meridian_citations_checked_total",
    "Citations put through verification, by result.",
    ["result", "dimension"],
    registry=REGISTRY,
)

citation_pass_rate = Gauge(
    "meridian_citation_pass_rate",
    "Share of citations that passed verification in the most recent run.",
    registry=REGISTRY,
)

coverage_verdicts = Counter(
    "meridian_coverage_verdicts_total",
    "Deterministic coverage-ladder verdicts, by dimension.",
    ["verdict", "dimension"],
    registry=REGISTRY,
)


# ── Provider ────────────────────────────────────────────────────────────
provider_requests = Counter(
    "meridian_provider_requests_total",
    "Provider calls, by outcome. 'terminal' means retrying cannot help.",
    ["provider", "outcome"],
    registry=REGISTRY,
)

provider_latency = Histogram(
    "meridian_provider_latency_seconds",
    "Latency of a single provider call.",
    ["provider"],
    buckets=(0.5, 1, 2, 5, 10, 20, 40, 80, 160),
    registry=REGISTRY,
)

provider_failover = Counter(
    "meridian_provider_failover_total",
    "Failover events, by kind: key_rotation, circuit_open, capacity_exhausted.",
    ["event"],
    registry=REGISTRY,
)

provider_keys_healthy = Gauge(
    "meridian_provider_keys_healthy",
    "Credentials the circuit breaker currently trusts.",
    registry=REGISTRY,
)

provider_quota_remaining = Gauge(
    "meridian_provider_quota_remaining",
    "Requests left in the daily budget.",
    registry=REGISTRY,
)


# ── Uploads ─────────────────────────────────────────────────────────────
uploads_rejected = Counter(
    "meridian_uploads_rejected_total",
    "Uploads refused at validation, by reason.",
    ["reason"],
    registry=REGISTRY,
)


@contextmanager
def timed_stage(stage: str) -> Iterator[None]:
    """Record how long one named pipeline stage took.

    Used around validate / chunk / embed / retrieve / evaluate / verify /
    synthesise / export, so the histogram answers which stage dominates a
    run rather than only how long the whole thing took.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        stage_duration.labels(stage=stage).observe(time.perf_counter() - start)


def record_citation_results(results: list[dict], dimension: str = "all") -> None:
    """Fold one dimension's verification results into the counters."""
    passed = sum(1 for r in results if r.get("verified"))
    failed = len(results) - passed
    if passed:
        citations_checked.labels(result="verified", dimension=dimension).inc(passed)
    if failed:
        citations_checked.labels(result="rejected", dimension=dimension).inc(failed)
    if results:
        citation_pass_rate.set(passed / len(results))


def refresh_provider_gauges(healthy: int, quota_remaining: int) -> None:
    provider_keys_healthy.set(healthy)
    provider_quota_remaining.set(quota_remaining)


def render() -> tuple[bytes, str]:
    """The exposition payload and its content type."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
