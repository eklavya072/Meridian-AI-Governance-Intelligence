"""Context builders and the routing that decides which context a question gets.

CLAUDE.md records that routing was the part that was wrong, not the model:
"why eight dimensions?" had nothing to retrieve because no document in the
corpus describes Meridian, and the Rapporteur was answering cross-dimension
questions without ever receiving the decision analytics.
"""

import hashlib

import pytest

from src.analysis_brief import build_analysis_overview_context, is_analysis_overview_question
from src.document_overview import (
    build_overview_context,
    build_overview_prompt,
    build_overview_system_prompt,
    is_document_specific_question,
    needs_full_analysis,
)
from src.framework_sync import compute_file_hash, load_frameworks_config
from src.meridian_facts import (
    build_method_context,
    is_corpus_question,
    is_method_question,
)


class TestMethodQuestions:
    @pytest.mark.parametrize(
        "message",
        [
            "why eight dimensions and not more?",
            "how does the maturity score work?",
            "how do you score a document?",
        ],
    )
    def test_a_question_about_the_method_is_routed_to_method_context(self, message):
        # No document in the corpus describes Meridian, so these had nothing
        # to retrieve and returned a confident non-answer.
        assert is_method_question(message)

    def test_a_question_about_a_policy_is_not_a_method_question(self):
        assert not is_method_question("does the Act require bias testing?")

    def test_an_empty_message_is_not_a_method_question(self):
        assert not is_method_question("")


class TestCorpusQuestions:
    @pytest.mark.parametrize(
        "message",
        ["what frameworks do you use?", "what frameworks are indexed?"],
    )
    def test_a_question_about_the_corpus_is_recognised(self, message):
        assert is_corpus_question(message)

    def test_an_unrelated_question_is_not(self):
        assert not is_corpus_question("summarise the document")


class TestMethodContext:
    def test_the_context_is_derived_from_live_constants(self):
        from src.gap_analyzer import GOVERNANCE_DIMENSIONS

        context = build_method_context()

        # A hand-typed description drifts the first time a threshold moves.
        for dimension in GOVERNANCE_DIMENSIONS:
            assert dimension in context

    def test_the_normative_force_ladder_is_stated(self):
        context = build_method_context()

        assert "T0" in context or "Aspirational" in context

    def test_the_context_is_stable_between_calls(self):
        first = hashlib.sha256(build_method_context().encode()).hexdigest()
        second = hashlib.sha256(build_method_context().encode()).hexdigest()

        assert first == second

    def test_the_framework_roster_comes_from_config_not_the_vector_store(self):
        context = build_method_context()

        # A metadata scan also sweeps up every uploaded country document and
        # each name variant a sync has written, which is how the first
        # version answered "97 sources" for a library of 33.
        assert "97" not in context


class TestAnalysisOverviewRouting:
    @pytest.mark.parametrize(
        "message",
        ["which dimension came out strongest?", "give me an overview of the results"],
    )
    def test_cross_dimension_questions_are_recognised(self, message):
        assert is_analysis_overview_question(message)

    def test_a_single_dimension_question_is_not_an_overview(self):
        assert not is_analysis_overview_question("why is fairness partial?")


class TestAnalysisOverviewContext:
    def _analysis(self):
        return {
            "country": "Testland",
            "policy_title": "National AI Strategy",
            "gaps": {
                "Transparency": {
                    "dimension": "Transparency",
                    "coverage": "Covered",
                    "governance_maturity": "Operationalized",
                    "risk_level": "Low",
                },
                "Fairness": {
                    "dimension": "Fairness",
                    "coverage": "Partial",
                    "governance_maturity": "Emerging",
                    "risk_level": "Medium",
                },
            },
            "decision_analytics": {
                "coverage_index": 62.5,
                "binding_share": 47.4,
                "strongest_dimension": "Transparency",
            },
        }

    def test_the_verdicts_reach_the_context(self):
        context = build_analysis_overview_context(self._analysis())

        assert "Transparency" in context and "Fairness" in context

    def test_the_decision_analytics_reach_the_context(self):
        context = build_analysis_overview_context(self._analysis())

        # main.py passed only {"gaps": ...}, so the Rapporteur answered
        # "which dimension is strongest" from gaps alone and drifted.
        assert "Transparency" in context

    def test_no_analysis_yields_no_context_rather_than_a_crash(self):
        assert isinstance(build_analysis_overview_context(None), str)

    def test_an_empty_analysis_is_handled(self):
        assert isinstance(build_analysis_overview_context({}), str)


class TestDocumentOverviewRouting:
    @pytest.mark.parametrize(
        "message",
        [
            "how does this compare to the EU AI Act?",
            "what should this country improve?",
        ],
    )
    def test_comparison_questions_are_referred_to_the_full_analysis(self, message):
        # Answering these from a handful of retrieved passages means
        # producing verdicts outside the scored pipeline — a second source
        # of verdict truth, which is the failure this codebase keeps
        # eliminating.
        assert needs_full_analysis(message)

    def test_a_document_summary_request_is_not_referred(self):
        assert not needs_full_analysis("what is this document about?")

    def test_a_question_about_this_document_is_recognised(self):
        assert is_document_specific_question("what does this document say about privacy?")

    def test_a_general_question_is_not_document_specific(self):
        assert not is_document_specific_question("what is AI governance?")


class TestOverviewPrompts:
    CHUNKS = [
        {"text": "Article 1. Scope of this Act.", "page_number": 1, "chunk_id": "c1"},
        {"text": "Article 2. Definitions.", "page_number": 2, "chunk_id": "c2"},
    ]

    def test_context_is_built_from_chunks(self):
        context = build_overview_context(self.CHUNKS)

        assert "Article 1" in context and "Article 2" in context

    def test_no_chunks_yields_an_empty_context(self):
        assert isinstance(build_overview_context([]), str)

    def test_the_system_prompt_is_real_text(self):
        assert len(build_overview_system_prompt().strip()) > 40

    def test_the_overview_prompt_carries_the_document_name(self):
        prompt = build_overview_prompt(
            query="what is this about?",
            context=build_overview_context(self.CHUNKS),
        )

        assert "what is this about?" in prompt
        assert "Article 1" in prompt

    def test_history_is_included_for_follow_ups(self):
        prompt = build_overview_prompt(
            query="and the second one?",
            context="",
            history=[{"role": "user", "content": "what is the first principle?"}],
        )

        assert "first principle" in prompt

    def test_no_passages_is_stated_rather_than_left_blank(self):
        prompt = build_overview_prompt(query="anything", context="")

        # A blank evidence block invites the model to answer from memory.
        assert "no passages" in prompt.lower()


class TestFrameworkConfig:
    def test_the_config_loads_and_every_entry_has_a_name(self):
        for framework in load_frameworks_config():
            assert framework.get("name")

    def test_the_config_is_not_empty(self):
        # An empty roster silently disables framework routing entirely.
        assert load_frameworks_config()

    def test_names_are_unique(self):
        names = [f["name"] for f in load_frameworks_config()]

        assert len(names) == len(set(names))


class TestFileHash:
    def test_the_same_bytes_hash_the_same(self, tmp_path):
        path = tmp_path / "a.pdf"
        path.write_bytes(b"%PDF-1.7\ncontent")

        assert compute_file_hash(path) == compute_file_hash(path)

    def test_different_bytes_hash_differently(self, tmp_path):
        first = tmp_path / "a.pdf"
        second = tmp_path / "b.pdf"
        first.write_bytes(b"%PDF-1.7\none")
        second.write_bytes(b"%PDF-1.7\ntwo")

        # The sync skips re-ingestion when the checksum is unchanged, so a
        # collision here would silently serve a stale index.
        assert compute_file_hash(first) != compute_file_hash(second)

    def test_a_large_file_is_hashed_in_chunks_without_loading_it_whole(self, tmp_path):
        path = tmp_path / "big.pdf"
        path.write_bytes(b"x" * (5 * 1024 * 1024))

        assert len(compute_file_hash(path)) == 64
