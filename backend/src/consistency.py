from __future__ import annotations

import re
import structlog
from typing import Any

from src.models import CoverageLevel, DimensionGraph, GovernanceGap, RiskLevel

logger = structlog.get_logger()

# ── Fully Covered tier: framework-synthesis drift safeguard ───────────────
# A Covered dimension's framework_synthesis must justify compliance from the
# document's own evidence in present tense. Gap-filling / recommendation
# phrasing ("should establish", "would strengthen", "recommend"...) signals
# that the tier classification and the generated content have drifted apart.
# Strong signals auto-downgrade the dimension to Partial for review (code,
# never LLM judgment); weaker signals are flagged in logs and the consistency
# report.

# Weight 3: unambiguous imperative / recommendation phrasing (exact phrases).
_COVERED_SYNTHESIS_STRONG_PHRASES: tuple[str, ...] = (
    "should implement",
    "should establish",
    "should adopt",
    "should create",
    "should introduce",
    "should develop",
    "should require",
    "would strengthen",
    "would translate",
    "would close",
    "would address",
    "will strengthen",
    "will translate",
    "recommend that",
    "it is recommended",
    "we recommend",
    "in order to",
    "bridge the gap",
    "close the gap",
    "needs to",
    # The model's OWN admission that coverage is not substantive is the
    # strongest drift signal of all — the Branch A prompt explicitly instructs
    # it to state this when it cannot ground compliance, and it means the
    # Covered verdict is likely wrong (should be Partial).
    "does not substantively",
)

# Weight 1: softer gap-indicating vocabulary (word-bounded, so "recommend"
# does not match "recommendation" or "recommending").
_COVERED_SYNTHESIS_SOFT_RE = re.compile(
    r"\b(should|would|recommend|lacks|missing|gap|shortfall|deficit)\b",
    re.IGNORECASE,
)

# Weight 1: multi-word gap-negative phrases. These are the EXACT honesty path
# the Branch A prompt instructs the model to emit when it cannot ground
# compliance ("state plainly which principle the document does not
# substantively satisfy... will be surfaced for review"). Without them, an
# honest Covered synthesis that says "the document does not address X" would
# score 0 and the promised review surfacing would never fire.
#
# NOTE: deliberately NOT prefix-nested ("does not provide" etc. are substrings
# of "does not" and would double-count the score).
_COVERED_SYNTHESIS_SOFT_PHRASES: tuple[str, ...] = (
    "does not",
    "not substantively",
    "fails to",
    "insufficient",
    "no provisions",
)

# Auto-downgrade when the weighted score reaches this threshold.
# e.g. "should establish" alone (3) downgrades; a lone "lacks" (1) flags only.
COVERED_SYNTHESIS_DOWNGRADE_THRESHOLD = 3


def detect_covered_synthesis_drift(synthesis: str) -> tuple[int, list[str]]:
    """Score a Covered-tier framework_synthesis for gap-filling language.

    Returns (weighted_score, matched_phrases). (0, []) means the synthesis is
    clean compliance-justification language. Score >= threshold is a strong
    drift signal (auto-downgrade); score > 0 is a weak signal (flag only).
    """
    if not synthesis:
        return 0, []
    lower = synthesis.lower()
    score = 0
    matched: list[str] = []
    for phrase in _COVERED_SYNTHESIS_STRONG_PHRASES:
        if phrase in lower:
            score += 3
            matched.append(phrase)
    for m in _COVERED_SYNTHESIS_SOFT_RE.finditer(lower):
        score += 1
        matched.append(m.group(1))
    for phrase in _COVERED_SYNTHESIS_SOFT_PHRASES:
        if phrase in lower:
            score += 1
            matched.append(phrase)
    seen: set[str] = set()
    dedup: list[str] = []
    for p in matched:
        if p not in seen:
            seen.add(p)
            dedup.append(p)
    return score, dedup


def build_governance_dimension_graph() -> DimensionGraph:
    g = DimensionGraph()

    g.add_relationship("Governance", "Accountability", "subsumes")
    g.add_relationship("Accountability", "Human Oversight", "requires")
    g.add_relationship("Human Oversight", "Transparency", "requires")
    g.add_relationship("Transparency", "Explainability", "subsumes")
    g.add_relationship("Explainability", "Auditability", "requires")
    g.add_relationship("Risk Management", "Impact Assessment", "subsumes")
    g.add_relationship("Risk Management", "Safety", "requires")
    g.add_relationship("Safety", "Robustness", "subsumes")
    g.add_relationship("Privacy", "Data Protection", "subsumes")
    g.add_relationship("Data Protection", "Anonymization", "requires")
    g.add_relationship("Fairness", "Non-discrimination", "subsumes")
    g.add_relationship("Inclusivity", "Accessibility", "subsumes")
    g.add_relationship("Inclusivity", "Equity", "requires")
    g.add_relationship("Accountability", "Liability", "subsumes")
    g.add_relationship("Ethics", "Human Rights", "subsumes")
    g.add_relationship("Ethics", "Inclusivity", "requires")
    g.add_relationship("Governance", "Risk Management", "requires")

    return g


RISK_COVERAGE_MAP: dict[CoverageLevel, list[RiskLevel]] = {
    CoverageLevel.COVERED: [RiskLevel.LOW],
    CoverageLevel.PARTIAL: [RiskLevel.LOW, RiskLevel.MEDIUM],
    CoverageLevel.MISSING: [RiskLevel.MEDIUM, RiskLevel.HIGH],
}


GOVERNANCE_GRAPH = build_governance_dimension_graph()


class ConsistencyViolation:
    def __init__(
        self,
        dimension: str,
        violation_type: str,
        description: str,
        severity: str = "warning",
        suggestion: str = "",
    ):
        self.dimension = dimension
        self.violation_type = violation_type
        self.description = description
        self.severity = severity
        self.suggestion = suggestion

    def to_dict(self) -> dict[str, str]:
        return {
            "dimension": self.dimension,
            "violation_type": self.violation_type,
            "description": self.description,
            "severity": self.severity,
            "suggestion": self.suggestion,
        }


class ConsistencyReport:
    def __init__(self, violations: list[ConsistencyViolation]):
        self.violations = violations
        self.passed = len(violations) == 0
        self.score = max(0.0, 1.0 - (len(violations) * 0.15))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
        }


SUBSET_DIMENSIONS: dict[str, set[str]] = {
    "Transparency": {"Explainability"},
    "Privacy": {"Data Protection", "Anonymization"},
    "Inclusivity": {"Accessibility", "Non-discrimination"},
    "Risk Management": {"Safety", "Impact Assessment"},
    "Accountability": {"Liability", "Oversight"},
    "Fairness": {"Non-discrimination"},
}


class ConsistencyValidator:
    def __init__(self):
        self.dimension_graph = GOVERNANCE_GRAPH

    def validate(
        self,
        gaps: list[GovernanceGap],
        doc_chunks_per_dimension: dict[str, int] | None = None,
    ) -> ConsistencyReport:
        violations: list[ConsistencyViolation] = []
        gap_by_dim = {g.dimension: g for g in gaps}

        violations.extend(self._check_subset_consistency(gap_by_dim))
        violations.extend(self._check_risk_coherence(gaps))
        violations.extend(self._check_evidence_sufficiency(gaps, doc_chunks_per_dimension))
        violations.extend(self._check_framework_synthesis_quality(gap_by_dim))
        violations.extend(self._check_covered_synthesis_drift(gap_by_dim))
        violations.extend(self._check_graph_consistency(gap_by_dim))

        if not violations:
            logger.info("consistency_check_passed", dimensions=len(gaps))
        else:
            logger.info(
                "consistency_check_violations",
                count=len(violations),
                violations=[v.violation_type for v in violations],
            )

        return ConsistencyReport(violations)

    def _check_subset_consistency(
        self, gap_by_dim: dict[str, GovernanceGap]
    ) -> list[ConsistencyViolation]:
        violations: list[ConsistencyViolation] = []

        for parent_dim, child_keywords in SUBSET_DIMENSIONS.items():
            parent_gap = gap_by_dim.get(parent_dim)
            if parent_gap is None:
                continue

            if parent_gap.coverage == CoverageLevel.COVERED:
                continue

            for child_keyword in child_keywords:
                child_gap = gap_by_dim.get(child_keyword)
                if child_gap is not None:
                    if child_gap.coverage == CoverageLevel.COVERED and parent_gap.coverage in (
                        CoverageLevel.MISSING, CoverageLevel.PARTIAL
                    ):
                        violations.append(ConsistencyViolation(
                            dimension=parent_dim,
                            violation_type="subset_inconsistency",
                            description=(
                                f"'{child_keyword}' is {child_gap.coverage.value} "
                                f"but its parent dimension '{parent_dim}' is {parent_gap.coverage.value}. "
                                f"'{child_keyword}' is conceptually part of '{parent_dim}'."
                            ),
                            severity="error",
                            suggestion=(
                                f"Review whether '{parent_dim}' coverage should be elevated "
                                f"since '{child_keyword}' is addressed."
                            ),
                        ))

        for parent_dim, child_keywords in SUBSET_DIMENSIONS.items():
            parent_gap = gap_by_dim.get(parent_dim)
            if parent_gap is None:
                continue

            if parent_gap.coverage == CoverageLevel.COVERED:
                all_children_covered = True
                for child_keyword in child_keywords:
                    child_gap = gap_by_dim.get(child_keyword)
                    if child_gap is not None and child_gap.coverage != CoverageLevel.COVERED:
                        all_children_covered = False

                if not all_children_covered:
                    missing_children = [
                        ck for ck in child_keywords
                        if gap_by_dim.get(ck) and gap_by_dim[ck].coverage != CoverageLevel.COVERED
                    ]
                    violations.append(ConsistencyViolation(
                        dimension=parent_dim,
                        violation_type="missing_sub_elements",
                        description=(
                            f"'{parent_dim}' is {parent_gap.coverage.value} but sub-elements "
                            f"{missing_children} are not. Coverage may be overestimated."
                        ),
                        severity="warning",
                        suggestion=(
                            f"Ensure sub-elements {missing_children} reflect the parent dimension coverage."
                        ),
                    ))

        return violations

    def _check_graph_consistency(
        self, gap_by_dim: dict[str, GovernanceGap]
    ) -> list[ConsistencyViolation]:
        violations: list[ConsistencyViolation] = []

        processed_pairs: set[tuple[str, str]] = set()

        for dim_name, gap in gap_by_dim.items():
            node = self.dimension_graph.nodes.get(dim_name)
            if node is None:
                continue

            for child in node.children:
                child_gap = gap_by_dim.get(child)
                if child_gap is None:
                    continue
                pair = (dim_name, child)
                if pair in processed_pairs:
                    continue
                processed_pairs.add(pair)

                if gap.coverage == CoverageLevel.COVERED and child_gap.coverage != CoverageLevel.COVERED:
                    desc = self.dimension_graph.nodes.get(dim_name)
                    child_desc = self.dimension_graph.nodes.get(child)
                    violations.append(ConsistencyViolation(
                        dimension=dim_name,
                        violation_type="graph_child_not_covered",
                        description=(
                            f"'{dim_name}' is {gap.coverage.value} but child dimension "
                            f"'{child}' is {child_gap.coverage.value}. "
                        ),
                        severity="warning",
                        suggestion=(
                            f"Review if '{child}' coverage should be elevated "
                            f"to match parent '{dim_name}'."
                        ),
                    ))

            for parent in node.parents:
                parent_gap = gap_by_dim.get(parent)
                if parent_gap is None:
                    continue
                pair = (parent, dim_name)
                if pair in processed_pairs:
                    continue
                processed_pairs.add(pair)

                if gap.coverage == CoverageLevel.COVERED and parent_gap.coverage in (
                    CoverageLevel.MISSING, CoverageLevel.PARTIAL
                ):
                    violations.append(ConsistencyViolation(
                        dimension=dim_name,
                        violation_type="graph_child_covered_but_parent_missing",
                        description=(
                            f"'{dim_name}' is {gap.coverage.value} but parent dimension "
                            f"'{parent}' is {parent_gap.coverage.value}. "
                            f"A child dimension cannot be covered if the parent is not."
                        ),
                        severity="error",
                        suggestion=(
                            f"Review '{parent}' coverage — it may need to be elevated."
                        ),
                    ))

            for required in node.requires:
                req_gap = gap_by_dim.get(required)
                if req_gap is None:
                    continue
                pair = (dim_name, required)
                if pair in processed_pairs:
                    continue
                processed_pairs.add(pair)

                if gap.coverage == CoverageLevel.COVERED and req_gap.coverage == CoverageLevel.MISSING:
                    violations.append(ConsistencyViolation(
                        dimension=dim_name,
                        violation_type="missing_required_dimension",
                        description=(
                            f"'{dim_name}' is {gap.coverage.value} but requires "
                            f"'{required}' which is {req_gap.coverage.value}. "
                        ),
                        severity="error",
                        suggestion=(
                            f"'{dim_name}' depends on '{required}'. "
                            f"Address coverage for '{required}' first."
                        ),
                    ))

        return violations

    def _check_risk_coherence(
        self, gaps: list[GovernanceGap]
    ) -> list[ConsistencyViolation]:
        violations: list[ConsistencyViolation] = []

        for g in gaps:
            if g.coverage in (CoverageLevel.INSUFFICIENT_EVIDENCE, CoverageLevel.COVERED):
                continue
            allowed_risks = RISK_COVERAGE_MAP.get(g.coverage, [])
            if allowed_risks and g.risk_level not in allowed_risks:
                violations.append(ConsistencyViolation(
                    dimension=g.dimension,
                    violation_type="risk_coverage_mismatch",
                    description=(
                        f"Coverage is '{g.coverage.value}' but risk is '{g.risk_level.value}'. "
                        f"Expected one of: {[r.value for r in allowed_risks]}"
                    ),
                    severity="error",
                    suggestion=(
                        f"Adjust risk level for '{g.dimension}' from {g.risk_level.value} "
                        f"to match coverage level {g.coverage.value}."
                    ),
                ))

        return violations

    def _check_evidence_sufficiency(
        self,
        gaps: list[GovernanceGap],
        doc_chunks_per_dimension: dict[str, int] | None,
    ) -> list[ConsistencyViolation]:
        violations: list[ConsistencyViolation] = []

        for g in gaps:
            if g.coverage == CoverageLevel.INSUFFICIENT_EVIDENCE:
                continue

            n_evidence = len(g.evidence)
            if n_evidence == 0:
                violations.append(ConsistencyViolation(
                    dimension=g.dimension,
                    violation_type="missing_evidence",
                    description=(
                        f"Dimension '{g.dimension}' has coverage '{g.coverage.value}' "
                        f"but zero evidence items."
                    ),
                    severity="error",
                    suggestion="Re-run retrieval for this dimension or check ChromaDB state.",
                ))
                continue

            fw_items = [e for e in g.evidence if e.source_framework != "unknown"]
            if g.coverage in (CoverageLevel.MISSING, CoverageLevel.PARTIAL) and not fw_items:
                violations.append(ConsistencyViolation(
                    dimension=g.dimension,
                    violation_type="missing_framework_evidence",
                    description=(
                        f"Dimension '{g.dimension}' is '{g.coverage.value}' "
                        f"but has no framework-level evidence to support gap analysis."
                    ),
                    severity="warning",
                    suggestion=(
                        "Framework retrieval returned no results for this dimension. "
                        "Consider expanding the retrieval query."
                    ),
                ))

            if g.framework_positions and g.recommendation in ("", "No recommendation provided."):
                violations.append(ConsistencyViolation(
                    dimension=g.dimension,
                    violation_type="recommendation_missing",
                    description=(
                        f"Framework positions exist but recommendation is empty "
                        f"for '{g.dimension}'."
                    ),
                    severity="warning",
                    suggestion="LLM should generate a recommendation when framework positions are available.",
                ))

        if doc_chunks_per_dimension:
            for dim, count in doc_chunks_per_dimension.items():
                if count == 0:
                    g = next((x for x in gaps if x.dimension == dim), None)
                    if g and g.coverage != CoverageLevel.INSUFFICIENT_EVIDENCE:
                        violations.append(ConsistencyViolation(
                            dimension=dim,
                            violation_type="zero_doc_retrieval",
                            description=(
                                f"No document chunks retrieved for '{dim}' "
                                f"but coverage is '{g.coverage.value if g else 'N/A'}'."
                            ),
                            severity="warning",
                            suggestion="Increase doc_retrieve_k or check document chunking quality.",
                        ))

        return violations

    def _check_covered_synthesis_drift(
        self, gap_by_dim: dict[str, GovernanceGap]
    ) -> list[ConsistencyViolation]:
        """Safeguard: a Fully Covered dimension whose own framework_synthesis
        uses gap-filling / recommendation language has drifted from its tier.

        This is a warning (flag for review) — the auto-downgrade to Partial
        happens earlier in the pipeline (gap_analyzer) on strong signals; this
        check catches residual weak signals on any Covered gap that survives.
        """
        violations: list[ConsistencyViolation] = []

        for dim, gap in gap_by_dim.items():
            if gap.coverage != CoverageLevel.COVERED:
                continue
            # Scan only the overall-assessment part of a structured Covered
            # synthesis (the compliance justification). The Consensus /
            # Differences sections describe the external frameworks, where
            # words like "lacks" or "requires" legitimately describe
            # framework positions, not the policy — gap-filling language in
            # the overall assessment is the true tier/content drift signal.
            synthesis = (
                (gap.module_2.framework_synthesis_overall_assessment
                 if gap.module_2 else "")
                or gap.framework_synthesis
                or ""
            )
            if not synthesis:
                continue
            score, phrases = detect_covered_synthesis_drift(synthesis)
            if score <= 0:
                continue
            violations.append(ConsistencyViolation(
                dimension=dim,
                violation_type="covered_synthesis_drift",
                description=(
                    f"'{dim}' is Covered but its framework synthesis uses "
                    f"gap-filling/recommendation language ({', '.join(phrases[:5])}) — "
                    "the tier classification and the generated content have "
                    "drifted apart. The verdict may overstate compliance."
                ),
                severity="warning",
                suggestion=(
                    "Review whether this dimension should be Partial, and "
                    "re-run the analysis after fixing the Module 2 prompt "
                    "(framework_synthesis must justify compliance from document "
                    "evidence, not recommend future action)."
                ),
            ))

        return violations

    def _check_framework_synthesis_quality(
        self, gap_by_dim: dict[str, GovernanceGap]
    ) -> list[ConsistencyViolation]:
        violations: list[ConsistencyViolation] = []

        for dim, gap in gap_by_dim.items():
            if gap.framework_synthesis and gap.framework_synthesis == gap.recommendation:
                violations.append(ConsistencyViolation(
                    dimension=dim,
                    violation_type="synthesis_recommendation_collision",
                    description=(
                        f"Framework synthesis and recommendation are identical for '{dim}'."
                    ),
                    severity="warning",
                    suggestion="Ensure framework synthesis compares requirements vs document, "
                               "while recommendation suggests actions.",
                ))

        return violations
