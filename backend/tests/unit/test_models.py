import pytest
from pydantic import ValidationError

from src.models import (
    CalibratedConfidence,
    CoverageLevel,
    FrameworkPositionRaw,
    GovernanceGap,
    RetrievedEvidence,
    RiskLevel,
)


class TestGovernanceGap:
    def test_minimal_construction(self):
        gap = GovernanceGap(
            dimension="Transparency",
            reason_flagged="No transparency provisions found",
            recommendation="Add transparency requirements",
        )
        assert gap.dimension == "Transparency"
        assert gap.coverage == CoverageLevel.MISSING
        assert gap.gap_found is True

    def test_covered_gap_not_found(self):
        gap = GovernanceGap(
            dimension="Privacy",
            coverage=CoverageLevel.COVERED,
            gap_found=False,
            reason_flagged="Adequately addressed",
            recommendation="Maintain current approach",
        )
        assert gap.gap_found is False

    def test_evidence_list(self):
        ev = RetrievedEvidence(chunk_id="c1", text="evidence text", source_framework="OECD")
        gap = GovernanceGap(
            dimension="Safety",
            reason_flagged="test",
            recommendation="test",
            evidence=[ev],
        )
        assert len(gap.evidence) == 1
        assert gap.evidence[0].chunk_id == "c1"

    def test_full_construction(self):
        gap = GovernanceGap(
            dimension="Accountability",
            coverage=CoverageLevel.PARTIAL,
            gap_found=True,
            reason_flagged="Partial coverage",
            recommendation="Strengthen grievance mechanisms",
            risk_level=RiskLevel.MEDIUM,
            risk_reason="Core dimension partially addressed",
            potential_consequence="Reduced public trust",
            framework_synthesis="OECD requires grievance mechanisms",
            confidence_score=0.75,
            confidence_method="GeoMean method",
            coverage_reasoning="Level 2 depth",
        )
        assert gap.confidence_score == 0.75


class TestCalibratedConfidence:
    def test_default_values(self):
        cal = CalibratedConfidence()
        assert cal.overall == 0.0
        assert cal.method == ""

    def test_geometric_mean_all_ones(self):
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

    def test_geometric_mean_mixed(self):
        cal = CalibratedConfidence(
            evidence_quality_factor=0.8,
            evidence_diversity_factor=0.6,
            evidence_agreement_factor=0.7,
            retrieval_stability_factor=0.9,
            citation_strength_factor=0.5,
            cross_source_agreement=0.4,
            coverage_completeness_factor=0.3,
        )
        gm = cal.geometric_mean()
        assert 0.0 < gm < 1.0

    def test_geometric_mean_zeros_protected(self):
        cal = CalibratedConfidence(
            evidence_quality_factor=0.0,
            evidence_diversity_factor=0.0,
            evidence_agreement_factor=0.0,
            retrieval_stability_factor=0.0,
            citation_strength_factor=0.0,
            cross_source_agreement=0.0,
            coverage_completeness_factor=0.0,
        )
        assert cal.geometric_mean() > 0.0  # protected by 0.001 floor

    def test_geometric_mean_negative_protected(self):
        cal = CalibratedConfidence(
            evidence_quality_factor=-0.5,
            evidence_diversity_factor=0.5,
        )
        gm = cal.geometric_mean()
        assert gm > 0.0

    def test_serialization_roundtrip(self):
        cal = CalibratedConfidence(
            overall=0.75,
            evidence_quality_factor=0.8,
            method="GeoMean(0.8, 0.7, 0.6)",
        )
        data = cal.model_dump()
        restored = CalibratedConfidence(**data)
        assert restored.overall == 0.75
        assert "GeoMean" in restored.method


class TestRetrievedEvidence:
    def test_minimal_construction(self):
        ev = RetrievedEvidence(chunk_id="c1", text="text", source_framework="OECD")
        assert ev.verified is False
        assert ev.verification is None

    def test_full_construction(self):
        ev = RetrievedEvidence(
            chunk_id="c1",
            text="policy text",
            page_number=5,
            source_framework="UNESCO",
            similarity_score=0.92,
            section_title="Chapter 3",
            verified=True,
            verification={"method": "nli", "score": 0.85},
        )
        assert ev.page_number == 5
        assert ev.similarity_score == 0.92
        assert ev.section_title == "Chapter 3"
        assert ev.verified is True
