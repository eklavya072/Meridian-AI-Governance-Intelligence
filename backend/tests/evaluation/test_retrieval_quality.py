"""
Retrieval quality checks: verify that known relevant chunks are actually retrieved
for known queries.

This test requires:
- ChromaDB with indexed framework documents
- sentence-transformers
"""

import os

import pytest

from src.vectorstore import VectorStore

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_EVALUATION_TESTS"),
    reason="Set RUN_EVALUATION_TESTS=1 to run evaluation tests; requires indexed frameworks",
)


class TestRetrievalQuality:
    def test_transparency_query_retrieves_relevant_chunks(self):
        vs = VectorStore()
        results = vs.retrieve("transparency explainability AI systems", top_k=5)
        assert len(results) > 0, "No chunks retrieved for transparency query"

        transparency_terms = ["transparency", "explainab", "explain", "open"]
        found_terms = any(
            any(term in r["text"].lower() for term in transparency_terms) for r in results
        )
        assert found_terms, "Transparency query did not retrieve transparency-related chunks"

    def test_accountability_query_retrieves_relevant_chunks(self):
        vs = VectorStore()
        results = vs.retrieve("accountability responsible AI governance", top_k=5)
        assert len(results) > 0

        terms = ["accountab", "responsib", "oversight", "audit"]
        found = any(any(term in r["text"].lower() for term in terms) for r in results)
        assert found, "Accountability query did not retrieve accountability-related chunks"

    def test_multi_framework_retrieval(self):
        vs = VectorStore()
        frameworks = vs.get_all_frameworks()
        assert len(frameworks) > 0, "No frameworks indexed"

        results = vs.retrieve("AI ethics principles", top_k=10)
        retrieved_frameworks = {r["metadata"].get("framework", "") for r in results}
        assert len(retrieved_frameworks) >= 1, "Retrieved from no frameworks"

    def test_top_k_returns_correct_count(self):
        vs = VectorStore()
        for k in [1, 3, 5]:
            results = vs.retrieve("AI governance", top_k=k)
            assert len(results) <= k, f"Requested top_k={k} but got {len(results)} results"

    def test_framework_filter_works(self):
        vs = VectorStore()
        frameworks = vs.get_all_frameworks()
        if not frameworks:
            pytest.skip("No frameworks indexed")

        target = frameworks[0]
        results = vs.retrieve("AI principles", top_k=5, framework_filter=[target])
        for r in results:
            assert r["metadata"].get("framework") == target, (
                f"Expected framework {target}, got {r['metadata'].get('framework')}"
            )
