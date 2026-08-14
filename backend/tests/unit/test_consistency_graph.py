import pytest
from src.consistency import (
    ConsistencyValidator,
    build_governance_dimension_graph,
    ConsistencyViolation,
    ConsistencyReport,
    detect_covered_synthesis_drift,
    COVERED_SYNTHESIS_DOWNGRADE_THRESHOLD,
)
from src.models import (
    CoverageLevel, RiskLevel, GovernanceGap, RetrievedEvidence, DimensionGraph,
)


def test_dimension_graph_build():
    g = build_governance_dimension_graph()
    assert "Governance" in g.nodes
    assert "Accountability" in g.nodes
    assert "Accountability" in g.nodes["Governance"].children
    assert "Governance" in g.nodes["Accountability"].parents


def test_dimension_graph_get_ancestors():
    g = DimensionGraph()
    g.add_relationship("A", "B", "subsumes")
    g.add_relationship("B", "C", "requires")
    ancestors = g.get_ancestors("C")
    assert "B" in ancestors
    assert "A" in ancestors
    assert "C" not in ancestors


def test_dimension_graph_get_descendants():
    g = DimensionGraph()
    g.add_relationship("A", "B", "subsumes")
    g.add_relationship("B", "C", "requires")
    descendants = g.get_descendants("A")
    assert "B" in descendants
    assert "C" in descendants
    assert "A" not in descendants


def test_dimension_graph_has_path():
    g = DimensionGraph()
    g.add_relationship("A", "B")
    g.add_relationship("B", "C")
    assert g.has_path("A", "C")
    assert g.has_path("A", "B")
    assert not g.has_path("C", "A")


def test_consistency_validator_init():
    validator = ConsistencyValidator()
    assert validator.dimension_graph is not None
    assert "Governance" in validator.dimension_graph.nodes


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
    assert report.passed or len(report.violations) >= 0


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


def test_graph_child_not_covered():
    validator = ConsistencyValidator()
    gaps = [
        GovernanceGap(
            dimension="Accountability",
            coverage=CoverageLevel.COVERED,
            evidence=[RetrievedEvidence(chunk_id="c1", text="t1", source_framework="fw")],
            reason_flagged="r",
            recommendation="rec",
        ),
        GovernanceGap(
            dimension="Human Oversight",
            coverage=CoverageLevel.MISSING,
            evidence=[RetrievedEvidence(chunk_id="c2", text="t2", source_framework="fw")],
            reason_flagged="r",
            recommendation="rec",
        ),
    ]
    report = validator.validate(gaps)
    graph_violations = [v for v in report.violations if v.violation_type == "graph_child_not_covered"]
    assert len(graph_violations) >= 0


def test_risk_coherence():
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
    assert len(risk_violations) > 0


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
    assert score >= COVERED_SYNTHESIS_DOWNGRADE_THRESHOLD
    assert any(p in phrases for p in ("should establish", "in order to", "close the gap"))


def test_drift_detector_should_implement():
    score, phrases = detect_covered_synthesis_drift(
        "The policy should implement a national registry."
    )
    assert score >= COVERED_SYNTHESIS_DOWNGRADE_THRESHOLD
    assert "should implement" in phrases


def test_drift_detector_would_strengthen():
    score, phrases = detect_covered_synthesis_drift(
        "Mandating disclosure would strengthen public oversight."
    )
    assert score >= COVERED_SYNTHESIS_DOWNGRADE_THRESHOLD
    assert "would strengthen" in phrases


def test_drift_detector_weak_signal_flags_only():
    # A lone "lacks" is a flag (score > 0) but below the downgrade threshold.
    score, phrases = detect_covered_synthesis_drift(
        "The document covers the principle but the synthesis lacks clarity."
    )
    assert 0 < score < COVERED_SYNTHESIS_DOWNGRADE_THRESHOLD
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
    assert score >= COVERED_SYNTHESIS_DOWNGRADE_THRESHOLD
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
    assert score >= COVERED_SYNTHESIS_DOWNGRADE_THRESHOLD
    assert "should establish" in phrases
