import pytest

from src.evaluation import (
    evaluate_retrieval,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from src.models import RetrievalMetrics


def test_precision_at_k():
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = {"a", "c"}

    assert precision_at_k(retrieved, relevant, 1) == 1.0
    assert precision_at_k(retrieved, relevant, 2) == 0.5
    assert precision_at_k(retrieved, relevant, 3) == 2.0 / 3.0
    assert precision_at_k(retrieved, relevant, 5) == 2.0 / 5.0
    assert precision_at_k(retrieved, relevant, 0) == 0.0
    assert precision_at_k([], relevant, 5) == 0.0


def test_recall_at_k():
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = {"a", "c", "f"}

    assert recall_at_k(retrieved, relevant, 1) == 1.0 / 3.0
    assert recall_at_k(retrieved, relevant, 2) == 1.0 / 3.0
    assert recall_at_k(retrieved, relevant, 3) == 2.0 / 3.0
    assert recall_at_k(retrieved, relevant, 10) == 2.0 / 3.0
    assert recall_at_k(retrieved, set(), 5) == 0.0


def test_mrr():
    retrieved = ["x", "a", "b", "c"]
    relevant = {"a"}
    assert mean_reciprocal_rank(retrieved, relevant) == 0.5

    retrieved = ["a", "b", "c"]
    relevant = {"a"}
    assert mean_reciprocal_rank(retrieved, relevant) == 1.0

    retrieved = ["x", "y", "z"]
    relevant = {"a"}
    assert mean_reciprocal_rank(retrieved, relevant) == 0.0


def test_ndcg():
    retrieved = ["a", "b", "c", "d", "e"]
    relevance = {"a": 3.0, "b": 2.0, "c": 1.0}

    ndcg = ndcg_at_k(retrieved, relevance, 5)
    assert 0 < ndcg <= 1.0
    assert ndcg_at_k([], relevance, 5) == 0.0

    perfect = ["a", "b", "c"]
    ndcg_perfect = ndcg_at_k(perfect, {"a": 3.0, "b": 2.0, "c": 1.0}, 3)
    assert ndcg_perfect == 1.0


def test_evaluate_retrieval_all_metrics():
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = {"a", "c", "f"}

    metrics = evaluate_retrieval(
        retrieved_chunk_ids=retrieved,
        relevant_chunk_ids=relevant,
        similarity_scores=[0.9, 0.8, 0.7, 0.6, 0.5],
    )

    assert isinstance(metrics, RetrievalMetrics)
    assert metrics.precision_at_1 == 1.0
    assert 0 < metrics.mrr <= 1.0
    assert metrics.avg_retrieval_similarity == 0.7


def test_evaluate_retrieval_empty():
    metrics = evaluate_retrieval(
        retrieved_chunk_ids=[],
        relevant_chunk_ids=set(),
    )
    assert metrics.precision_at_1 == 0.0
    assert metrics.recall_at_5 == 0.0
    assert metrics.mrr == 0.0


def test_evaluate_retrieval_diversity():
    metrics = evaluate_retrieval(
        retrieved_chunk_ids=["a", "b", "c"],
        relevant_chunk_ids={"a"},
        total_retrieved=3,
        duplicate_count=1,
        diversity_count=2,
    )
    assert metrics.duplicate_rate == 1.0 / 3.0
    assert metrics.evidence_diversity == 2.0 / 3.0


def test_precision_at_k_no_relevant():
    retrieved = ["a", "b", "c"]
    assert precision_at_k(retrieved, {"x"}, 3) == 0.0


def test_recall_at_k_more_relevant_than_retrieved():
    retrieved = ["a", "b"]
    relevant = {"a", "c", "d", "e"}
    assert recall_at_k(retrieved, relevant, 2) == 0.25
