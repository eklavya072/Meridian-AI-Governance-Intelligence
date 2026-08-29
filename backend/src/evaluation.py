from __future__ import annotations

import math
from typing import Any

from src.models import RetrievalMetrics


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if k <= 0 or not retrieved:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for cid in top_k if cid in relevant)
    return hits / len(top_k)


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for cid in top_k if cid in relevant)
    return hits / len(relevant)


def mean_reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for i, cid in enumerate(retrieved):
        if cid in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(
    retrieved: list[str],
    relevance: dict[str, float],
    k: int,
) -> float:
    top_k = retrieved[:k]
    if not top_k:
        return 0.0

    dcg = 0.0
    for i, cid in enumerate(top_k):
        rel = relevance.get(cid, 0.0)
        if i == 0:
            dcg += rel
        else:
            dcg += rel / math.log2(i + 1)

    ideal = sorted(relevance.values(), reverse=True)[:k]
    idcg = ideal[0] if ideal else 0.0
    for i in range(1, len(ideal)):
        idcg += ideal[i] / math.log2(i + 1)

    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def evaluate_retrieval(
    retrieved_chunk_ids: list[str],
    relevant_chunk_ids: set[str],
    relevance_scores: dict[str, float] | None = None,
    total_relevant_in_corpus: int | None = None,
    false_positives: int = 0,
    false_negatives: int = 0,
    total_retrieved: int = 0,
    duplicate_count: int = 0,
    diversity_count: int = 0,
    framework_retrieval_correct: int = 0,
    framework_retrieval_total: int = 0,
    policy_retrieval_correct: int = 0,
    policy_retrieval_total: int = 0,
    similarity_scores: list[float] | None = None,
) -> RetrievalMetrics:
    rel_scores = relevance_scores or dict.fromkeys(relevant_chunk_ids, 2.0)

    metrics = RetrievalMetrics()

    for k in (1, 3, 5, 10):
        p = precision_at_k(retrieved_chunk_ids, relevant_chunk_ids, k)
        r = recall_at_k(retrieved_chunk_ids, relevant_chunk_ids, k)
        if k == 1:
            metrics.precision_at_1 = p
        elif k == 3:
            metrics.precision_at_3 = p
            metrics.recall_at_3 = r
        elif k == 5:
            metrics.precision_at_5 = p
            metrics.recall_at_5 = r
        elif k == 10:
            metrics.precision_at_10 = p
            metrics.recall_at_10 = r

    metrics.recall_at_3 = recall_at_k(retrieved_chunk_ids, relevant_chunk_ids, 3)
    metrics.recall_at_5 = recall_at_k(retrieved_chunk_ids, relevant_chunk_ids, 5)
    metrics.recall_at_10 = recall_at_k(retrieved_chunk_ids, relevant_chunk_ids, 10)

    metrics.mrr = mean_reciprocal_rank(retrieved_chunk_ids, relevant_chunk_ids)

    metrics.ndcg_at_5 = ndcg_at_k(retrieved_chunk_ids, rel_scores, 5)
    metrics.ndcg_at_10 = ndcg_at_k(retrieved_chunk_ids, rel_scores, 10)

    if total_relevant_in_corpus is not None and total_relevant_in_corpus > 0:
        metrics.coverage_recall = len(relevant_chunk_ids) / total_relevant_in_corpus

    if total_retrieved > 0:
        metrics.evidence_diversity = diversity_count / total_retrieved
        metrics.duplicate_rate = duplicate_count / total_retrieved

    if similarity_scores:
        metrics.avg_retrieval_similarity = sum(similarity_scores) / len(similarity_scores)

    if framework_retrieval_total > 0:
        metrics.framework_retrieval_accuracy = (
            framework_retrieval_correct / framework_retrieval_total
        )

    if policy_retrieval_total > 0:
        metrics.policy_retrieval_accuracy = policy_retrieval_correct / policy_retrieval_total

    total_classified = false_positives + false_negatives
    if total_classified > 0:
        metrics.false_positive_rate = false_positives / max(total_classified, 1)
        metrics.false_negative_rate = false_negatives / max(total_classified, 1)
    elif total_retrieved > 0:
        all_negatives = total_retrieved - len(relevant_chunk_ids)
        metrics.false_positive_rate = false_positives / max(all_negatives, 1)
        all_positives = len(relevant_chunk_ids)
        metrics.false_negative_rate = false_negatives / max(all_positives, 1)

    return metrics


class RetrievalEvaluator:
    def __init__(self, vectorstore):
        self.vectorstore = vectorstore

    def evaluate_dimension(
        self,
        dimension: str,
        retrieved_chunks: list[dict[str, Any]],
        relevant_ids: set[str] | None = None,
    ) -> RetrievalMetrics:
        retrieved_ids = [c.get("chunk_id", "") for c in retrieved_chunks]
        if relevant_ids is None:
            relevant_ids = set(retrieved_ids[:3])

        similarity_scores = [
            c.get("rrf_score") or c.get("similarity_score") or 0.0 for c in retrieved_chunks
        ]

        sum(1 for c in retrieved_chunks if c.get("is_document", True))
        sum(1 for c in retrieved_chunks if not c.get("is_document", True))

        source_frameworks = {
            c.get("source_framework", "") for c in retrieved_chunks if c.get("source_framework")
        }

        seen_texts: set[str] = set()
        duplicate_count = 0
        for c in retrieved_chunks:
            t = c.get("text", "")[:200]
            if t in seen_texts:
                duplicate_count += 1
            seen_texts.add(t)

        return evaluate_retrieval(
            retrieved_chunk_ids=retrieved_ids,
            relevant_chunk_ids=relevant_ids,
            total_retrieved=len(retrieved_chunks),
            duplicate_count=duplicate_count,
            diversity_count=len(source_frameworks),
            similarity_scores=similarity_scores,
        )

    def compare_configs(
        self,
        dimension: str,
        config_results: dict[str, RetrievalMetrics],
    ) -> dict[str, dict[str, float]]:
        comparison: dict[str, dict[str, float]] = {}
        for config_name, metrics in config_results.items():
            comparison[config_name] = metrics.model_dump()
        return comparison
