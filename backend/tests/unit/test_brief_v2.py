"""Unit tests for the executive brief (Part 3): LLM synthesis assembly,
deterministic sections, markdown rendering, and DOCX/PDF exporters.

The synthesis LLM call itself is NOT exercised here (network + quota) — the
deterministic assembly and rendering layers are, which is where the
anti-fabrication guarantees live.
"""

import pytest

from src.brief_synthesis import (
    BriefSynthesis,
    assemble_brief,
    build_dimension_digest,
    build_relevant_precedent,
    build_risk_overview,
    render_brief_markdown,
)

SCOPE = "Scope: this assessment evaluates the provided document (strat.pdf)."


@pytest.fixture
def gaps():
    return [
        {
            "dimension": "Transparency",
            "coverage": "Partial",
            "risk_level": "Medium",
            "analysis_error": None,
            "module_1": {"governance_maturity": "Emerging"},
            "module_2": {
                "priority": "Medium",
                "recommendations": ["Mandate model-level disclosure", "Publish an AI system registry"],
            },
        },
        {
            "dimension": "Accountability",
            "coverage": "Missing",
            "risk_level": "High",
            "analysis_error": None,
            "module_1": {"governance_maturity": "Unaddressed"},
            "module_2": {
                "priority": "High",
                "recommendations": ["Establish a responsible AI oversight body"],
            },
        },
        {
            "dimension": "Privacy",
            "coverage": "Covered",
            "risk_level": "Low",
            "analysis_error": None,
            "module_1": {"governance_maturity": "Formalized"},
            "module_2": {
                "priority": None,
                "recommendations": [],
                "best_practices": {"future_strengthening_opportunities": ["Cross-border data flow code"]},
            },
        },
        {
            "dimension": "Safety",
            "coverage": "Partial",
            "risk_level": "High",
            "analysis_error": None,
            "module_1": {"governance_maturity": "Emerging"},
            "module_2": {"priority": "High", "recommendations": ["Pre-deployment safety testing"]},
            "module_4": {
                "matched": True,
                "incident_matches": [{"incident_name": "Algorithmic bias in credit scoring"}],
            },
        },
    ]


def _synthesis():
    return BriefSynthesis(
        executive_summary="The strategy covers privacy well but has partial transparency and safety mechanisms.",
        areas_of_strength=["Privacy is fully addressed at Formalized maturity."],
        areas_requiring_attention=["Accountability has no owner mechanism."],
        priority_recommendations=[
            {"recommendation": "Establish a responsible AI oversight body", "rationale": "No accountable owner exists today"}
        ],
    )


class TestDeterministicSections:
    def test_digest_includes_only_stored_facts(self, gaps):
        digest = build_dimension_digest(gaps)
        assert "Transparency: Coverage Partial" in digest
        assert "Priority: High" in digest
        assert "Mandate model-level disclosure" in digest
        assert "future strengthening opportunities" in digest.lower()
        assert "Cross-border data flow code" in digest

    def test_risk_overview_counts_and_compounding(self, gaps):
        ro = build_risk_overview(gaps)
        assert ro["distribution"]["High"] == 2
        assert ro["distribution"]["Medium"] == 1
        assert ro["distribution"]["Low"] == 1
        assert ro["high_priority_dimensions"] == ["Accountability", "Safety"]
        # 2+ high-priority dims -> compounding sentence present.
        assert "compounding" in ro["paragraph"]

    def test_risk_overview_single_high_no_compounding(self, gaps):
        single = [g for g in gaps if g["dimension"] in ("Accountability", "Privacy")]
        ro = build_risk_overview(single)
        assert ro["high_priority_dimensions"] == ["Accountability"]
        assert "compounding" not in ro["paragraph"]

    def test_precedent_deduplicates(self, gaps):
        assert "Algorithmic bias in credit scoring" in build_relevant_precedent(gaps)
        no_incidents = [g for g in gaps if "module_4" not in g]
        assert build_relevant_precedent(no_incidents) is None


class TestAssembly:
    def test_assemble_structure(self, gaps):
        brief = assemble_brief(
            workspace_id="w1",
            country="Testland",
            policy_title="AI Strategy",
            document_name="strat.pdf",
            documents=["strat.pdf"],
            frameworks_used=["EU AI Act", "UNESCO"],
            scope_disclaimer=SCOPE,
            gaps=gaps,
            synthesis=_synthesis(),
            decision_analytics={},
        )
        assert brief["num_dimensions"] == 4
        assert brief["coverage_summary"] == {
            "covered": 1, "partial": 2, "missing": 1,
            "insufficient_evidence": 0, "analysis_failed": 0,
        }
        sec = brief["sections"]
        assert sec["executive_summary"] == _synthesis().executive_summary
        assert sec["priority_recommendations"][0]["recommendation"]
        assert sec["relevant_precedent"] is not None
        assert SCOPE in sec["scope_and_methodology"]
        assert "EU AI Act, UNESCO" in sec["scope_and_methodology"]

    def test_markdown_roundtrip(self, gaps):
        brief = assemble_brief(
            workspace_id="w1", country="Testland", policy_title="AI Strategy",
            document_name="strat.pdf", documents=["strat.pdf"],
            frameworks_used=["EU AI Act"], scope_disclaimer=SCOPE,
            gaps=gaps, synthesis=_synthesis(), decision_analytics=None,
        )
        md = render_brief_markdown(brief)
        for marker in [
            "Testland — AI Strategy",
            "AI Governance Assessment Brief",
            "EXECUTIVE SUMMARY",
            "KEY FINDINGS",
            "Areas of Strength",
            "RISK OVERVIEW",
            "PRIORITY RECOMMENDATIONS",
            "RELEVANT PRECEDENT",
            "SCOPE & METHODOLOGY",
        ]:
            assert marker in md


class TestExporters:
    def _brief(self, gaps):
        return assemble_brief(
            workspace_id="w1", country="Testland", policy_title="AI Strategy",
            document_name="strat.pdf", documents=["strat.pdf"],
            frameworks_used=["EU AI Act"], scope_disclaimer=SCOPE,
            gaps=gaps, synthesis=_synthesis(), decision_analytics=None,
        )

    def test_docx_valid(self, gaps):
        from src.brief_export import render_docx

        data = render_docx(self._brief(gaps))
        assert data[:2] == b"PK"  # zip magic — python-docx output
        assert len(data) > 1000

    def test_pdf_valid(self, gaps):
        from src.brief_export import render_pdf

        data = render_pdf(self._brief(gaps))
        assert data[:5] == b"%PDF-"
        assert len(data) > 500
