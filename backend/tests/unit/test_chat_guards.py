"""Guards that must hold on the chat surface, not only on gap analysis.

A check that runs on one surface is not a property of the system. Chat
verified QUOTED sources but never the article and recital NUMBERS it wrote
into prose — the same failure that produced four flagged citations on a live
EU AI Act run, one of them pointing at an article of a different regulation.
"""

import ast
import pathlib

import pytest

CHAT = pathlib.Path(__file__).resolve().parents[2] / "src" / "chat.py"


class TestNarrativeCitationCheckIsWired:
    def test_chat_uses_the_shared_classifier(self):
        source = CHAT.read_text()
        assert "classify_narrative_citations" in source, (
            "Chat must run the same article/recital number check as gap "
            "analysis, using the shared helper — not a second copy of it."
        )

    def test_chat_exposes_both_severities(self):
        source = CHAT.read_text()
        assert 'result["fabricated_citations"]' in source
        assert 'result["unverifiable_citations"]' in source

    def test_document_fetch_is_lazy(self):
        """The whole-document pull must sit behind the cheap regex pass."""
        source = CHAT.read_text()
        block = source[source.index("Narrative citation numbers") :]
        block = block[: block.index('result["reply"]')]
        guard = block.index("find_unverifiable_citations")
        fetch = block.index("vector_store.collection.get")
        assert guard < fetch, (
            "Fetching every chunk of the workspace document on every chat "
            "turn is only acceptable when a citation was actually flagged."
        )


class TestSessionContextIsBounded:
    def test_lru_eviction_keeps_the_map_bounded(self):
        import src.chat as chat

        chat._session_contexts.clear()
        limit = chat._SESSION_CONTEXT_LIMIT
        for i in range(limit + 20):
            chat._get_session(f"session-{i}")
        assert len(chat._session_contexts) == limit
        assert "session-0" not in chat._session_contexts
        assert f"session-{limit + 19}" in chat._session_contexts
        chat._session_contexts.clear()

    def test_reuse_refreshes_recency(self):
        """An active conversation must not be evicted by newer idle ones."""
        import src.chat as chat

        chat._session_contexts.clear()
        limit = chat._SESSION_CONTEXT_LIMIT
        first = chat._get_session("keep-me")
        for i in range(limit - 1):
            chat._get_session(f"filler-{i}")
        chat._get_session("keep-me")  # touch it
        for i in range(10):
            chat._get_session(f"newer-{i}")
        assert "keep-me" in chat._session_contexts
        assert chat._get_session("keep-me") is first
        chat._session_contexts.clear()

    def test_returns_the_same_context_for_one_session(self):
        import src.chat as chat

        chat._session_contexts.clear()
        assert chat._get_session("s") is chat._get_session("s")
        chat._session_contexts.clear()
