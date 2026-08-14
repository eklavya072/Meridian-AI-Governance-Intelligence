import pytest
from src.models import CalibratedConfidence, CoverageLevel, RetrievedEvidence
from src.gap_analyzer import compute_calibrated_confidence


def test_calibrated_confidence_geometric_mean():
    cal = CalibratedConfidence(
        evidence_quality_factor=0.8,
        evidence_diversity_factor=0.7,
        evidence_agreement_factor=0.9,
        retrieval_stability_factor=0.6,
        citation_strength_factor=0.5,
        cross_source_agreement=0.8,
        coverage_completeness_factor=0.7,
    )
    gm = cal.geometric_mean()
    assert 0 < gm < 1.0
    assert gm > 0.6


def test_calibrated_confidence_zero_factor():
    cal = CalibratedConfidence(
        evidence_quality_factor=0.0,
        evidence_diversity_factor=0.9,
        evidence_agreement_factor=0.9,
        retrieval_stability_factor=0.9,
        citation_strength_factor=0.9,
        cross_source_agreement=0.9,
        coverage_completeness_factor=0.9,
    )
    gm = cal.geometric_mean()
    assert gm < 0.5
    assert gm > 0.0


def test_calibrated_confidence_all_ones():
    cal = CalibratedConfidence(
        evidence_quality_factor=1.0,
        evidence_diversity_factor=1.0,
        evidence_agreement_factor=1.0,
        retrieval_stability_factor=1.0,
        citation_strength_factor=1.0,
        cross_source_agreement=1.0,
        coverage_completeness_factor=1.0,
    )
    assert cal.geometric_mean() == 1.0


def test_compute_calibrated_confidence_no_evidence():
    score, method = compute_calibrated_confidence([])
    assert score == 0.0
    assert "No evidence" in method


def test_compute_calibrated_confidence_with_evidence():
    evidence = [
        RetrievedEvidence(chunk_id="c1", text="t1", source_framework="fw1", similarity_score=0.8),
        RetrievedEvidence(chunk_id="c2", text="t2", source_framework="fw2", similarity_score=0.7),
    ]
    score, method = compute_calibrated_confidence(
        evidence,
        coverage_level=CoverageLevel.COVERED,
        dimension="Transparency",
    )
    assert 0 < score <= 1.0
    assert "GeoMean" in method


def test_compute_calibrated_confidence_single_source():
    evidence = [
        RetrievedEvidence(chunk_id="c1", text="t1", source_framework="fw1", similarity_score=0.5),
    ]
    score, method = compute_calibrated_confidence(evidence)
    assert 0 < score <= 1.0


def test_calibrated_confidence_agreement_factor_improves():
    evidence = [
        RetrievedEvidence(chunk_id="c1", text="t1", source_framework="fw1", similarity_score=0.5),
        RetrievedEvidence(chunk_id="c2", text="t2", source_framework="fw2", similarity_score=0.5),
    ]

    import src.evidence_agreement
    original_fn = src.evidence_agreement.compute_evidence_agreement_score

    score_no_pairs, _ = compute_calibrated_confidence(evidence, evidence_pairs=[])

    from src.models import EvidencePair, EvidenceAgreement
    good_pairs = [
        EvidencePair(item_a_id="c1", item_b_id="c2",
                     agreement=EvidenceAgreement.SUPPORTING, score=0.9),
    ]
    score_with_pairs, _ = compute_calibrated_confidence(evidence, evidence_pairs=good_pairs)

    assert score_with_pairs >= score_no_pairs
