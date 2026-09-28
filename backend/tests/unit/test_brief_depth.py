"""The brief carries the analysis, not a summary of a summary.

Eight dimensions were being compressed into three strength bullets and three
attention bullets, so a reader never saw what was found for any particular
dimension, never saw the sequenced Module 3 roadmap, and never saw the evidence
the verdicts rest on — all of it already computed and already citation-verified.

The extra length is DETERMINISTIC. None of these sections passes through the
LLM, so the brief got longer without the model getting more room to invent.
"""

import pytest

from src.brief_synthesis import (
    build_dimension_assessment,
    build_evidence_base,
    build_implementation_roadmap,
)

GAPS = [
    {
        "dimension": "Accountability",
        "coverage": "Covered",
        "implementation_depth": "Institutionalized",
        "confidence_score": 0.80,
        "risk_basis": "The document imposes 26 binding requirement(s) here, 16 of "
        "them backed by supervisory or enforcement powers.",
        "evidence": [
            {
                "text": "Market surveillance authorities shall have the power to "
                "require corrective action from providers.",
                "verified": True,
            }
        ],
    },
    {
        "dimension": "Environmental Sustainability",
        "coverage": "Partial",
        "implementation_depth": "Emerging",
        "confidence_score": 0.73,
        "risk_basis": "1 binding requirement(s) exist with no enforcement, audit or "
        "redress machinery behind them. Not addressed: carbon "
        "disclosure, e-waste / hardware lifecycle.",
        "evidence": [
            {
                "text": "High-risk AI systems shall be designed and developed with resource "
                "and energy efficiency in mind throughout their lifecycle.",
                "verified": True,
                "document_name": "EU AI Act.pdf",
                "source_framework": "EU AI Act.pdf",
                "page_number": "12",
            },
            {
                "text": "Member States should assess the direct and indirect environmental "
                "impact throughout the AI system life cycle, including its carbon footprint "
                "and energy consumption.",
                "verified": True,
                "document_name": "UNESCO_Recommendation_on_the_Ethics_of_AI.pdf",
                "source_framework": "UNESCO Recommendation on the Ethics of AI",
                "page_number": "30",
            },
            {"text": "short", "verified": True},
            {
                "text": "An unverified passage that must never be quoted in the brief.",
                "verified": False,
            },
        ],
        "module_3": {
            "responsible_agency": "AI Office",
            "phases": [
                {
                    "phase": "Phase 1",
                    "timeline": "0-4 months",
                    "objective": "Establish metrics.",
                    "steps": ["Extend GPAI documentation."],
                },
                {
                    "phase": "Phase 2",
                    "timeline": "4-7 months",
                    "objective": "Operationalise guidance.",
                    "steps": [],
                },
            ],
            "monitoring_checklist": ["Documentation contains energy disclosures."],
        },
    },
    {
        "dimension": "Privacy",
        "coverage": "Insufficient Evidence",
        "analysis_error": "LLM quota exhausted",
    },
]


class TestDimensionAssessment:
    def test_every_dimension_appears(self):
        rows = build_dimension_assessment(GAPS)
        assert [r["dimension"] for r in rows] == [
            "Accountability",
            "Environmental Sustainability",
            "Privacy",
        ]

    def test_absent_mechanisms_are_extracted(self):
        rows = build_dimension_assessment(GAPS)
        env = next(r for r in rows if r["dimension"] == "Environmental Sustainability")
        assert env["absent_mechanisms"] == ["carbon disclosure", "e-waste / hardware lifecycle"]

    def test_absent_list_is_not_also_left_inside_the_basis(self):
        """Both were rendered on consecutive lines before this was stripped."""
        rows = build_dimension_assessment(GAPS)
        env = next(r for r in rows if r["dimension"] == "Environmental Sustainability")
        assert "Not addressed" not in env["basis"]
        assert "no enforcement" in env["basis"]

    def test_a_failed_dimension_is_marked_as_not_assessed(self):
        """A pipeline failure must never read as a finding about the document."""
        rows = build_dimension_assessment(GAPS)
        priv = next(r for r in rows if r["dimension"] == "Privacy")
        assert priv["coverage"] == "Not assessed"
        assert "not a finding about the document" in priv["basis"]


class TestImplementationRoadmap:
    def test_only_dimensions_with_phases_appear(self):
        items = build_implementation_roadmap(GAPS)
        assert [i["dimension"] for i in items] == ["Environmental Sustainability"]

    def test_empty_phases_are_dropped(self):
        """Phase 2 has no steps — an empty phase is noise in a brief."""
        item = build_implementation_roadmap(GAPS)[0]
        assert [p["phase"] for p in item["phases"]] == ["Phase 1"]

    def test_responsible_agency_and_monitoring_survive(self):
        item = build_implementation_roadmap(GAPS)[0]
        assert item["responsible_agency"] == "AI Office"
        assert item["monitoring"] == ["Documentation contains energy disclosures."]

    def test_failed_dimensions_are_excluded(self):
        assert all(i["dimension"] != "Privacy" for i in build_implementation_roadmap(GAPS))


class TestEvidenceBase:
    def test_counts_cover_every_citation(self):
        ev = build_evidence_base(GAPS)
        assert ev["citations_total"] == 5
        assert ev["citations_verified"] == 4

    def test_unverified_passages_are_never_quoted(self):
        ev = build_evidence_base(GAPS)
        for q in ev["representative_quotes"]:
            assert "must never be quoted" not in q["quote"]

    def test_quotes_come_only_from_gapped_dimensions(self):
        ev = build_evidence_base(GAPS)
        assert [q["dimension"] for q in ev["representative_quotes"]] == [
            "Environmental Sustainability"
        ]

    def test_a_framework_passage_is_never_quoted_as_the_countrys_text(self):
        # The UNESCO passage is longer, so "longest verified" alone chose it
        # and printed it under the EU's dimension as if the Act said it.
        ev = build_evidence_base(GAPS, documents=["EU AI Act.pdf"])
        assert [q["source"] for q in ev["representative_quotes"]] == ["EU AI Act, p. 12"]
        assert "resource and energy efficiency" in ev["representative_quotes"][0]["quote"]

    def test_every_rendering_names_the_source(self):
        from src.brief_synthesis import format_evidence_quote

        q = build_evidence_base(GAPS)["representative_quotes"][0]
        assert format_evidence_quote(q).endswith("(EU AI Act, p. 12)")

    def test_trivially_short_fragments_are_skipped(self):
        ev = build_evidence_base(GAPS)
        assert all(len(q["quote"]) > 80 for q in ev["representative_quotes"])

    def test_no_evidence_is_handled(self):
        ev = build_evidence_base([{"dimension": "X", "coverage": "Partial"}])
        assert ev["citations_total"] == 0
        assert ev["representative_quotes"] == []


class TestAbsentMechanismsInTheBrief:
    """The brief read absent mechanisms back out of prose by matching "Not
    addressed:", which the mechanism summary stopped writing — so 22 of the 42
    dimensions with gaps printed none. Japan's Privacy was one of them."""

    def test_they_come_from_the_stored_fields_not_the_prose(self):
        from src.brief_synthesis import _absent_mechanisms

        gap = {
            "dimension": "Privacy",
            "mechanisms_absent": ["data minimisation", "purpose limitation"],
            "risk_basis": "The document imposes 105 binding requirement(s) here.",
        }

        assert _absent_mechanisms(gap) == ["data minimisation", "purpose limitation"]

    def test_only_consensus_gaps_carry_a_count_and_they_lead(self):
        from src.brief_synthesis import _absent_mechanisms

        gap = {
            "dimension": "Safety",
            "mechanisms_absent": ["human failsafe / shutdown", "post-market monitoring"],
            "priority_gaps": [{"mechanism": "post-market monitoring", "expected_by": 24}],
            "framework_corpus_size": 43,
        }

        assert _absent_mechanisms(gap) == [
            "post-market monitoring (expected by 24 of 43 reference instruments)",
            "human failsafe / shutdown",
        ]
