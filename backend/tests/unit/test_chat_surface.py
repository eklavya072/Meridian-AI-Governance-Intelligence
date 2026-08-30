"""Prompt construction, citation extraction and source matching in chat.

The chat surfaces answer questions about a scored run, so the parts worth
pinning are the ones that decide what reaches the model and what a reader is
shown as a source — not the model's prose.
"""

import pytest

from src import chat as chat_mod
from src.chat import (
    CHAT_MODES,
    _clean_prose_source,
    _source_matches_known_framework,
    build_auditor_greeting,
    build_context_from_retrieval,
    build_drill_down_context,
    build_framework_qa_greeting,
    build_framework_qa_system_prompt,
    build_full_analysis_referral,
    build_system_prompt,
    extract_citations,
)


class TestModes:
    def test_the_mode_list_is_the_one_the_api_accepts(self):
        # main.py whitelists modes when creating a session; a mode here that
        # is missing there silently drops a history filter.
        assert set(CHAT_MODES) == {"advisor", "framework_qa", "document_overview", "auditor"}


class TestPrompts:
    @pytest.mark.parametrize(
        "builder",
        [
            build_system_prompt,
            build_framework_qa_system_prompt,
            build_auditor_greeting,
            build_framework_qa_greeting,
        ],
    )
    def test_every_prompt_builder_returns_real_text(self, builder):
        text = builder()

        assert isinstance(text, str)
        assert len(text.strip()) > 40

    def test_the_system_prompt_refuses_to_agree_with_a_false_premise(self):
        # Asked "why is Human Autonomy partial" on a run where it scored
        # Covered, the model argued the case for Partial. A leading question
        # is the easiest way to get a wrong verdict in front of a reader.
        prompt = build_system_prompt().lower()

        assert "covered" in prompt and "partial" in prompt

    def test_a_referral_is_returned_for_comparison_questions(self):
        with_doc = build_full_analysis_referral(has_document=True)
        without = build_full_analysis_referral(has_document=False)

        # Comparison questions are declined and handed to the Analysis
        # section rather than answered from a handful of passages, which
        # would be a second source of verdict truth.
        assert with_doc.strip() and without.strip()
        assert with_doc != without


class TestRetrievalContext:
    def test_context_is_built_from_retrieved_chunks(self):
        retrieved = [
            {
                "text": "Article 12 requires logging.",
                "source_framework": "EU AI Act",
                "page_number": 5,
                "chunk_id": "c1",
            },
            {
                "text": "Article 13 requires transparency.",
                "source_framework": "EU AI Act",
                "page_number": 6,
                "chunk_id": "c2",
            },
        ]

        context = build_context_from_retrieval(retrieved, top_k=2)

        assert "Article 12" in context
        assert "Article 13" in context

    def test_top_k_bounds_what_reaches_the_prompt(self):
        retrieved = [
            {"text": f"passage {i}", "source_framework": "F", "page_number": i, "chunk_id": f"c{i}"}
            for i in range(10)
        ]

        context = build_context_from_retrieval(retrieved, top_k=3)

        assert "passage 9" not in context

    def test_no_retrieval_produces_empty_context_not_a_crash(self):
        assert isinstance(build_context_from_retrieval([], top_k=5), str)


class TestDrillDownContext:
    def test_a_finding_context_reaches_the_prompt(self):
        context = build_drill_down_context(
            {
                "dimension": "Fairness",
                "coverage": "Partial",
                "coverage_reasoning": "Bias testing is committed to but not required.",
                "evidence": [{"text": "bias testing should be conducted", "page_number": 4}],
            }
        )

        # A typed "why is Fairness Partial" must carry the evidence, not just
        # the verdict — that was the most common phrasing and it reached the
        # model with no reasoning trail.
        assert "Fairness" in context
        assert "bias testing" in context

    def test_an_empty_finding_context_is_handled(self):
        assert isinstance(build_drill_down_context({}), str)


class TestCitationExtraction:
    def test_a_bracketed_source_is_extracted(self):
        citations = extract_citations(
            '[EU AI Act]: "High-risk AI systems shall allow automatic logging."'
        )

        assert citations
        assert citations[0]["source"] == "EU AI Act"
        assert "logging" in citations[0]["quote"]

    def test_a_prose_source_without_brackets_is_also_caught(self):
        # Models write 'Source Name: "quote"' without brackets; over-matching
        # is safe because every quote still passes through verification.
        citations = extract_citations(
            'EU AI Act: "High-risk AI systems shall allow automatic logging."'
        )

        assert citations

    def test_a_quote_too_short_to_verify_is_ignored(self):
        assert extract_citations('[EU AI Act]: "short"') == []

    def test_prose_with_no_citation_yields_none(self):
        assert extract_citations("There is no citation in this sentence.") == []

    def test_extraction_never_raises_on_malformed_markers(self):
        for text in ("[Source:", "[Source: ]", "[]", "[Source: , p. ]"):
            assert isinstance(extract_citations(text), list)


class TestProseSourceCleaning:
    @pytest.mark.parametrize(
        "raw",
        [
            "According to the EU AI Act",
            "as stated in the EU AI Act",
            "the EU AI Act",
            "  EU AI Act  ",
        ],
    )
    def test_leading_filler_is_stripped(self, raw):
        assert _clean_prose_source(raw).strip().startswith("EU AI Act")

    def test_an_empty_source_stays_empty(self):
        assert _clean_prose_source("") == ""


class TestKnownFrameworkMatching:
    def test_an_exact_name_matches(self):
        known = ["UNESCO Recommendation on the Ethics of AI", "NIST AI RMF"]

        assert (
            _source_matches_known_framework("UNESCO Recommendation on the Ethics of AI", known)
            == "UNESCO Recommendation on the Ethics of AI"
        )

    def test_matching_ignores_punctuation_and_case(self):
        # The model writes "Model AI Governance Framework for Agentic AI";
        # the store holds "Model-AI-Governance-Framework-for-Agentic-AI.pdf".
        assert (
            _source_matches_known_framework(
                "model ai governance framework for agentic ai",
                ["Model-AI-Governance-Framework-for-Agentic-AI.pdf"],
            )
            == "Model-AI-Governance-Framework-for-Agentic-AI.pdf"
        )

    def test_a_mid_sentence_mention_resolves_to_the_canonical_name(self):
        known = ["UNESCO Recommendation on the Ethics of AI"]

        assert (
            _source_matches_known_framework(
                "For instance, the UNESCO Recommendation on the Ethics of AI", known
            )
            == "UNESCO Recommendation on the Ethics of AI"
        )

    def test_a_too_short_claim_never_matches(self):
        # "Risk" or "Data" would substring-match a real name by accident.
        assert _source_matches_known_framework("Risk", ["NIST AI Risk Management"]) is None

    def test_prose_that_is_not_a_source_is_rejected(self):
        assert (
            _source_matches_known_framework(
                "Accountability requires evaluating the governance structure",
                ["EU AI Act"],
            )
            is None
        )

    def test_an_unknown_source_does_not_match(self):
        # Better to show no source than to attribute a claim to a framework
        # that was never retrieved.
        assert _source_matches_known_framework("Invented Framework", ["EU AI Act"]) is None

    def test_an_empty_roster_matches_nothing(self):
        assert _source_matches_known_framework("EU AI Act", []) is None


class TestSessionCache:
    def test_a_session_context_is_reused_for_the_same_id(self):
        first = chat_mod._get_session("session-a")
        second = chat_mod._get_session("session-a")

        assert first is second

    def test_different_sessions_do_not_share_context(self):
        assert chat_mod._get_session("session-b") is not chat_mod._get_session("session-c")

    def test_the_cache_is_bounded(self):
        limit = chat_mod._SESSION_CONTEXT_LIMIT

        for i in range(limit + 25):
            chat_mod._get_session(f"overflow-{i}")

        # Unbounded, this grows for the life of the process — one entry per
        # conversation anyone ever starts.
        assert len(chat_mod._session_contexts) <= limit
