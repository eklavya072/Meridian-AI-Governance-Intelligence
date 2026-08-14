import pytest
from src.stability import (
    jaccard_similarity,
    kendall_tau,
    score_variance,
    analyze_retrieval_stability,
)


def test_jaccard_similarity():
    assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0
    assert jaccard_similarity({"a", "b"}, {"a", "c"}) == 1.0 / 3.0
    assert jaccard_similarity(set(), set()) == 1.0


def test_kendall_tau():
    ranking_a = ["a", "b", "c", "d"]
    ranking_b = ["a", "b", "c", "d"]
    assert kendall_tau(ranking_a, ranking_b) == 1.0

    ranking_b_rev = ["d", "c", "b", "a"]
    assert kendall_tau(ranking_a, ranking_b_rev) == -1.0

    assert kendall_tau(["a"], ["b"]) == 0.0


def test_kendall_tau_no_common():
    assert kendall_tau(["a", "b"], ["c", "d"]) == 0.0


def test_score_variance():
    scores = [[1.0, 0.5, 0.8], [0.9, 0.6, 0.7]]
    var = score_variance(scores)
    assert var >= 0.0

    assert score_variance([]) == 0.0
    assert score_variance([[1.0]]) == 0.0


def test_score_variance_identical():
    scores = [[0.5, 0.5], [0.5, 0.5]]
    assert score_variance(scores) == 0.0


def test_analyze_stability_single_retrieval():
    class MockResult:
        document_chunks = [{"chunk_id": "c1"}, {"chunk_id": "c2"}]
        framework_chunks = []

    def retrieval_fn(dim):
        return MockResult()

    result = analyze_retrieval_stability("Test", retrieval_fn, num_retrievals=1)
    assert result.is_stable
    assert result.num_retrievals == 1


def test_analyze_stability_multiple_retrievals():
    results = []

    class MockResult:
        def __init__(self, ids):
            self.document_chunks = [{"chunk_id": cid} for cid in ids]
            self.framework_chunks = []

    def retrieval_fn(dim):
        if len(results) == 0:
            r = MockResult(["a", "b", "c"])
        else:
            r = MockResult(["a", "b", "d"])
        results.append(r)
        return r

    result = analyze_retrieval_stability("Test", retrieval_fn, num_retrievals=3)
    assert result.num_retrievals == 3
    assert 0 <= result.jaccard_similarity <= 1.0
    assert 0 <= result.semantic_stability <= 1.0


def test_stability_low_variance():
    import time
    results_data = []

    def mock_retrieval(dim):
        return type('R', (), {
            'document_chunks': [
                {'chunk_id': 'c1', 'rrf_score': 0.9},
                {'chunk_id': 'c2', 'rrf_score': 0.8},
                {'chunk_id': 'c3', 'rrf_score': 0.7},
            ],
            'framework_chunks': [],
        })()

    result = analyze_retrieval_stability("Transparency", mock_retrieval, num_retrievals=3)
    assert result.num_retrievals == 3
    assert result.score_variance >= 0.0
