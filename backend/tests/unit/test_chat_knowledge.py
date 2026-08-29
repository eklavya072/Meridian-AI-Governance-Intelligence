"""Routing and context tests for the three things chat could not do before:
explain Meridian's own method, reason across a whole analysis, and decline a
question that only a scored run can answer honestly.

All three failed the same way in production — a confident non-answer — so the
assertions here are mostly about which context a question ATTRACTS, not about
model output. Routing is the part that was wrong; the model was never the
problem once it had the right material in front of it.
"""

import pytest

from src.analysis_brief import (
    build_analysis_overview_context,
    is_analysis_overview_question,
)
from src.document_overview import (
    is_document_specific_question,
    needs_full_analysis,
)
from src.meridian_facts import (
    build_method_context,
    is_corpus_question,
    is_method_question,
)


class TestMethodQuestions:
    @pytest.mark.parametrize("q", [
        "Why do you use 8 dimensions and not more?",
        "why not add more dimensions",
        "How do you decide something is Covered rather than Partial?",
        "what does binding force mean",
        "what is your methodology",
        "do you rank countries against each other",
        "what are your limitations",
        "how is the maturity index calculated",
    ])
    def test_self_referential_questions_are_method_questions(self, q):
        assert is_method_question(q)

    @pytest.mark.parametrize("q", [
        "What is transparency in AI?",
        "How does the EU AI Act classify high-risk AI?",
        "What does NIST say about bias?",
        "summarize this policy",
    ])
    def test_subject_matter_questions_are_not(self, q):
        assert not is_method_question(q)

    @pytest.mark.parametrize("q", [
        "What frameworks do you use?",
        "why not add more frameworks",
        "which frameworks are indexed",
    ])
    def test_corpus_questions_want_the_roster(self, q):
        # Corpus questions are a subset of method questions — both need the
        # method brief, only these pay for the roster lookup.
        assert is_corpus_question(q) and is_method_question(q)

    def test_corpus_lookup_is_not_paid_for_unnecessarily(self):
        assert not is_corpus_question("why eight dimensions")

    def test_method_context_is_derived_not_hardcoded(self):
        ctx = build_method_context()
        # Counts and labels come from the live constants; if a stage, tier or
        # mechanism moves, this text must move with it.
        for marker in [
            "THE 8 DIMENSIONS",
            "Environmental Sustainability",
            "T0 Aspirational",
            "T4 Enforceable",
            "Institutionalized (100)",
            "Delegated (65)",
            "45 framework-required mechanisms",
        ]:
            assert marker in ctx, marker

    def test_method_context_states_the_limits(self):
        ctx = build_method_context()
        assert "does not rank countries" in ctx.lower()
        assert "AI for Government" in ctx


class TestFullAnalysisReferral:
    @pytest.mark.parametrize("q", [
        "How does this fair with the EU AI Act?",
        "How does this policy compare with the EU AI Act?",
        "What should improve?",
        "whats the best implementation plan",
        "is this policy compliant",
        "are these guidelines adequate",
    ])
    def test_scoring_questions_are_referred(self, q):
        assert needs_full_analysis(q)

    @pytest.mark.parametrize("q", [
        "does this pdf deal with ai accountability",
        "where in the pdf does it mention environment rules",
        "summarize this document",
        "what does this say about privacy",
    ])
    def test_plain_document_questions_are_answered_not_referred(self, q):
        assert not needs_full_analysis(q)
        # And they must still reach the document, which is the marker list's
        # job — "this pdf" phrasing used to miss it entirely.
        assert is_document_specific_question(q)


class TestAnalysisOverview:
    @pytest.mark.parametrize("q", [
        "Which is the strongest dimension and why?",
        "what are the main gaps in this analysis",
        "how many dimensions are covered",
        "what is the coverage index",
        "rank the dimensions",
    ])
    def test_cross_dimension_questions_want_the_whole_run(self, q):
        assert is_analysis_overview_question(q)

    @pytest.mark.parametrize("q", [
        "why is safety partial",
        "what does NIST say about bias",
    ])
    def test_single_dimension_questions_do_not(self, q):
        # The per-dimension generator handles these and does it better; the
        # overview would just be noise in the prompt.
        assert not is_analysis_overview_question(q)

    def test_overview_context_carries_the_figures_that_were_missing(self):
        results = {
            "country": "Testland",
            "policy_title": "AI Strategy",
            "documents": ["strategy.pdf"],
            "decision_analytics": {
                "covered": 6, "partial": 2, "missing": 0,
                "coverage_index": 71.1, "maturity_index": 78.4,
                "binding_share": 28.1, "mechanisms_met": 32,
                "mechanisms_total": 45, "mechanisms_binding": 9,
                "strongest_dimension": "Accountability",
            },
            "gaps": {
                "Accountability": {
                    "dimension": "Accountability",
                    "coverage": "Covered",
                    "risk_level": "Low",
                    "module_1": {"governance_maturity": "Institutionalized"},
                    "mechanisms_present": {"oversight body": 4, "redress": 3},
                    "mechanisms_absent": ["audit trail"],
                },
                "Privacy": {
                    "dimension": "Privacy",
                    "coverage": "Partial",
                    "risk_level": "Medium",
                    "module_1": {"governance_maturity": "Emerging"},
                    "mechanisms_present": {"consent": 1},
                    "mechanisms_absent": ["purpose limitation"],
                },
            },
        }
        ctx = build_analysis_overview_context(results)
        assert "Testland" in ctx
        assert "Coverage index 71.1" in ctx
        assert "Strongest dimension as computed: Accountability" in ctx
        # Both verdicts present, each with the counts that justify it.
        assert "Accountability: Covered" in ctx
        assert "Privacy: Partial" in ctx
        # Binding is tier >= 3: Accountability's two both qualify, Privacy's
        # single T1 does not — which is exactly why one is Covered and the
        # other Partial.
        assert "2 present (2 binding)" in ctx   # Accountability
        assert "1 present (0 binding)" in ctx   # Privacy
        assert "purpose limitation" in ctx

    def test_no_analysis_yields_no_context(self):
        assert build_analysis_overview_context(None) == ""
        assert build_analysis_overview_context({"gaps": {}}) == ""
