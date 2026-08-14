"""
Unit tests for brief generator (text brief).
"""

import pytest

from src.gap_analyzer import (
    GapAnalysisResult,
    GovernanceGap,
    RiskLevel,
    RetrievedEvidence,
)
from src.brief_generator import generate_executive_brief_text
from src.gap_analyzer import GOVERNANCE_DIMENSIONS


@pytest.fixture
def sample_result():
    gaps = []
    for dim in GOVERNANCE_DIMENSIONS:
        ev = RetrievedEvidence(
            chunk_id="test_chunk",
            text="Relevant framework text about " + dim,
            page_number=5,
            source_framework="OECD AI Principles",
            similarity_score=0.85,
            section_title="Section on " + dim,
        )
        gap = GovernanceGap(
            dimension=dim,
            gap_found=(dim in ["Transparency", "Accountability"]),
            evidence=[ev],
            reason_flagged=f"Document lacks specific {dim.lower()} provisions." if dim in ["Transparency", "Accountability"] else "Sufficient coverage found.",
            recommendation=f"Strengthen {dim.lower()} provisions." if dim in ["Transparency", "Accountability"] else "Maintain current approach.",
            risk_level=RiskLevel.HIGH if dim == "Transparency" else (
                RiskLevel.MEDIUM if dim == "Accountability" else RiskLevel.LOW
            ),
            risk_reason=f"Gap in {dim.lower()} poses governance risk.",
            potential_consequence=f"Without {dim.lower()}, AI systems may lack public trust.",
            un_recommendation=f"Align with international standards on {dim.lower()}.",
            confidence_score=0.85,
            confidence_method="Based on retrieved evidence similarity",
        )
        gaps.append(gap)

    return GapAnalysisResult(
        analysis_id="test-analysis-001",
        workspace_id="test-ws-001",
        document_name="National AI Strategy - Test",
        frameworks_used=["OECD AI Principles", "UNESCO Recommendation"],
        governance_gaps=gaps,
        summary="Analysis of 8 governance dimensions: 2 gaps identified (1 high-risk, 1 medium-risk). 0 dimensions had insufficient evidence.",
        total_retrieved=24,
        retrieval_frameworks=["OECD AI Principles", "UNESCO Recommendation"],
        similarity_scores=[0.85, 0.82, 0.78, 0.75],
        llm_latency=4.5,
        total_processing_time=12.3,
    )


class TestExecutiveBriefText:
    def test_generates_brief(self, sample_result):
        brief = generate_executive_brief_text(sample_result)
        assert len(brief) > 100
        assert "EXECUTIVE BRIEF" in brief
        assert "EXECUTIVE SUMMARY" in brief
        assert "KEY FINDINGS" in brief
        assert "RISK SUMMARY" in brief
        assert "RECOMMENDATIONS" in brief
        assert "REFERENCES" in brief

    def test_includes_document_name(self, sample_result):
        brief = generate_executive_brief_text(sample_result)
        assert sample_result.document_name in brief

    def test_includes_frameworks(self, sample_result):
        brief = generate_executive_brief_text(sample_result)
        for fw in sample_result.frameworks_used:
            assert fw in brief

    def test_includes_gap_details(self, sample_result):
        brief = generate_executive_brief_text(sample_result)
        assert "Transparency" in brief
        assert "Accountability" in brief
