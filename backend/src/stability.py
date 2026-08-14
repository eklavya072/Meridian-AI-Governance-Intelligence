from __future__ import annotations

import math
import os
import structlog
import time
from typing import Any

from src.models import RetrievalStability

logger = structlog.get_logger()

STABILITY_NUM_RETRIEVALS = int(os.getenv("STABILITY_NUM_RETRIEVALS", "3"))
STABILITY_JACCARD_THRESHOLD = float(os.getenv("STABILITY_JACCARD_THRESHOLD", "0.5"))
ENABLE_STABILITY_CHECK = os.getenv("ENABLE_STABILITY_CHECK", "false").lower() == "true"


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    if not set_a and not set_b:
        return 1.0
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    return len(set_a & set_b) / union


def kendall_tau(ranking_a: list[str], ranking_b: list[str]) -> float:
    common = set(ranking_a) & set(ranking_b)
    if len(common) < 2:
        return 0.0

    a_pos = {cid: i for i, cid in enumerate(ranking_a) if cid in common}
    b_pos = {cid: i for i, cid in enumerate(ranking_b) if cid in common}

    common_list = list(common)
    concordant = 0
    discordant = 0

    for i in range(len(common_list)):
        for j in range(i + 1, len(common_list)):
            ci, cj = common_list[i], common_list[j]
            diff_a = a_pos[ci] - a_pos[cj]
            diff_b = b_pos[ci] - b_pos[cj]
            if diff_a * diff_b > 0:
                concordant += 1
            elif diff_a * diff_b < 0:
                discordant += 1

    total = concordant + discordant
    if total == 0:
        return 1.0
    return (concordant - discordant) / total


def score_variance(scores_list: list[list[float]]) -> float:
    all_scores = [s for scores in scores_list for s in scores]
    if len(all_scores) < 2:
        return 0.0
    mean = sum(all_scores) / len(all_scores)
    variance = sum((s - mean) ** 2 for s in all_scores) / len(all_scores)
    return round(variance, 4)


def analyze_retrieval_stability(
    dimension: str,
    retrieval_fn: Any,
    num_retrievals: int | None = None,
) -> RetrievalStability:
    n = num_retrievals or STABILITY_NUM_RETRIEVALS
    if n < 2:
        return RetrievalStability(dimension=dimension, num_retrievals=1, is_stable=True)

    all_ids: list[list[str]] = []
    all_scores: list[list[float]] = []

    for i in range(n):
        try:
            result = retrieval_fn(dimension)
            chunk_ids = []
            scores = []
            for c in result.document_chunks + result.framework_chunks:
                cid = c.get("chunk_id", "")
                score = c.get("reranker_score") or c.get("rrf_score") or c.get("similarity_score") or 0.0
                chunk_ids.append(cid)
                scores.append(score)
            all_ids.append(chunk_ids)
            all_scores.append(scores)
        except Exception as exc:
            logger.warning("stability_retrieval_failed", dimension=dimension, attempt=i, error=str(exc))

    if len(all_ids) < 2:
        return RetrievalStability(dimension=dimension, num_retrievals=len(all_ids), is_stable=True)

    jaccard_scores = []
    tau_scores = []

    for i in range(len(all_ids)):
        for j in range(i + 1, len(all_ids)):
            jaccard_scores.append(jaccard_similarity(set(all_ids[i]), set(all_ids[j])))
            tau_scores.append(kendall_tau(all_ids[i], all_ids[j]))

    avg_jaccard = sum(jaccard_scores) / len(jaccard_scores) if jaccard_scores else 0.0
    avg_tau = sum(tau_scores) / len(tau_scores) if tau_scores else 0.0
    var = score_variance(all_scores)

    is_stable = avg_jaccard >= STABILITY_JACCARD_THRESHOLD

    return RetrievalStability(
        dimension=dimension,
        num_retrievals=len(all_ids),
        jaccard_similarity=round(avg_jaccard, 4),
        kendall_tau=round(avg_tau, 4),
        semantic_stability=round((avg_jaccard + avg_tau) / 2.0, 4),
        score_variance=round(var, 4),
        is_stable=is_stable,
    )
