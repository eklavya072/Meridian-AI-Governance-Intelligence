"""
Unit tests for guardrails (out-of-scope input detection).
"""

from unittest.mock import MagicMock, patch

import pytest

from src.guardrails import (
    GREETING_PATTERNS,
    OFF_TOPIC_PATTERNS,
    SCOPE_MESSAGE,
    Guardrails,
)


class MockVectorStore:
    def __init__(self, return_results=True, similarity=0.8):
        self.return_results = return_results
        self.similarity = similarity

    def retrieve(self, query, top_k=5, framework_filter=None, workspace_filter=None):
        if not self.return_results:
            return []
        return [
            {
                "chunk_id": "mock_1",
                "text": "Some policy content about AI governance.",
                "metadata": {"framework": "OECD", "page_number": "5"},
                "similarity_score": self.similarity,
            }
            for _ in range(top_k)
        ]


class TestGreetingDetection:
    def test_hello_detected(self):
        vs = MockVectorStore()
        g = Guardrails(vs)
        result = g.check_query("hello")
        assert not result.passed
        assert result.reason == "greeting_detected"

    def test_hi_detected(self):
        vs = MockVectorStore()
        g = Guardrails(vs)
        result = g.check_query("Hi there")
        assert not result.passed

    def test_good_morning_detected(self):
        vs = MockVectorStore()
        g = Guardrails(vs)
        result = g.check_query("Good morning!")
        assert not result.passed

    def test_policy_query_not_rejected(self):
        vs = MockVectorStore()
        g = Guardrails(vs)
        result = g.check_query("What are the transparency requirements for AI systems?")
        assert result.passed


class TestOffTopicDetection:
    def test_joke_request_rejected(self):
        vs = MockVectorStore()
        g = Guardrails(vs)
        result = g.check_query("Tell me a joke")
        assert not result.passed
        assert result.reason == "off_topic_detected"

    def test_weather_query_rejected(self):
        vs = MockVectorStore()
        g = Guardrails(vs)
        result = g.check_query("What is the weather today?")
        assert not result.passed

    def test_policy_query_not_rejected(self):
        vs = MockVectorStore()
        g = Guardrails(vs)
        result = g.check_query("How does the OECD address risk management?")
        assert result.passed


class TestScopeMessage:
    def test_scope_message_on_rejection(self):
        vs = MockVectorStore()
        g = Guardrails(vs)
        result = g.check_query("hello")
        assert result.scope_message == SCOPE_MESSAGE


class TestNoRetrievalResults:
    def test_no_results_rejected(self):
        vs = MockVectorStore(return_results=False)
        g = Guardrails(vs)
        result = g.check_query("Some random query about nothing")
        assert not result.passed
        assert result.reason == "no_relevant_documents_found"

    def test_low_similarity_rejected(self):
        vs = MockVectorStore(return_results=True, similarity=0.1)
        g = Guardrails(vs)
        result = g.check_query("What is the meaning of life?")
        assert not result.passed
        assert "similar" in (result.reason or "")


@pytest.mark.parametrize(
    "question",
    [
        "Highlight the main obligations on providers",
        "History of the EU AI Act?",
        "Supervisory authorities: what powers do they have?",
        "Your scoring: why five depth stages?",
        "How are you deciding what counts as binding?",
        "Hi, what does NIST say about bias?",
    ],
)
def test_a_question_that_starts_like_a_greeting_is_not_one(question):
    """Prefix matching with no word boundary answered these with a hello."""
    result = Guardrails(MockVectorStore()).check_query(question, strict=False)
    assert result.passed
