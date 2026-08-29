from __future__ import annotations

import re
from typing import Any

import structlog

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

# Weight 3: the general "would/will VERB ... into ..." construction — e.g.
# "would transform these commitments into enforceable safeguards" or "will
# convert this high-level commitment into an actionable framework". This is
# the same gap-filling template as the enumerated STRONG_PHRASES above
# ("would strengthen", "will translate", ...), just with a different verb.
# Confirmed live: two real Covered verdicts (EU Inclusivity, Kenya
# Environmental Sustainability) used this exact template with paraphrased
# verbs ("transform", "convert") that the hand-picked phrase list didn't
# cover, so each scored only 1 point (the generic "would"/"lacks" soft hit)
# instead of the 3 needed to trigger the auto-downgrade — the safeguard
# correctly fires on "would strengthen" but was blind to any other verb
# filling the same "turn a principle into a mechanism" role. A regex on the
# construction itself, not the specific verb, closes that gap.
_COVERED_SYNTHESIS_TRANSFORM_RE = re.compile(
    r"\b(?:would|will)\s+[\w-]+(?:\s+[\w-]+){0,5}\s+into\b",
    re.IGNORECASE,
)

# Weight 3: "transition/move/shift from [current state] to [target state]" —
# a distinct gap-filling idiom from the "would/will ... into" one above, but
# the same underlying tell: describing where the document should GO, not
# where it already IS. Confirmed live: India's Accountability synthesis used
# "must transition from directional proposals to concrete enforcement
# rules" — no would/will/should present at all, so it scored 0 under every
# other check and shipped as an unflagged "Covered" verdict.
_COVERED_SYNTHESIS_FROM_TO_RE = re.compile(
    r"\b(?:transition|move|shift|evolve|progress)(?:s|ing|ed)?\s+from\b[^.]{0,80}?\bto\b",
    re.IGNORECASE,
)

# Weight 1: softer gap-indicating vocabulary (word-bounded, so "recommend"
# does not match "recommendation" or "recommending"). "must" is included
# here (not as a standalone strong phrase) because it is common in
# legitimate present-tense descriptions of a document's OWN requirements
# ("the policy states operators must report annually") — a soft weight lets
# it contribute to a downgrade alongside other signals without being a
# strong signal entirely on its own.
_COVERED_SYNTHESIS_SOFT_RE = re.compile(
    r"\b(should|would|must|recommend|lacks|missing|gap|shortfall|deficit)\b",
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
    transform_match = _COVERED_SYNTHESIS_TRANSFORM_RE.search(lower)
    if transform_match:
        score += 3
        matched.append(transform_match.group(0))
    from_to_match = _COVERED_SYNTHESIS_FROM_TO_RE.search(lower)
    if from_to_match:
        score += 3
        matched.append(from_to_match.group(0))
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


# ── Ladder-raise review safeguard ────────────────────────────────────────
# The deterministic coverage ladder (R1 floor, R2 raise) can override the
# LLM's raw verdict (Missing → Partial, Partial → Covered). When such a
# raise produces a final verdict that contradicts the model's OWN
# coverage_reasoning — the reasoning lists explicit gaps ("does not
# establish", "no provisions", "lacks") yet the raised verdict says
# Covered — the mismatch must be flagged for review rather than shipped
# silently. This is the same review discipline as the synthesis-drift
# safeguard above, applied to the ladder's OWN override instead of LLM
# output.

# Weight 3: unambiguous gap assertions — the model's own admission that the
# document lacks the very mechanisms a raised verdict claims.
_LADDER_RAISE_GAP_PHRASES: tuple[str, ...] = (
    "does not establish",
    "does not provide",
    "does not address",
    "does not contain",
    "does not set out",
    "does not specify",
    "does not include",
    "does not define",
    "does not cover",
    "does not require",
    "does not mention",
    "does not create",
    "does not introduce",
    "never mentions",
    "makes no mention",
    "no provisions",
    "no mention of",
    "no mechanism",
    "no requirement",
    "no obligation",
    "no reference",
    "no evidence",
    "no language",
    "no framework",
    "nowhere",
    "lacks",
    "lacking",
    "fails to",
    "absent",
    "omits",
    "is silent",
    "not addressed",
    "no coverage",
    # Explicit-absence constructions with the object AFTER the negator
    # ("provides no concrete operational mechanisms", "establishes no
    # liability framework", "contains no privacy provisions", "sets out
    # no redress pathway"). The "does not provide" family only catches
    # subject-verb-negator order; a raised verdict paired with "provides
    # no…" reasoning is the same contradiction and must flag too.
    "provides no",
    "provides neither",
    "offers no",
    "gives no",
    "sets out no",
    "lays down no",
    "establishes no",
    "creates no",
    "introduces no",
    "contains no",
    "includes no",
    "specifies no",
    "defines no",
    "mentions no",
    "requires no",
    "mandates no",
    "imposes no",
)

# Weight 1: softer gap vocabulary (word-bounded).
_LADDER_RAISE_GAP_SOFT_RE = re.compile(r"\b(missing|gap|insufficient|deficient)\b", re.IGNORECASE)

# Flag for review when the weighted score reaches this threshold — a single
# strong gap assertion ("does not establish") is enough.
LADDER_RAISE_REVIEW_THRESHOLD = 3


def detect_ladder_raise_contradiction(reasoning: str) -> tuple[int, list[str]]:
    """Score a model's coverage_reasoning for gap assertions that contradict
    a deterministic ladder raise.

    Returns (weighted_score, matched_phrases). (0, []) means the reasoning
    does not list explicit gaps — the raise is consistent with the model's
    own text. Score >= LADDER_RAISE_REVIEW_THRESHOLD is a strong
    contradiction (flag for review, e.g. reasoning lists explicit gaps but
    the raised verdict says Covered).
    """
    if not reasoning:
        return 0, []
    lower = reasoning.lower()
    score = 0
    matched: list[str] = []
    for phrase in _LADDER_RAISE_GAP_PHRASES:
        if phrase in lower:
            score += 3
            matched.append(phrase)
    for m in _LADDER_RAISE_GAP_SOFT_RE.finditer(lower):
        score += 1
        matched.append(m.group(1))
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


# Risk levels each coverage tier may legitimately carry.
#
# These MUST stay in sync with compute_risk() in gap_analyzer.py, which
# applies a documented cluster-compounding escalation: when a related
# dimension in the same cluster is also a genuine gap, risk is raised one
# step (LOW->MEDIUM, MEDIUM->HIGH). A core Partial dimension therefore
# legitimately reaches HIGH.
#
# PARTIAL previously allowed only [LOW, MEDIUM], so the validator flagged the
# pipeline's OWN correct output as a "risk_coverage_mismatch" error every time
# compounding fired — an internal contradiction between two components that
# were each individually right. The table now reflects the escalation rule.
RISK_COVERAGE_MAP: dict[CoverageLevel, list[RiskLevel]] = {
    CoverageLevel.COVERED: [RiskLevel.LOW],
    CoverageLevel.PARTIAL: [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH],
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
                        CoverageLevel.MISSING,
                        CoverageLevel.PARTIAL,
                    ):
                        violations.append(
                            ConsistencyViolation(
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
                            )
                        )

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
                        ck
                        for ck in child_keywords
                        if gap_by_dim.get(ck) and gap_by_dim[ck].coverage != CoverageLevel.COVERED
                    ]
                    violations.append(
                        ConsistencyViolation(
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
                        )
                    )

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

                if (
                    gap.coverage == CoverageLevel.COVERED
                    and child_gap.coverage != CoverageLevel.COVERED
                ):
                    self.dimension_graph.nodes.get(dim_name)
                    self.dimension_graph.nodes.get(child)
                    violations.append(
                        ConsistencyViolation(
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
                        )
                    )

            for parent in node.parents:
                parent_gap = gap_by_dim.get(parent)
                if parent_gap is None:
                    continue
                pair = (parent, dim_name)
                if pair in processed_pairs:
                    continue
                processed_pairs.add(pair)

                if gap.coverage == CoverageLevel.COVERED and parent_gap.coverage in (
                    CoverageLevel.MISSING,
                    CoverageLevel.PARTIAL,
                ):
                    violations.append(
                        ConsistencyViolation(
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
                        )
                    )

            for required in node.requires:
                req_gap = gap_by_dim.get(required)
                if req_gap is None:
                    continue
                pair = (dim_name, required)
                if pair in processed_pairs:
                    continue
                processed_pairs.add(pair)

                if (
                    gap.coverage == CoverageLevel.COVERED
                    and req_gap.coverage == CoverageLevel.MISSING
                ):
                    violations.append(
                        ConsistencyViolation(
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
                        )
                    )

        return violations

    def _check_risk_coherence(self, gaps: list[GovernanceGap]) -> list[ConsistencyViolation]:
        violations: list[ConsistencyViolation] = []

        for g in gaps:
            if g.coverage in (CoverageLevel.INSUFFICIENT_EVIDENCE, CoverageLevel.COVERED):
                continue
            allowed_risks = RISK_COVERAGE_MAP.get(g.coverage, [])
            if allowed_risks and g.risk_level not in allowed_risks:
                violations.append(
                    ConsistencyViolation(
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
                    )
                )

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
                violations.append(
                    ConsistencyViolation(
                        dimension=g.dimension,
                        violation_type="missing_evidence",
                        description=(
                            f"Dimension '{g.dimension}' has coverage '{g.coverage.value}' "
                            f"but zero evidence items."
                        ),
                        severity="error",
                        suggestion="Re-run retrieval for this dimension or check ChromaDB state.",
                    )
                )
                continue

            fw_items = [e for e in g.evidence if e.source_framework != "unknown"]
            if g.coverage in (CoverageLevel.MISSING, CoverageLevel.PARTIAL) and not fw_items:
                violations.append(
                    ConsistencyViolation(
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
                    )
                )

            # framework_synthesis, not framework_positions. The combined
            # Module 1+2 call emits the synthesis as prose and never fills the
            # structured positions list, so keying this check on
            # framework_positions meant it could never fire on a real run —
            # a validator that is always silent is not a validator.
            if (g.framework_synthesis or g.framework_positions) and g.recommendation in (
                "",
                "No recommendation provided.",
            ):
                violations.append(
                    ConsistencyViolation(
                        dimension=g.dimension,
                        violation_type="recommendation_missing",
                        description=(
                            f"Framework positions exist but recommendation is empty "
                            f"for '{g.dimension}'."
                        ),
                        severity="warning",
                        suggestion="LLM should generate a recommendation when framework positions are available.",
                    )
                )

        if doc_chunks_per_dimension:
            for dim, count in doc_chunks_per_dimension.items():
                if count == 0:
                    g = next((x for x in gaps if x.dimension == dim), None)
                    if g and g.coverage != CoverageLevel.INSUFFICIENT_EVIDENCE:
                        violations.append(
                            ConsistencyViolation(
                                dimension=dim,
                                violation_type="zero_doc_retrieval",
                                description=(
                                    f"No document chunks retrieved for '{dim}' "
                                    f"but coverage is '{g.coverage.value if g else 'N/A'}'."
                                ),
                                severity="warning",
                                suggestion="Increase doc_retrieve_k or check document chunking quality.",
                            )
                        )

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
                (gap.module_2.framework_synthesis_overall_assessment if gap.module_2 else "")
                or gap.framework_synthesis
                or ""
            )
            if not synthesis:
                continue
            score, phrases = detect_covered_synthesis_drift(synthesis)
            if score <= 0:
                continue
            violations.append(
                ConsistencyViolation(
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
                )
            )

        return violations

    def _check_framework_synthesis_quality(
        self, gap_by_dim: dict[str, GovernanceGap]
    ) -> list[ConsistencyViolation]:
        violations: list[ConsistencyViolation] = []

        for dim, gap in gap_by_dim.items():
            if gap.framework_synthesis and gap.framework_synthesis == gap.recommendation:
                violations.append(
                    ConsistencyViolation(
                        dimension=dim,
                        violation_type="synthesis_recommendation_collision",
                        description=(
                            f"Framework synthesis and recommendation are identical for '{dim}'."
                        ),
                        severity="warning",
                        suggestion="Ensure framework synthesis compares requirements vs document, "
                        "while recommendation suggests actions.",
                    )
                )

        return violations
