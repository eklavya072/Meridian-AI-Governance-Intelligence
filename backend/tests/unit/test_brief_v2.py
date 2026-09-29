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
    build_precedents,
    build_relevant_precedent,
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
            "module_1": {"implementation_depth": "Emerging"},
            "module_2": {
                "priority": "Medium",
                "recommendations": [
                    "Mandate model-level disclosure",
                    "Publish an AI system registry",
                ],
            },
        },
        {
            "dimension": "Accountability",
            "coverage": "Missing",
            "risk_level": "High",
            "analysis_error": None,
            "module_1": {"implementation_depth": "Unaddressed"},
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
            "module_1": {"implementation_depth": "Formalized"},
            "module_2": {
                "priority": None,
                "recommendations": [],
                "best_practices": {
                    "future_strengthening_opportunities": ["Cross-border data flow code"]
                },
            },
        },
        {
            "dimension": "Safety",
            "coverage": "Partial",
            "risk_level": "High",
            "analysis_error": None,
            "module_1": {"implementation_depth": "Emerging"},
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
        areas_of_strength=["Privacy is fully addressed at Formalized depth."],
        areas_requiring_attention=["Accountability has no owner mechanism."],
        priority_recommendations=[
            {
                "recommendation": "Establish a responsible AI oversight body",
                "rationale": "No accountable owner exists today",
            }
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

    def test_precedents_carry_what_happened_and_the_lesson(self):
        gaps = [
            {
                "dimension": "Fairness",
                "module_4": {
                    "incident_matches": [
                        {
                            "incident_name": "SyRI",
                            "source": "SyRI Judgment",
                            "what_happened": "A welfare-fraud risk model was struck down. "
                            "The court found it opaque.",
                            "lessons_learned": "Publish the model's criteria.",
                        }
                    ]
                },
            },
            {
                "dimension": "Transparency",
                "module_4": {"incident_matches": [{"incident_name": "SyRI"}]},
            },
        ]
        [p] = build_precedents(gaps)
        # One entry per incident, naming every dimension it bears on.
        assert p["incident"] == "SyRI"
        assert p["dimensions"] == ["Fairness", "Transparency"]
        assert p["what_happened"].startswith("A welfare-fraud risk model")
        assert p["lesson"] == "Publish the model's criteria."
        assert p["source"] == "SyRI Judgment"

    def test_precedent_deduplicates(self, gaps):
        names = [p["incident"] for p in build_precedents(gaps)]
        assert names == ["Algorithmic bias in credit scoring"]
        assert "one real-world incident" in build_relevant_precedent(gaps)
        no_incidents = [g for g in gaps if "module_4" not in g]
        assert build_relevant_precedent(no_incidents) is None
        assert build_precedents(no_incidents) == []


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
            "covered": 1,
            "partial": 2,
            "missing": 1,
            "insufficient_evidence": 0,
            "analysis_failed": 0,
        }
        sec = brief["sections"]
        assert sec["executive_summary"] == _synthesis().executive_summary
        assert sec["priority_recommendations"][0]["recommendation"]
        assert sec["relevant_precedent"] is not None
        assert SCOPE in sec["scope_and_methodology"]
        # The instruments are counted, not listed: the list was 43 names long.
        assert (
            "compared against 2 international reference instruments" in sec["scope_and_methodology"]
        )
        assert "risk_overview" not in sec

    def test_markdown_roundtrip(self, gaps):
        brief = assemble_brief(
            workspace_id="w1",
            country="Testland",
            policy_title="AI Strategy",
            document_name="strat.pdf",
            documents=["strat.pdf"],
            frameworks_used=["EU AI Act"],
            scope_disclaimer=SCOPE,
            gaps=gaps,
            synthesis=_synthesis(),
            decision_analytics=None,
        )
        md = render_brief_markdown(brief)
        for marker in [
            "Testland — AI Strategy",
            "AI Governance Assessment Brief",
            "EXECUTIVE SUMMARY",
            "KEY FINDINGS",
            "Areas of Strength",
            "PRIORITY RECOMMENDATIONS",
            "RELEVANT PRECEDENT",
            "SCOPE & METHODOLOGY",
        ]:
            assert marker in md
        assert "RISK OVERVIEW" not in md


class TestExporters:
    def _brief(self, gaps):
        return assemble_brief(
            workspace_id="w1",
            country="Testland",
            policy_title="AI Strategy",
            document_name="strat.pdf",
            documents=["strat.pdf"],
            frameworks_used=["EU AI Act"],
            scope_disclaimer=SCOPE,
            gaps=gaps,
            synthesis=_synthesis(),
            decision_analytics=None,
        )

    def test_docx_valid(self, gaps):
        from src.brief_export import render_docx

        data = render_docx(self._brief(gaps))
        assert data[:2] == b"PK"  # zip magic — python-docx output
        assert len(data) > 1000

    def test_docx_survives_characters_pdf_text_carries(self, gaps):
        """Form feeds and vertical tabs come out of PDF extraction; Word's XML
        refuses them, and one inside a quote used to fail the whole export."""
        from src.brief_export import render_docx

        brief = self._brief(gaps)
        brief["country"] = "Testland\x0c"
        brief["policy_title"] = "AI\x0bStrategy & R&D <2025>"

        assert render_docx(brief)[:2] == b"PK"

    def test_pdf_valid(self, gaps):
        from src.brief_export import render_pdf

        data = render_pdf(self._brief(gaps))
        assert data[:5] == b"%PDF-"
        assert len(data) > 500
