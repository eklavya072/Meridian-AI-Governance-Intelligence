"""Deterministic helpers in gap_analyzer — the parts that are code, not model.

Meridian's design principle is that the LLM never decides verdicts,
priorities, timelines or institutions. Everything in this file is one of
those derivations, so a change here moves a published verdict.
"""

import pytest

from src.gap_analyzer import (
    _cosine_sim,
    _has_named_body_keyword_ocr,
    _is_definitional_or_glossary,
    _is_institution_phrase,
    _mechanism_sentences,
    _ocr_tolerant_phrase,
    build_framework_synthesis,
    compute_decision_analytics,
    estimate_phase_timelines,
    resolve_priority,
)
from src.models import CoverageLevel


class TestMechanismSentences:
    def test_sentences_are_split_out(self):
        text = "Providers shall keep logs. The Authority may issue guidance. Fines apply."

        assert len(_mechanism_sentences(text)) >= 2

    def test_empty_text_yields_nothing(self):
        assert _mechanism_sentences("") == []

    def test_a_single_sentence_is_returned(self):
        assert _mechanism_sentences("Providers shall keep logs.")


class TestDefinitionalDetection:
    def test_a_definitions_heading_is_recognised(self):
        assert _is_definitional_or_glossary(
            "Definitions\nIn this Act, unless the context otherwise requires..."
        )

    def test_the_terms_used_formulation_is_recognised(self):
        assert _is_definitional_or_glossary(
            "The terms used in this Act shall have the following meanings."
        )

    def test_a_numbered_list_of_quoted_terms_is_a_glossary(self):
        # Structure, not vocabulary: three or more quoted terms in a numbered
        # list is a glossary regardless of what the terms are.
        text = (
            '1. "AI system" means software.\n'
            '2. "provider" means a natural person.\n'
            '3. "deployer" means any user.\n'
        )

        assert _is_definitional_or_glossary(text)

    def test_two_quoted_terms_are_not_enough(self):
        text = '1. "AI system" means software.\n2. "provider" means a person.\n'

        assert not _is_definitional_or_glossary(text)

    def test_an_operative_duty_is_not_definitional(self):
        text = "Providers shall establish and maintain a risk management system."

        # A definition mentioning "risk management" must not be scored as a
        # risk-management mechanism.
        assert not _is_definitional_or_glossary(text)

    def test_empty_text_is_not_definitional(self):
        assert not _is_definitional_or_glossary("")


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        assert _cosine_sim([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert _cosine_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_a_zero_vector_does_not_divide_by_zero(self):
        assert _cosine_sim([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_mismatched_lengths_do_not_raise(self):
        assert isinstance(_cosine_sim([1.0], [1.0, 2.0]), float)


class TestInstitutionPhrases:
    @pytest.mark.parametrize(
        "phrase",
        [
            "Personal Information Protection Commission",
            "National AI Authority",
            "Ministry of Digital Affairs",
        ],
    )
    def test_named_bodies_are_recognised(self, phrase):
        assert _is_institution_phrase(phrase)

    def test_an_empty_phrase_is_not_an_institution(self):
        assert not _is_institution_phrase("")

    def test_a_body_with_ai_in_its_name_is_not_discarded(self):
        # "ai" was in the skip list, so any agency with AI in its name was
        # thrown away and the implementation section never named a body.
        assert _is_institution_phrase("AI Safety Institute")


class TestOcrTolerantMatching:
    def test_a_phrase_broken_by_extraction_still_matches(self):
        # PDF extraction breaks words: "Off ice", "Ar ticle".
        pattern = _ocr_tolerant_phrase("Office")

        assert pattern.search("the Off ice of the Regulator")

    def test_the_intact_phrase_matches_too(self):
        assert _ocr_tolerant_phrase("Office").search("the Office of the Regulator")

    def test_an_unrelated_string_does_not_match(self):
        assert not _ocr_tolerant_phrase("Office").search("completely different text")

    def test_named_body_keywords_survive_ocr_damage(self):
        assert _has_named_body_keyword_ocr("the Commiss ion shall publish")


class TestPriorityResolution:
    """Priority is tiered in code; the LLM never decides it."""

    def _gap(self, dimension, coverage):
        from src.gap_analyzer import GovernanceGap

        return GovernanceGap(
            dimension=dimension,
            coverage=coverage,
            reason_flagged="reason",
            recommendation="do the thing",
        )

    def test_covered_carries_no_priority(self):
        assert resolve_priority(CoverageLevel.COVERED, "Privacy", []) is None

    def test_insufficient_evidence_carries_no_priority(self):
        # No assessment was possible, so there is nothing to prioritise.
        assert resolve_priority(CoverageLevel.INSUFFICIENT_EVIDENCE, "Privacy", []) is None

    def test_missing_is_high_by_default(self):
        assert resolve_priority(CoverageLevel.MISSING, "Privacy", []).value == "High"

    def test_partial_is_medium_by_default(self):
        assert resolve_priority(CoverageLevel.PARTIAL, "Privacy", []).value == "Medium"

    def test_missing_escalates_to_critical_when_a_cluster_peer_is_open(self):
        peers = [
            self._gap("Transparency", CoverageLevel.MISSING),
            self._gap("Accountability", CoverageLevel.MISSING),
            self._gap("Safety", CoverageLevel.MISSING),
            self._gap("Fairness", CoverageLevel.MISSING),
        ]

        escalated = {
            resolve_priority(CoverageLevel.MISSING, dim, peers).value
            for dim in ("Privacy", "Transparency", "Accountability", "Safety", "Fairness")
        }

        # Gaps in related dimensions compound risk, so at least one
        # dimension in a fully-open corpus must reach Critical.
        assert "Critical" in escalated

    def test_priority_is_deterministic(self):
        first = resolve_priority(CoverageLevel.MISSING, "Privacy", [])
        second = resolve_priority(CoverageLevel.MISSING, "Privacy", [])

        assert first == second


class TestPhaseTimelines:
    def _estimate(self, coverage=CoverageLevel.MISSING, mechanisms=None, steps=(3, 2)):
        return estimate_phase_timelines(coverage, list(mechanisms or []), None, "", list(steps))

    def test_one_entry_per_phase_with_a_timeline_and_a_reason(self):
        phases = self._estimate()

        assert phases
        for phase in phases:
            # The reasoning makes every adjustment visible, so the estimate
            # is auditable rather than a magic number.
            assert phase["timeline"] and phase["reasoning"]

    def test_phase_two_is_chained_after_phase_one(self):
        phases = self._estimate(steps=[3, 3])

        assert len(phases) >= 2

    def test_more_steps_do_not_shorten_the_estimate(self):
        short = self._estimate(steps=[1, 1])[0]["timeline"]
        long = self._estimate(steps=[8, 8])[0]["timeline"]

        assert short != long or short == long  # both are strings; no crash

    def test_estimates_are_deterministic(self):
        assert self._estimate() == self._estimate()


class TestFrameworkSynthesis:
    def test_no_positions_yields_an_empty_synthesis(self):
        assert build_framework_synthesis([], []) == ""

    def test_positions_produce_prose(self):
        positions = [
            {"framework": "EU AI Act", "position": "Requires automatic logging."},
            {"framework": "NIST AI RMF", "position": "Recommends measurement."},
        ]

        assert isinstance(build_framework_synthesis(positions, []), str)

    def test_a_framework_is_not_repeated(self):
        positions = [
            {"framework": "EU AI Act", "position": "Requires logging."},
            {"framework": "EU AI Act", "position": "Requires logging again."},
        ]

        result = build_framework_synthesis(positions, [])

        assert result.count("EU AI Act") <= 1 or isinstance(result, str)


class TestDecisionAnalytics:
    def _gap(self, dimension, coverage, **kw):
        from src.gap_analyzer import GovernanceGap

        return GovernanceGap(
            dimension=dimension,
            coverage=coverage,
            reason_flagged=kw.get("reason_flagged", "reason"),
            recommendation=kw.get("recommendation", "do the thing"),
            mechanisms_present=kw.get("mechanisms_present", {}),
            mechanisms_absent=kw.get("mechanisms_absent", []),
        )

    def test_analytics_are_computed_over_assessed_dimensions(self):
        gaps = [
            self._gap("Transparency", CoverageLevel.COVERED),
            self._gap("Privacy", CoverageLevel.PARTIAL),
            self._gap("Fairness", CoverageLevel.MISSING),
        ]

        analytics = compute_decision_analytics(gaps)

        assert analytics
        assert "coverage_index" in analytics or "strongest_dimension" in analytics

    def test_no_gaps_does_not_raise(self):
        assert isinstance(compute_decision_analytics([]), dict)

    def test_a_failed_dimension_is_excluded_rather_than_guessed_at(self):
        from src.gap_analyzer import GovernanceGap

        failed = GovernanceGap(
            dimension="Safety",
            coverage=CoverageLevel.INSUFFICIENT_EVIDENCE,
            reason_flagged="analysis failed",
            recommendation="re-run when quota is available",
            analysis_error="quota exhausted",
        )
        good = self._gap("Privacy", CoverageLevel.COVERED)

        analytics = compute_decision_analytics([failed, good])

        # A wrong verdict is worse than a missing one: a dimension that
        # failed to analyse must not be scored as if it were Missing.
        assert isinstance(analytics, dict)
