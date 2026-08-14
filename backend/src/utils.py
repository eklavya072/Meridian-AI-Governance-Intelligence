from __future__ import annotations

from typing import Any

import numpy as np
from numpy.linalg import norm


def l2_normalize(vec: list[float]) -> list[float]:
    arr = np.array(vec, dtype=np.float32)
    n = norm(arr)
    if n == 0:
        return vec
    return (arr / n).tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_np = np.array(a, dtype=np.float32)
    b_np = np.array(b, dtype=np.float32)
    if norm(a_np) == 0 or norm(b_np) == 0:
        return 0.0
    return float(np.dot(a_np, b_np) / (norm(a_np) * norm(b_np)))


def rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def reciprocal_rank_fusion(
    result_lists: list[list[tuple[str, float]]], k: int = 60
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for results in result_lists:
        for rank, (chunk_id, _) in enumerate(results):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + rrf_score(rank, k)
    sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_items


def compute_keyword_overlap(text_a: str, text_b: str) -> float:
    a_lower = text_a.lower()
    b_lower = text_b.lower()
    words = a_lower.split()
    key_terms = [w for w in words if len(w) > 3]
    if len(key_terms) <= 3:
        key_terms = words
    if not key_terms:
        return 0.0
    overlap = sum(1 for term in key_terms if term in b_lower)
    return overlap / len(key_terms)


def batch_fetch_chunk_metadata(
    vectorstore: Any, chunk_ids: list[str]
) -> dict[str, dict[str, Any]]:
    if not chunk_ids:
        return {}
    result: dict[str, dict[str, Any]] = {}
    try:
        collection = vectorstore.collection
        data = collection.get(
            ids=chunk_ids,
            include=["metadatas", "documents"],
        )
        if data and data.get("ids"):
            for i, cid in enumerate(data["ids"]):
                md = {}
                if data.get("metadatas") and i < len(data["metadatas"]):
                    md = data["metadatas"][i] or {}
                text = ""
                if data.get("documents") and i < len(data["documents"]):
                    text = data["documents"][i] or ""
                result[cid] = {
                    "text": text,
                    "page_number": md.get("page_number"),
                    # Stored metadata key is "section" (set in vectorstore
                    # add_chunks); "section_title" never exists in this store.
                    "section_title": md.get("section") or md.get("section_title"),
                    "source_framework": md.get("source_framework", md.get("framework", "")),
                    # Which uploaded document this chunk came from (workspace
                    # multi-doc support): clean display name, not the
                    # UUID-prefixed storage filename.
                    "document_name": md.get("document_name", ""),
                    "is_document": md.get("is_document", not bool(md.get("framework", ""))),
                }
    except Exception:
        pass
    return result
