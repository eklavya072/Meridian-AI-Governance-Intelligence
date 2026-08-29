from __future__ import annotations

import re

import structlog
from pydantic import BaseModel

from src.vectorstore import VectorStore

logger = structlog.get_logger()

SCOPE_MESSAGE = (
    "This application is designed for policy analysis. "
    "Please upload a policy document or ask a question related to an indexed document."
)

GREETING_PATTERNS = re.compile(
    r"^(hello|hi|hey|good morning|good afternoon|good evening|thanks|thank you|"
    r"how are you|what'?s up|yo|sup|greetings)",
    re.IGNORECASE,
)

OFF_TOPIC_PATTERNS = re.compile(
    r"(what'?s your name|who are you|what can you do|tell me a joke|"
    r"weather|recipe|cook|cooking|sports|game|movie|music|play)",
    re.IGNORECASE,
)

MIN_RETRIEVAL_SIMILARITY = 0.3
MIN_RETRIEVAL_CHUNKS = 2


class GuardrailResult(BaseModel):
    passed: bool
    reason: str | None = None
    scope_message: str | None = None


class Guardrails:
    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store

    def check_query(
        self,
        query: str,
        workspace_filter: list[str] | None = None,
        strict: bool = True,
    ) -> GuardrailResult:
        """Check if a query should be processed.

        In strict mode (default): checks all guardrails including greeting,
        off-topic, and similarity. In non-strict mode: only checks for
        greetings, allowing governance-related questions to pass through
        even if no similar chunks are found.
        """
        if GREETING_PATTERNS.match(query.strip()):
            logger.info("guardrail_greeting_rejected", query=query[:100])
            return GuardrailResult(
                passed=False,
                reason="greeting_detected",
                scope_message=SCOPE_MESSAGE,
            )

        if strict:
            if OFF_TOPIC_PATTERNS.search(query):
                logger.info("guardrail_off_topic_rejected", query=query[:100])
                return GuardrailResult(
                    passed=False,
                    reason="off_topic_detected",
                    scope_message=SCOPE_MESSAGE,
                )

            results = self.vector_store.retrieve(
                query=query,
                top_k=5,
                workspace_filter=workspace_filter,
            )
            if not results:
                logger.info("guardrail_no_retrieval_results", query=query[:100])
                return GuardrailResult(
                    passed=False,
                    reason="no_relevant_documents_found",
                    scope_message=SCOPE_MESSAGE,
                )

            high_similarity = [
                r for r in results if (r.get("similarity_score") or 0) >= MIN_RETRIEVAL_SIMILARITY
            ]
            if len(high_similarity) < MIN_RETRIEVAL_CHUNKS:
                logger.info(
                    "guardrail_insufficient_similarity",
                    query=query[:100],
                    high_similarity_count=len(high_similarity),
                )
                return GuardrailResult(
                    passed=False,
                    reason="query_not_similar_enough_to_indexed_content",
                    scope_message=SCOPE_MESSAGE,
                )

        return GuardrailResult(passed=True)

    def check_document_upload(self, query: str | None = None) -> GuardrailResult:
        return GuardrailResult(passed=True)
