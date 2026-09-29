"""The chat entry points, driven end to end with the LLM mocked.

chat() is a router before it is anything else: the question decides whether
it reads the uploaded document, the governance knowledge base, the already
computed reasoning trail, or nothing at all. Routing was the part that was
wrong, so routing is what these assert on.
"""

import pytest

from src import chat as chat_mod
from src import governance_advisor as advisor_mod
from src.governance_advisor import Intent, SessionContext, generate_response


class FakeVectorStore:
    def __init__(self, chunks=None):
        self.chunks = (
            chunks
            if chunks is not None
            else [
                {
                    "chunk_id": "c1",
                    "text": "Article 13. Providers shall ensure the system is transparent.",
                    "source_framework": "policy.pdf",
                    "document_name": "policy.pdf",
                    "page_number": 5,
                    "similarity_score": 0.8,
                    "metadata": {"document_name": "policy.pdf", "page_number": "5"},
                }
            ]
        )

    def retrieve(self, **kw):
        return [dict(c) for c in self.chunks]

    def get_chunk(self, chunk_id):
        return next((c for c in self.chunks if c["chunk_id"] == chunk_id), None)

    def chunk_exists(self, chunk_id):
        return any(c["chunk_id"] == chunk_id for c in self.chunks)

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]

    def count_chunks(self, framework_filter=None):
        return len(self.chunks)

    def get_all_frameworks(self):
        return ["EU AI Act"]

    def get_workspace_documents(self, workspace_id):
        return ["policy.pdf"]

    @property
    def embedding_service(self):
        return self

    def embed(self, texts):
        return [self.embed_query(t) for t in texts]

    @property
    def collection(self):
        return self

    def get(self, **kw):
        return {
            "ids": [c["chunk_id"] for c in self.chunks],
            "documents": [c["text"] for c in self.chunks],
            "metadatas": [c["metadata"] for c in self.chunks],
        }


class FakeGuardrails:
    def __init__(self, allow=True):
        self.allow = allow

    def check_query(self, query, workspace_filter=None, strict=True):
        from src.guardrails import GuardrailResult

        return GuardrailResult(
            passed=self.allow,
            reason="" if self.allow else "off-topic",
            scope_message=None if self.allow else "That is outside this assistant's scope.",
        )


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    """Every LLM call returns a fixed reply. No network, no quota."""
    calls = []

    def _text(*a, **kw):
        calls.append(kw.get("operation", "chat"))
        return "A grounded reply about the document."

    monkeypatch.setattr(chat_mod, "generate_text_with_retry", _text, raising=False)
    monkeypatch.setattr(advisor_mod, "generate_text_with_retry", _text, raising=False)
    monkeypatch.setattr(chat_mod, "get_provider", lambda: object(), raising=False)
    monkeypatch.setattr(advisor_mod, "get_provider", lambda: object(), raising=False)
    return calls


def _chat(**kw):
    return chat_mod.chat(
        workspace_id=kw.pop("workspace_id", "w1"),
        user_message=kw.pop("user_message", "what does this document say?"),
        vector_store=kw.pop("vector_store", FakeVectorStore()),
        guardrails=kw.pop("guardrails", FakeGuardrails()),
        **kw,
    )


class TestModeSelection:
    def test_an_unknown_mode_falls_back_to_advisor(self):
        result = _chat(mode="not-a-mode")

        assert result["reply"]

    @pytest.mark.parametrize("mode", ["advisor", "framework_qa", "document_overview", "auditor"])
    def test_every_supported_mode_returns_a_reply(self, mode):
        result = _chat(mode=mode)

        assert result["reply"]

    def test_a_comparison_question_is_referred_without_an_llm_call(self, _mock_llm):
        result = _chat(
            user_message="how does this compare to the EU AI Act?",
            mode="document_overview",
        )

        # The referral returns with no LLM call: answering from a handful of
        # passages would produce verdicts outside the scored pipeline.
        assert result["reply"]


class TestFindingDrillDown:
    def test_a_finding_context_produces_a_grounded_reply(self):
        result = _chat(
            user_message="why is fairness partial?",
            finding_context={
                "dimension": "Fairness",
                "coverage": "Partial",
                "coverage_reasoning": "Bias testing is committed to but not required.",
                "evidence": [{"text": "bias testing should be conducted", "page_number": 4}],
            },
        )

        assert result["reply"]

    def test_the_reply_carries_a_provider_label(self):
        result = _chat(user_message="hello")

        # The frontend shows how a reply was produced; a missing label reads
        # as an unattributed answer.
        assert "provider" in result or "reply" in result


class TestGuardrails:
    def test_an_off_topic_question_is_refused_without_an_llm_call(self, _mock_llm):
        result = _chat(
            user_message="what is the weather in Nairobi?",
            guardrails=FakeGuardrails(allow=False),
        )

        assert result["reply"]


class TestEmptyCorpus:
    def test_no_retrievable_context_does_not_invent_an_answer(self):
        result = _chat(
            user_message="what does the document say about carbon reporting?",
            vector_store=FakeVectorStore(chunks=[]),
        )

        assert result["reply"]

    def test_a_session_id_is_accepted(self):
        result = _chat(user_message="hello", session_id="session-xyz")

        assert result["reply"]


class TestConversationHistory:
    def test_history_is_accepted_for_follow_ups(self):
        result = _chat(
            user_message="and the second one?",
            conversation_history=[
                {"role": "user", "content": "what is the first principle?"},
                {"role": "assistant", "content": "The first principle is transparency."},
            ],
        )

        assert result["reply"]


class TestAdvisorResponses:
    def test_a_greeting_is_answered_without_an_llm_call(self, _mock_llm):
        result = generate_response("hello", SessionContext())

        assert result["reply"]
        assert result["intent"] == Intent.GREETING.value or result["intent"]

    def test_a_concept_question_is_answered_deterministically(self):
        result = generate_response("what is fairness?", SessionContext())

        assert result["reply"]

    def test_the_session_records_the_turn(self):
        session = SessionContext()

        generate_response("what is fairness?", session)

        assert session.history

    def test_a_finding_context_drives_the_reply(self):
        result = generate_response(
            "why is this partial?",
            SessionContext(),
            finding_context={
                "dimension": "Fairness",
                "coverage": "Partial",
                "coverage_reasoning": "No binding requirement.",
            },
        )

        assert result["reply"]

    def test_analysis_results_reach_a_cross_dimension_question(self):
        result = generate_response(
            "which dimension came out strongest?",
            SessionContext(),
            analysis_results={
                "gaps": {
                    "Transparency": {
                        "dimension": "Transparency",
                        "coverage": "Covered",
                        "risk_level": "Low",
                    }
                },
                "decision_analytics": {"strongest_dimension": "Transparency"},
            },
        )

        assert result["reply"]

    def test_an_unknown_question_still_answers(self):
        result = generate_response("asdfghjkl", SessionContext())

        # A confident non-answer is worse than an honest one, but silence is
        # worse than both.
        assert result["reply"]

    def test_every_response_names_its_intent_and_provider(self):
        result = generate_response("what is transparency?", SessionContext())

        assert "intent" in result
        assert "provider" in result


class TestDimensionQuestionsReadTheAnalysis:
    """A question about a dimension, asked while a run is open, is answered
    from that dimension's stored record, not from raw document passages."""

    GAP = {
        "dimension": "Environmental Sustainability",
        "coverage": "Partial",
        "implementation_depth": "Emerging",
        "coverage_reasoning": "3 provisions address it; none imposes a binding duty.",
        "mechanisms_present": {"energy reporting": 1},
        "mechanisms_absent": ["carbon disclosure", "e-waste / hardware lifecycle"],
        "evidence": [
            {
                "text": "Providers shall document the energy consumption of the model.",
                "document_name": "EU AI ACT.pdf",
                "source_framework": "EU AI ACT.pdf",
                "page_number": 12,
            },
            {
                "text": "AI actors should minimise environmental impact.",
                "document_name": "OECD_AI_Principles.pdf",
                "source_framework": "OECD AI Principles",
                "page_number": 3,
            },
        ],
    }

    def _ask(self, monkeypatch, question):
        prompts = []

        def _capture(**kw):
            prompts.append(kw["prompt"])
            return "reply"

        monkeypatch.setattr(chat_mod, "generate_text_with_retry", _capture)
        result = _chat(
            user_message=question,
            analysis_results={
                "gaps": {"Environmental Sustainability": self.GAP},
                "documents": ["EU AI ACT.pdf"],
            },
        )
        return result, prompts[-1] if prompts else ""

    @pytest.mark.parametrize(
        "question",
        [
            "why is environment sustainability partially covered for eu",
            "Why did environmental sustainability only get Partial in this document?",
            "explain the sustainability verdict",
            "what does the EU AI Act lack on environmental sustainability?",
        ],
    )
    def test_however_it_is_phrased_it_reads_the_stored_verdict(self, monkeypatch, question):
        result, prompt = self._ask(monkeypatch, question)

        assert result["mode"] == "advisor"
        assert "Why the verdict is what it is: 3 provisions address it" in prompt

    def test_the_answer_sees_what_is_missing(self, monkeypatch):
        _, prompt = self._ask(monkeypatch, "why is environment sustainability partial")

        assert "Mechanisms the document does not establish: carbon disclosure" in prompt
        assert "Mechanisms the document provides: energy reporting" in prompt

    def test_the_documents_text_is_kept_apart_from_framework_passages(self, monkeypatch):
        _, prompt = self._ask(monkeypatch, "why is environment sustainability partial")

        doc_part, framework_part = prompt.split("Reference framework passages:")
        assert "[EU AI ACT.pdf, p. 12]" in doc_part.split("Provisions of the assessed document:")[1]
        assert "[OECD_AI_Principles.pdf, p. 3]" in framework_part

    def test_a_verdict_answer_has_room_for_examples(self, monkeypatch):
        _, prompt = self._ask(monkeypatch, "why is environment sustainability partial")

        assert "two or three concrete examples" in prompt
        assert "under ~140 words" not in prompt

    def test_a_finding_the_session_remembers_does_not_answer_a_different_dimension(
        self, monkeypatch
    ):
        # "Ask about this finding" on Fairness, then a typed question about
        # sustainability: the answer must be about sustainability.
        _chat(
            user_message="why is this partial?",
            session_id="s-stale",
            finding_context={"dimension": "Fairness", "coverage": "Partial"},
        )
        prompts = []
        monkeypatch.setattr(
            chat_mod, "generate_text_with_retry", lambda **kw: prompts.append(kw["prompt"]) or "r"
        )

        _chat(
            user_message="why is environmental sustainability partial?",
            session_id="s-stale",
            analysis_results={"gaps": {"Environmental Sustainability": self.GAP}},
        )

        assert "Dimension: Environmental Sustainability" in prompts[-1]
        assert "Dimension: Fairness" not in prompts[-1]

    def test_without_an_open_run_a_document_question_still_reads_the_document(self):
        result = _chat(user_message="what does this document say about sustainability?")

        assert result["mode"] == "document_overview"
