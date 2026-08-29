import pytest
from pydantic import ValidationError

from src.models import (
    CalibratedConfidence,
    CoverageLevel,
    EvidenceInterpretation,
    EvidenceStrength,
    FrameworkPositionRaw,
    FrameworkSynthesisResult,
    GovernanceGap,
    GovernanceMaturityLevel,
    MaturityAssessment,
    PlausibilityReview,
    PolicyRecommendation,
    RetrievedEvidence,
    RiskLevel,
)


class TestGovernanceMaturityLevel:
    def test_level_values(self):
        assert GovernanceMaturityLevel.ABSENT.value == 0
        assert GovernanceMaturityLevel.GENERAL_ACKNOWLEDGEMENT.value == 1
        assert GovernanceMaturityLevel.GOVERNANCE_OBJECTIVES_DEFINED.value == 2
        assert GovernanceMaturityLevel.OPERATIONAL_MECHANISMS.value == 3
        assert GovernanceMaturityLevel.IMPLEMENTATION_AND_OVERSIGHT.value == 4
        assert GovernanceMaturityLevel.CONTINUOUS_MONITORING_AND_ENFORCEMENT.value == 5

    def test_all_levels_accessible(self):
        for i in range(6):
            assert GovernanceMaturityLevel(i) is not None

    def test_invalid_level_raises(self):
        with pytest.raises(ValueError):
            GovernanceMaturityLevel(6)
        with pytest.raises(ValueError):
            GovernanceMaturityLevel(-1)


class TestEvidenceStrength:
    def test_all_strengths(self):
        assert EvidenceStrength.NOT_DEMONSTRATED.value == "Not Demonstrated"
        assert EvidenceStrength.WEAKLY_DEMONSTRATED.value == "Weakly Demonstrated"
        assert EvidenceStrength.IMPLICITLY_ADDRESSED.value == "Implicitly Addressed"
        assert EvidenceStrength.EXPLICITLY_ADDRESSED.value == "Explicitly Addressed"
        assert EvidenceStrength.STRONGLY_OPERATIONALISED.value == "Strongly Operationalised"

    def test_from_string(self):
        assert EvidenceStrength("Not Demonstrated") == EvidenceStrength.NOT_DEMONSTRATED
        assert (
            EvidenceStrength("Strongly Operationalised")
            == EvidenceStrength.STRONGLY_OPERATIONALISED
        )


class TestEvidenceInterpretation:
    def test_minimal_construction(self):
        ei = EvidenceInterpretation(dimension="Transparency")
        assert ei.dimension == "Transparency"
        assert ei.explicit_evidence == []
        assert ei.evidence_strength == EvidenceStrength.NOT_DEMONSTRATED

    def test_full_construction(self):
        ei = EvidenceInterpretation(
            dimension="Privacy",
            explicit_evidence=["GDPR compliance required"],
            implicit_evidence=["Data protection inferred"],
            demonstrated_capability="Strong data governance",
            absent_capability="Enforcement mechanisms",
            strong_evidence=["Explicit data protection requirements"],
            weak_evidence=["Vague consent references"],
            contradictory_evidence=[],
            evidence_strength=EvidenceStrength.EXPLICITLY_ADDRESSED,
            interpretation_summary="Policy addresses privacy but lacks enforcement",
        )
        assert ei.dimension == "Privacy"
        assert len(ei.explicit_evidence) == 1
        assert ei.evidence_strength == EvidenceStrength.EXPLICITLY_ADDRESSED

    def test_missing_dimension_raises(self):
        with pytest.raises(ValidationError):
            EvidenceInterpretation()

    def test_serialization_roundtrip(self):
        ei = EvidenceInterpretation(
            dimension="Safety",
            evidence_strength=EvidenceStrength.STRONGLY_OPERATIONALISED,
            interpretation_summary="Strong safety framework",
        )
        data = ei.model_dump()
        restored = EvidenceInterpretation(**data)
        assert restored.dimension == "Safety"
        assert restored.evidence_strength == EvidenceStrength.STRONGLY_OPERATIONALISED
        assert restored.interpretation_summary == "Strong safety framework"


class TestMaturityAssessment:
    def test_minimal_construction(self):
        ma = MaturityAssessment(dimension="Accountability")
        assert ma.dimension == "Accountability"
        assert ma.maturity_level == GovernanceMaturityLevel.ABSENT

    def test_full_construction(self):
        ma = MaturityAssessment(
            dimension="Accountability",
            maturity_level=GovernanceMaturityLevel.OPERATIONAL_MECHANISMS,
            maturity_label="Operational Mechanisms",
            coverage=CoverageLevel.PARTIAL,
            maturity_reasoning="Policy establishes grievance mechanisms",
            level_justification="Section 3 defines complaints process",
            uncertainty_flags=["Scope of mechanism unclear"],
            false_negative_check="All nine checks passed",
        )
        assert ma.maturity_level == GovernanceMaturityLevel.OPERATIONAL_MECHANISMS
        assert ma.coverage == CoverageLevel.PARTIAL
        assert len(ma.uncertainty_flags) == 1

    def test_level_conversion_to_coverage(self):
        cases = [
            (GovernanceMaturityLevel.ABSENT, CoverageLevel.MISSING),
            (GovernanceMaturityLevel.GENERAL_ACKNOWLEDGEMENT, CoverageLevel.PARTIAL),
            (GovernanceMaturityLevel.GOVERNANCE_OBJECTIVES_DEFINED, CoverageLevel.PARTIAL),
            (GovernanceMaturityLevel.OPERATIONAL_MECHANISMS, CoverageLevel.COVERED),
            (GovernanceMaturityLevel.IMPLEMENTATION_AND_OVERSIGHT, CoverageLevel.COVERED),
            (GovernanceMaturityLevel.CONTINUOUS_MONITORING_AND_ENFORCEMENT, CoverageLevel.COVERED),
        ]
        for level, expected_coverage in cases:
            ma = MaturityAssessment(
                dimension="Test", maturity_level=level, coverage=expected_coverage
            )
            assert ma.maturity_level == level
            assert ma.coverage == expected_coverage

    def test_missing_dimension_raises(self):
        with pytest.raises(ValidationError):
            MaturityAssessment()


class TestFrameworkSynthesisResult:
    def test_minimal_construction(self):
        fs = FrameworkSynthesisResult(dimension="Fairness")
        assert fs.dimension == "Fairness"
        assert fs.implementation_maturity_comparison == {}

    def test_with_implementation_comparison(self):
        fs = FrameworkSynthesisResult(
            dimension="Fairness",
            implementation_maturity_comparison={
                "Already implemented": ["Bias testing requirements"],
                "Partially implemented": ["Demographic parity"],
                "Missing implementation": ["Enforcement mechanisms"],
            },
        )
        assert "Already implemented" in fs.implementation_maturity_comparison
        assert len(fs.implementation_maturity_comparison["Already implemented"]) == 1

    def test_full_construction(self):
        fs = FrameworkSynthesisResult(
            dimension="Inclusivity",
            universal_requirements=["Accessibility standards"],
            framework_agreements=["All frameworks mandate accessibility"],
            framework_differences=["UNESCO emphasises cultural inclusion"],
            existing_mechanisms=["Accessibility requirements defined"],
            missing_mechanisms=["Digital divide provisions"],
            framework_specific_requirements={"UNESCO": ["Cultural inclusion"]},
            implementation_maturity_comparison={
                "Already implemented": ["Accessibility standards"],
                "Framework-specific requirement": ["Cultural inclusion"],
            },
            synthesis="Policy meets baseline accessibility but not cultural inclusion",
        )
        assert len(fs.universal_requirements) == 1
        assert len(fs.existing_mechanisms) == 1
        assert len(fs.missing_mechanisms) == 1
        assert "UNESCO" in fs.framework_specific_requirements


class TestPlausibilityReview:
    def test_minimal_construction(self):
        pr = PlausibilityReview(dimension="Safety")
        assert pr.dimension == "Safety"
        assert pr.confidence_in_assessment == "Medium"

    def test_full_construction(self):
        pr = PlausibilityReview(
            dimension="Safety",
            original_maturity_level=2,
            validated_maturity_level=3,
            validated_coverage=CoverageLevel.PARTIAL,
            plausibility_checks=["Counter-argument constructed", "Original reasoning stronger"],
            adjustment_rationale="Counter-argument revealed implicit mechanisms",
            confidence_in_assessment="High",
            uncertainty_acknowledged=["Scope remains ambiguous"],
        )
        assert pr.original_maturity_level == 2
        assert pr.validated_maturity_level == 3
        assert pr.validated_coverage == CoverageLevel.PARTIAL
        assert pr.confidence_in_assessment == "High"

    def test_adjustment_preserves_trace(self):
        pr = PlausibilityReview(
            dimension="Test",
            original_maturity_level=1,
            validated_maturity_level=3,
            validated_coverage=CoverageLevel.COVERED,
            adjustment_rationale="Upgraded after counter-argument review",
        )
        assert pr.original_maturity_level != pr.validated_maturity_level
        assert pr.adjustment_rationale != ""


class TestPolicyRecommendation:
    def test_minimal_construction(self):
        rec = PolicyRecommendation(dimension="Human Autonomy")
        assert rec.dimension == "Human Autonomy"
        assert rec.recommendations == []

    def test_full_construction(self):
        rec = PolicyRecommendation(
            dimension="Human Autonomy",
            existing_strengths="Policy requires human oversight",
            governance_capability="Level 3 — Operational Mechanisms",
            remaining_limitations="No right to human review",
            missing_mechanisms=["Right to opt out", "Human review process"],
            recommendations=["Extend oversight provisions to include right to human review"],
            smallest_effective_improvement="Add human review clause to existing oversight mechanism",
            recommendation_rationale="Builds on existing Section 4 oversight provisions",
        )
        assert len(rec.recommendations) == 1
        assert "oversight" in rec.recommendation_rationale
        assert len(rec.smallest_effective_improvement) > 10


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
            coverage_reasoning="Level 2 maturity",
            evidence_quotes=["Section 5 mentions accountability"],
            aspects_addressed=["Grievance mechanism"],
            aspects_missing=["Enforcement"],
            gap_analysis="Partial coverage with gaps in enforcement",
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

    def test_semantic_score(self):
        ev = RetrievedEvidence(
            chunk_id="c1", text="text", source_framework="OECD", semantic_score=0.88
        )
        assert ev.semantic_score == 0.88
