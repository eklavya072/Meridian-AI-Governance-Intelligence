"""The open analysis, compacted into context the Rapporteur can reason over.

The Rapporteur was given the analysis as a dict of governance gaps and nothing
else. That is enough to answer "why is Safety Partial" — the per-dimension
generator resolves the gap and reads it — but it cannot answer anything that
spans dimensions. Asked which dimension came out strongest, it replied that
the context held no evaluation or scorecard and then drifted into unrelated
material, because no part of the prompt ever carried the verdicts side by
side or the aggregate figures at all.

What is assembled here is the whole run at a glance: the eight verdicts in one
table, the two indices, the mechanism and binding counts, and the drift and
review flags. Small enough to sit in every Rapporteur prompt without pushing
latency up, complete enough that a cross-dimension question has real numbers
to stand on instead of retrieval.

Nothing is computed here. Every figure is read from what the pipeline already
stored, so the chat surface cannot invent a second answer to a question the
analysis has already settled.
"""

from __future__ import annotations

import re
from typing import Any

# Aggregate questions: ones whose answer requires seeing every dimension at
# once. The per-dimension path handles the rest and does it better, so this
# stays narrow — matching too eagerly would attach the overview to questions
# that only need one gap record.
_OVERVIEW_MARKERS = re.compile(
    r"\b("
    r"(strongest|weakest|best|worst|highest|lowest|top|biggest)\b.{0,30}"
    r"\b(dimension|area|score|result|performing|covered|gap)|"
    r"\b(dimension|area)s?\b.{0,24}\b(strongest|weakest|best|worst|highest|lowest)|"
    r"(overall|overview|summary|summarise|summarize|in general|across (the )?dimensions|"
    r"compare the dimensions|which dimensions?)|"
    r"how (many|much) .{0,24}(covered|partial|missing|dimensions)|"
    r"(coverage index|maturity index|binding share|binding force|overall (score|result|picture))|"
    r"(what|where) .{0,24}(are|is) the (main|biggest|key) (gap|gaps|weakness|weaknesses|risk|risks)|"
    r"(rank|order) the dimensions|"
    r"(this|the) (analysis|run|assessment|result)s?\b.{0,30}(say|show|tell|mean|about)"
    r")",
    re.IGNORECASE,
)


def is_analysis_overview_question(message: str) -> bool:
    text = (message or "").strip()
    return bool(text and _OVERVIEW_MARKERS.search(text))


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None or value == "":
        return "n/a"
    return f"{value}{suffix}"


def _dimension_row(gap: dict[str, Any]) -> str:
    """One dimension, one line — verdict, stage, risk and the counts behind it.

    Ordered so the answer to "why" is on the same line as the verdict: a
    reader (or the model) should never have to hold two rows in mind to see
    that a dimension is Partial because nothing in it is binding.
    """
    m1 = gap.get("module_1") if isinstance(gap.get("module_1"), dict) else {}
    m2 = gap.get("module_2") if isinstance(gap.get("module_2"), dict) else {}
    present = gap.get("mechanisms_present") or {}
    absent = gap.get("mechanisms_absent") or []
    binding = sum(1 for tier in present.values() if isinstance(tier, int) and tier >= 3)

    parts = [
        f"{gap.get('dimension', '?')}: {_fmt(gap.get('coverage'))}",
        f"stage {_fmt(m1.get('governance_maturity') or gap.get('governance_maturity'))}",
        f"risk {_fmt(gap.get('risk_level'))}",
    ]
    if present or absent:
        parts.append(
            f"mechanisms {len(present)} present ({binding} binding), {len(absent)} absent"
        )
    if m2.get("priority"):
        parts.append(f"priority {m2['priority']}")
    line = "  • " + " | ".join(parts)

    basis = gap.get("risk_basis") or m1.get("coverage_reasoning") or gap.get("coverage_reasoning")
    if basis:
        line += f"\n      basis: {str(basis)[:260]}"
    if present:
        named = ", ".join(f"{k} (T{v})" for k, v in list(present.items())[:6])
        line += f"\n      present: {named}"
    if absent:
        line += f"\n      absent: {', '.join(str(a) for a in absent[:6])}"
    return line


def build_analysis_overview_context(analysis_results: dict[str, Any] | None) -> str:
    """Every dimension of the open run, plus the aggregates, as prompt context."""
    if not analysis_results:
        return ""
    gaps = analysis_results.get("gaps") or {}
    if not gaps:
        return ""

    analytics = analysis_results.get("decision_analytics") or {}
    lines: list[str] = ["--- The Analysis Currently Open (verdicts already computed) ---", ""]

    label_bits = [
        analysis_results.get("country"),
        analysis_results.get("policy_title"),
    ]
    label = " — ".join(b for b in label_bits if b)
    if label:
        lines.append(f"Assessment: {label}")
    documents = analysis_results.get("documents") or []
    if documents:
        lines.append(f"Documents evaluated in this run: {', '.join(str(d) for d in documents)}")
    if label or documents:
        lines.append("")

    if analytics:
        lines.append(
            "Aggregates: "
            f"{_fmt(analytics.get('covered'))} Covered, "
            f"{_fmt(analytics.get('partial'))} Partial, "
            f"{_fmt(analytics.get('missing'))} Missing"
            + (
                f", {analytics['analysis_failed']} not assessed"
                if analytics.get("analysis_failed")
                else ""
            )
        )
        lines.append(
            f"Coverage index {_fmt(analytics.get('coverage_index'))} "
            f"(breadth: {_fmt(analytics.get('mechanisms_met'))} of "
            f"{_fmt(analytics.get('mechanisms_total'))} mechanisms addressed). "
            f"Binding force / maturity index {_fmt(analytics.get('maturity_index'))}. "
            f"Binding share {_fmt(analytics.get('binding_share'), '%')} "
            f"({_fmt(analytics.get('mechanisms_binding'))} of the present mechanisms "
            "are carried by an actual duty)."
        )
        if analytics.get("strongest_dimension"):
            lines.append(f"Strongest dimension as computed: {analytics['strongest_dimension']}.")
        if analytics.get("highest_priority_dimensions"):
            lines.append(
                "Highest-priority dimensions: "
                + ", ".join(analytics["highest_priority_dimensions"])
            )
        dist = analytics.get("maturity_distribution") or {}
        if dist:
            lines.append(
                "Stage distribution: "
                + ", ".join(f"{k} {v}" for k, v in dist.items() if v)
            )
        if analytics.get("average_confidence") is not None:
            lines.append(f"Mean confidence across dimensions: {analytics['average_confidence']}.")
        # Flags worth volunteering rather than hiding — a reader asking about
        # a verdict deserves to know it was reconciled or held for review.
        if analytics.get("synthesis_drift_downgraded"):
            lines.append(
                "Downgraded after synthesis drift check: "
                + ", ".join(analytics["synthesis_drift_downgraded"])
            )
        if analytics.get("ladder_raise_review"):
            lines.append(
                "Flagged for ladder-raise review: "
                + ", ".join(analytics["ladder_raise_review"])
            )
        lines.append("")

    lines.append("Per dimension:")
    for gap in gaps.values():
        if isinstance(gap, dict):
            lines.append(_dimension_row(gap))
    lines.append("")
    lines.append(
        "Use these stored verdicts as the source of truth — they are what the "
        "analysis actually computed. Do not recompute a verdict, soften one, or "
        "assert a figure that is not above."
    )
    return "\n".join(lines)
