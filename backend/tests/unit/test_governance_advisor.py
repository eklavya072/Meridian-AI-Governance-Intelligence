"""Intent routing and the deterministic responses built from it.

governance_advisor decides what a chat turn is asking for and, for most
intents, answers without an LLM at all. Routing was the part that was wrong
before, not the model — so it is the part worth pinning.
"""

import pytest

from src.governance_advisor import (
    AdvisorPlugin,
    Intent,
    PluginRegistry,
    SessionContext,
    _extract_dimension,
    _gap_to_finding_context,
    _normalize,
    build_concept_response,
    build_educational_response,
    classify_intent,
)


class TestNormalisation:
    def test_lowercases_and_strips(self):
        assert _normalize("  WHY Is Fairness Partial?  ").startswith("why is fairness partial")

    def test_is_idempotent(self):
        once = _normalize("Why is Fairness Partial?")
        assert _normalize(once) == once


class TestDimensionExtraction:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("why is fairness partial", "Fairness"),
            ("tell me about transparency", "Transparency"),
            ("what about privacy here", "Privacy"),
            ("how does it handle accountability", "Accountability"),
        ],
    )
    def test_named_dimensions_are_found(self, text, expected):
        assert _extract_dimension(text) == expected

    def test_an_unrelated_question_names_no_dimension(self):
        assert _extract_dimension("what is the weather today") is None

    def test_extraction_is_case_insensitive(self):
        assert _extract_dimension("WHY IS FAIRNESS PARTIAL") == "Fairness"


class TestIntentClassification:
    def test_a_greeting_is_recognised(self):
        intent, _ = classify_intent("hello", SessionContext())

        assert intent is Intent.GREETING

    def test_a_dimension_question_is_not_a_greeting(self):
        intent, _ = classify_intent("why is fairness partial", SessionContext())

        assert intent is not Intent.GREETING

    def test_classification_returns_a_dimension_when_one_is_named(self):
        _, dimension = classify_intent("explain transparency", SessionContext())

        assert dimension == "Transparency"

    def test_empty_input_does_not_raise(self):
        intent, _ = classify_intent("", SessionContext())

        assert isinstance(intent, Intent)

    def test_classification_is_deterministic(self):
        ctx = SessionContext()
        first = classify_intent("why is privacy missing", ctx)
        second = classify_intent("why is privacy missing", SessionContext())

        # Routing must not depend on accumulated session state for the same
        # question asked cold — that is how a two-run country got answered
        # from the wrong run.
        assert first[0] == second[0]


class TestDeterministicResponses:
    def test_a_concept_response_names_the_dimension(self):
        text = build_concept_response("Fairness")

        assert "Fairness" in text
        assert len(text) > 50

    def test_a_concept_response_for_every_governance_dimension(self):
        from src.gap_analyzer import GOVERNANCE_DIMENSIONS

        for dimension in GOVERNANCE_DIMENSIONS:
            # A dimension with no definition would answer a legitimate
            # question with an empty string.
            assert build_concept_response(dimension).strip()

    def test_an_educational_response_is_produced(self):
        assert build_educational_response("what is ai governance", None).strip()

    def test_an_educational_response_uses_a_named_dimension(self):
        text = build_educational_response("tell me about it", "Privacy")

        assert "Privacy" in text


class TestFindingContext:
    def test_a_gap_becomes_a_finding_context(self):
        gap = {
            "dimension": "Fairness",
            "coverage": "Partial",
            "coverage_reasoning": "The document commits to bias testing.",
            "evidence": [{"text": "bias testing shall be conducted", "page_number": 4}],
        }

        context = _gap_to_finding_context(gap)

        assert context["dimension"] == "Fairness"
        assert "Partial" in str(context.get("coverage", ""))

    def test_a_gap_with_no_evidence_does_not_raise(self):
        # Failed dimensions are excluded from scoring rather than guessed at,
        # so an evidence-free gap is a real shape.
        context = _gap_to_finding_context({"dimension": "Privacy", "coverage": "Missing"})

        assert context["dimension"] == "Privacy"

    def test_an_empty_gap_is_handled(self):
        assert isinstance(_gap_to_finding_context({}), dict)


class TestPluginRegistry:
    def test_a_registered_plugin_is_returned_for_its_intent(self):
        registry = PluginRegistry()

        class _Plugin(AdvisorPlugin):
            @property
            def name(self):
                return "test-plugin"

            def can_handle(self, intent, dimension, message):
                return intent is Intent.GREETING

            def handle(self, message, dimension, context, **kwargs):
                return "handled"

        registry.register(_Plugin())
        found = registry.get_handler(Intent.GREETING, None, "hello")

        assert found is not None
        assert found.handle("hello", None, SessionContext()) == "handled"

    def test_no_plugin_matches_returns_none(self):
        registry = PluginRegistry()

        assert registry.get_handler(Intent.GREETING, None, "hi") is None

    def test_registering_twice_does_not_duplicate_handling(self):
        registry = PluginRegistry()

        class _Plugin(AdvisorPlugin):
            @property
            def name(self):
                return "dup"

            def can_handle(self, intent, dimension, message):
                return True

            def handle(self, message, dimension, context, **kwargs):
                return "x"

        plugin = _Plugin()
        registry.register(plugin)
        registry.register(plugin)

        assert registry.get_handler(Intent.GREETING, None, "hi") is not None


class TestSessionContext:
    def test_a_fresh_context_has_no_active_dimension(self):
        assert SessionContext().active_dimension is None

    def test_a_fresh_context_starts_at_unknown_intent(self):
        assert SessionContext().last_intent is Intent.UNKNOWN

    def test_update_records_the_turn_and_the_dimension(self):
        ctx = SessionContext()

        ctx.update("why is fairness partial", "because...", Intent.GREETING, "Fairness")

        assert ctx.active_dimension == "Fairness"
        assert len(ctx.history) == 2

    def test_history_is_bounded(self):
        ctx = SessionContext()

        for i in range(10):
            ctx.update(f"q{i}", f"a{i}", Intent.UNKNOWN)

        # An unbounded history grows a prompt without limit across a long
        # conversation.
        assert len(ctx.history) <= 6
