import pytest

from src.consistency import (
    GAP_ASSERTION_THRESHOLD,
    ConsistencyReport,
    ConsistencyValidator,
    ConsistencyViolation,
    detect_covered_synthesis_drift,
    detect_gap_assertions,
)
from src.models import (
    CoverageLevel,
    GovernanceGap,
    RetrievedEvidence,
    RiskLevel,
)

# A strong gap-filling phrase weighs 3, a weak one 1. The scorer no longer
# changes any verdict, so the boundary is a test expectation, not a rule.
STRONG_DRIFT_WEIGHT = 3


def test_consistency_validator_no_violations():
    validator = ConsistencyValidator()
    gaps = [
        GovernanceGap(
            dimension="Transparency",
            coverage=CoverageLevel.COVERED,
            evidence=[RetrievedEvidence(chunk_id="c1", text="t1", source_framework="fw")],
            reason_flagged="r",
            recommendation="rec",
        ),
    ]
    report = validator.validate(gaps)
    assert report.passed, [v.violation_type for v in report.violations]


def test_consistency_report():
    violations = [
        ConsistencyViolation("Test", "test_type", "desc", severity="error"),
    ]
    report = ConsistencyReport(violations)
    assert not report.passed
    assert report.score < 1.0
    assert report.to_dict()["violation_count"] == 1


def test_consistency_report_empty():
    report = ConsistencyReport([])
    assert report.passed
    assert report.score == 1.0


def test_risk_coherence():
    """A Missing dimension rated LOW risk is incoherent and must be flagged.

    Partial + HIGH is not a violation: compute_risk deliberately escalates a
    core Partial dimension to HIGH when a related dimension in the same
    cluster is also a genuine gap. Missing + LOW has no such escalation path
    and is a real mismatch.
    """
    validator = ConsistencyValidator()
    gaps = [
        GovernanceGap(
            dimension="Transparency",
            coverage=CoverageLevel.MISSING,
            risk_level=RiskLevel.LOW,
            evidence=[RetrievedEvidence(chunk_id="c1", text="t1", source_framework="fw")],
            reason_flagged="r",
            recommendation="rec",
        ),
    ]
    report = validator.validate(gaps)
    risk_violations = [v for v in report.violations if v.violation_type == "risk_coverage_mismatch"]
    assert len(risk_violations) > 0


def test_escalated_partial_risk_is_not_a_violation():
    """Partial + HIGH is the documented output of cluster compounding."""
    validator = ConsistencyValidator()
    gaps = [
        GovernanceGap(
            dimension="Transparency",
            coverage=CoverageLevel.PARTIAL,
            risk_level=RiskLevel.HIGH,
            evidence=[RetrievedEvidence(chunk_id="c1", text="t1", source_framework="fw")],
            reason_flagged="r",
            recommendation="rec",
        ),
    ]
    report = validator.validate(gaps)
    risk_violations = [v for v in report.violations if v.violation_type == "risk_coverage_mismatch"]
    assert risk_violations == []


def test_missing_evidence():
    validator = ConsistencyValidator()
    gaps = [
        GovernanceGap(
            dimension="Transparency",
            coverage=CoverageLevel.COVERED,
            evidence=[],
            reason_flagged="r",
            recommendation="rec",
        ),
    ]
    report = validator.validate(gaps)
    evidence_violations = [v for v in report.violations if v.violation_type == "missing_evidence"]
    assert len(evidence_violations) > 0


def _gap(dimension, coverage, evidence, recommendation="", synthesis="Frameworks expect X."):
    return GovernanceGap(
        dimension=dimension,
        coverage=coverage,
        evidence=evidence,
        reason_flagged="r",
        recommendation=recommendation,
        framework_synthesis=synthesis,
    )


DOC_EVIDENCE = RetrievedEvidence(
    chunk_id="d1", text="t", source_framework="Act.pdf", document_name="Act.pdf"
)
FW_EVIDENCE = RetrievedEvidence(
    chunk_id="f1",
    text="t",
    source_framework="OECD AI Principles",
    document_name="OECD_AI_Principles.pdf",
)


def _types(gaps):
    return [v.violation_type for v in ConsistencyValidator().validate(gaps).violations]


def test_a_covered_dimension_is_not_missing_a_recommendation():
    # Covered carries Best Practices instead of recommendations, so flagging
    # it put a false warning on every Covered dimension of every run.
    gaps = [_gap("Transparency", CoverageLevel.COVERED, [DOC_EVIDENCE, FW_EVIDENCE])]
    assert "recommendation_missing" not in _types(gaps)


def test_a_gap_without_a_recommendation_is_still_flagged():
    gaps = [_gap("Transparency", CoverageLevel.PARTIAL, [DOC_EVIDENCE, FW_EVIDENCE])]
    assert "recommendation_missing" in _types(gaps)


def test_a_gap_resting_on_document_passages_alone_is_flagged():
    # Every citation used to count as framework evidence, so this never fired.
    gaps = [_gap("Transparency", CoverageLevel.PARTIAL, [DOC_EVIDENCE], recommendation="rec")]
    assert "missing_framework_evidence" in _types(gaps)


def test_a_gap_with_framework_evidence_is_not_flagged():
    gaps = [_gap("Transparency", CoverageLevel.PARTIAL, [DOC_EVIDENCE, FW_EVIDENCE], "rec")]
    assert "missing_framework_evidence" not in _types(gaps)


# ── Fully Covered synthesis-drift safeguard ─────────────────────────────


def test_drift_detector_clean_compliance_text():
    clean = (
        "The policy establishes a National AI Ethics Board and already mandates "
        "annual transparency reporting, satisfying the OECD transparency "
        "principle through these existing provisions."
    )
    score, phrases = detect_covered_synthesis_drift(clean)
    assert score == 0
    assert phrases == []


def test_drift_detector_strong_signal_downgrades():
    # Recommendation-flavored synthesis on a Covered tier (the bug reported):
    # "Implementing X, Y, and Z will translate high-level goals into concrete
    # protections" — must register as a strong drift signal.
    bad = (
        "Implementing a mandatory AIA and model cards will translate the "
        "normative commitment into concrete protections, and the government "
        "should establish an oversight body to close the gap."
    )
    score, phrases = detect_covered_synthesis_drift(bad)
    assert score >= STRONG_DRIFT_WEIGHT
    assert any(p in phrases for p in ("should establish", "in order to", "close the gap"))


def test_drift_detector_should_implement():
    score, phrases = detect_covered_synthesis_drift(
        "The policy should implement a national registry."
    )
    assert score >= STRONG_DRIFT_WEIGHT
    assert "should implement" in phrases


def test_drift_detector_would_strengthen():
    score, phrases = detect_covered_synthesis_drift(
        "Mandating disclosure would strengthen public oversight."
    )
    assert score >= STRONG_DRIFT_WEIGHT
    assert "would strengthen" in phrases


def test_drift_detector_weak_signal_flags_only():
    # A lone "lacks" is a flag (score > 0) but below the downgrade threshold.
    score, phrases = detect_covered_synthesis_drift(
        "The document covers the principle but the synthesis lacks clarity."
    )
    assert 0 < score < STRONG_DRIFT_WEIGHT
    assert "lacks" in phrases


def test_drift_detector_empty_synthesis():
    assert detect_covered_synthesis_drift("") == (0, [])
    assert detect_covered_synthesis_drift(None) == (0, [])


def test_drift_detector_honesty_path_surfaces():
    # The Branch A prompt tells the model to honestly state when the document
    # does not substantively satisfy a principle — that honesty flag must be
    # surfaced by the drift detector (score > 0), not scored as clean.
    score, phrases = detect_covered_synthesis_drift(
        "The document does not substantively address consent mechanisms, though "
        "it satisfies other aspects of the privacy principle."
    )
    assert score > 0
    assert "does not" in phrases or "not substantively" in phrases


def test_drift_detector_explicit_non_substantive_admission_downgrades():
    # The model's own "does not substantively" admission is the strongest
    # drift signal — it should cross the downgrade threshold on its own.
    score, phrases = detect_covered_synthesis_drift(
        "The document does not substantively satisfy the consent principle."
    )
    assert score >= STRONG_DRIFT_WEIGHT
    assert "does not substantively" in phrases


def test_drift_detector_fails_to_flagged():
    score, phrases = detect_covered_synthesis_drift(
        "The policy fails to establish enforceable audit obligations."
    )
    assert score > 0
    assert "fails to" in phrases


def test_drift_detector_no_double_count_on_substring_phrases():
    # "does not provide" is a substring of "does not" — the score must not
    # inflate by counting both. One admission scores exactly once for "does
    # not".
    score, phrases = detect_covered_synthesis_drift(
        "The document does not provide any enforcement mechanism."
    )
    assert score == 1
    assert phrases.count("does not") == 1


def test_drift_detector_clean_text_with_substantively_not_flagged():
    # "substantively" alone (without a negating phrase) must stay clean.
    score, phrases = detect_covered_synthesis_drift(
        "The policy substantively addresses the principle through its "
        "existing oversight board and annual reporting."
    )
    assert score == 0


def test_drift_detector_does_not_match_recommendation_noun():
    # "recommendation" as a noun (e.g. the UNESCO Recommendation) must not be
    # confused with the verb "recommend".
    score, phrases = detect_covered_synthesis_drift(
        "The UNESCO Recommendation requires human oversight, which the policy "
        "satisfies through its existing oversight board."
    )
    assert score == 0
    assert "recommend" not in phrases


# ── Ladder-raise review safeguard ────────────────────────────────────────


def test_gap_assertion_detector_clean_reasoning():
    # A raise whose reasoning describes the concrete mechanisms (no explicit
    # gap assertions) stays clean — no contradiction to flag.
    score, phrases = detect_gap_assertions(
        "The Act establishes concrete notification and labeling duties for "
        "high-impact AI and generative AI services."
    )
    assert score == 0
    assert phrases == []


def test_gap_assertion_detector_strong_gap_assertion_flags():
    # The exact India Transparency case: the model's reasoning lists explicit
    # gaps ("does not establish ... obligations") while the ladder raised the
    # verdict to Covered — one strong assertion crosses the review threshold.
    score, phrases = detect_gap_assertions(
        "The Act requires advance notification for high-impact AI but does "
        "not establish individual-level explainability obligations, technical "
        "documentation standards, or system logging mechanisms."
    )
    assert score >= GAP_ASSERTION_THRESHOLD
    assert "does not establish" in phrases


def test_gap_assertion_detector_never_mentions_flags():
    score, phrases = detect_gap_assertions("Document never mentions transparency.")
    assert score >= GAP_ASSERTION_THRESHOLD
    assert "never mentions" in phrases


def test_gap_assertion_detector_lacks_flags():
    score, phrases = detect_gap_assertions(
        "The policy covers notification but lacks any explainability or logging requirements."
    )
    assert score >= GAP_ASSERTION_THRESHOLD
    assert "lacks" in phrases


def test_gap_assertion_detector_empty_reasoning():
    assert detect_gap_assertions("") == (0, [])
    assert detect_gap_assertions(None) == (0, [])


def test_gap_assertion_detector_no_double_count_on_substring_phrases():
    # "does not provide" contains both "does not" and "does not provide" —
    # the score must count the specific phrase once, not double-inflate.
    score, phrases = detect_gap_assertions(
        "The document does not provide any enforcement mechanism."
    )
    assert "does not provide" in phrases
    assert phrases.count("does not provide") == 1


def test_gap_assertion_detector_provides_no_flags():
    # The Fairness miss: the model phrased its gap as "provides no concrete
    # operational mechanisms" — subject-verb-negator order, not caught by
    # the "does not provide" family. A raised verdict paired with this
    # explicit-absence construction is the same contradiction and must
    # flag for review.
    score, phrases = detect_gap_assertions(
        "The Act provides no concrete operational mechanisms for fairness or non-discrimination."
    )
    assert score >= GAP_ASSERTION_THRESHOLD
    assert "provides no" in phrases


def test_gap_assertion_detector_explicit_absence_variants_flag():
    for reasoning in (
        "The Act establishes no liability framework for AI harms.",
        "The policy sets out no redress pathway for affected individuals.",
        "The framework contains no privacy provisions.",
        "The Act imposes no monitoring or enforcement duties.",
    ):
        score, phrases = detect_gap_assertions(reasoning)
        assert score >= GAP_ASSERTION_THRESHOLD, reasoning
        assert phrases, reasoning


def test_covered_synthesis_drift_violation_flagged():
    validator = ConsistencyValidator()
    gaps = [
        GovernanceGap(
            dimension="Transparency",
            coverage=CoverageLevel.COVERED,
            evidence=[RetrievedEvidence(chunk_id="c1", text="t1", source_framework="fw")],
            reason_flagged="r",
            recommendation="rec",
            framework_synthesis=(
                "The policy should implement a registry and would strengthen "
                "oversight through annual audits."
            ),
        ),
    ]
    report = validator.validate(gaps)
    drift = [v for v in report.violations if v.violation_type == "covered_synthesis_drift"]
    assert len(drift) > 0


def test_covered_synthesis_drift_no_violation_for_clean():
    validator = ConsistencyValidator()
    gaps = [
        GovernanceGap(
            dimension="Transparency",
            coverage=CoverageLevel.COVERED,
            evidence=[RetrievedEvidence(chunk_id="c1", text="t1", source_framework="fw")],
            reason_flagged="r",
            recommendation="rec",
            framework_synthesis=(
                "The policy establishes a National AI Ethics Board and mandates "
                "annual transparency reporting, satisfying the OECD principle "
                "through these existing provisions."
            ),
        ),
    ]
    report = validator.validate(gaps)
    drift = [v for v in report.violations if v.violation_type == "covered_synthesis_drift"]
    assert len(drift) == 0


def test_covered_synthesis_drift_not_applied_to_partial():
    validator = ConsistencyValidator()
    gaps = [
        GovernanceGap(
            dimension="Fairness",
            coverage=CoverageLevel.PARTIAL,
            evidence=[RetrievedEvidence(chunk_id="c1", text="t1", source_framework="fw")],
            reason_flagged="r",
            recommendation="rec",
            framework_synthesis=(
                "The policy should establish a bias-audit regime to close the gap."
            ),
        ),
    ]
    report = validator.validate(gaps)
    drift = [v for v in report.violations if v.violation_type == "covered_synthesis_drift"]
    assert len(drift) == 0


def test_drift_detector_honesty_phrase_with_strong_signal_downgrades():
    # Honesty phrases are weight-1 flags; combined with a strong phrase they
    # cross the downgrade threshold.
    score, phrases = detect_covered_synthesis_drift(
        "The policy should establish a registry and currently does not provide "
        "any enforcement mechanism."
    )
    assert score >= STRONG_DRIFT_WEIGHT
    assert "should establish" in phrases
