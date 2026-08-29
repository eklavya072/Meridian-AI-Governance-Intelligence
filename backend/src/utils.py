from __future__ import annotations

import re
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


def ocr_flexible_fragment(term: str, min_len_for_flex: int = 5) -> str:
    """Regex fragment matching `term` despite PDF intra-word space corruption.

    PDF text extraction routinely shatters words with spurious internal
    spaces (kerning/ligature artifacts). Measured on the EU AI Act corpus in
    this system, the damage is near-total for exactly the vocabulary that
    matters most for governance scoring:

        "deployers"   0 intact vs 10,496 space-broken
        "conformity"  0 intact vs  1,992 space-broken
        "supervis…"   0 intact vs    816 space-broken
        "providers"   2,304 intact vs 5,216 space-broken
        "high-risk"   24 intact vs 11,824 as "high-r isk"

    A literal match therefore silently scored the single most binding
    instrument in the corpus as though it named no duty-bearer and had no
    enforcement machinery — a document-quality artifact masquerading as a
    governance finding. Allowing an optional space between characters
    recovers every one of those matches.

    Only applied to terms of `min_len_for_flex`+ characters: for a long word
    the chance of accidentally matching the same letters spread across
    unrelated words is negligible, while for short words it is not.
    """
    compact = term.replace(" ", "")
    if len(compact) < min_len_for_flex:
        return re.escape(term)
    return r"\s?".join(re.escape(ch) for ch in compact)


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


# Chunk ids are printed in the evidence headers the model is shown, and the
# citation rule tells it to cite only numbers that literally appear in those
# passages. Handed a provision with no division number, the model did exactly
# that and wrote "Section 3081a297-54ab-4efd-9c8c-492521016736" into India's
# Human Autonomy narrative. Same family as the closed citation vocabulary: our
# instruction, not the model's invention. The prompt now forbids it, and this
# strips any that still get through — a reader must never see a UUID presented
# as a provision.
_CHUNK_ID_CITATION_RE = re.compile(
    r"\s*(?:,\s*)?(?:in|at|under|see|per)?\s*"
    r"(?:Section|Article|Part|Chapter|Clause|Paragraph|Principle|Rule)\s+"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def strip_chunk_id_citations(text: str) -> str:
    """Remove references that cite a chunk id as though it were a provision."""
    if not text:
        return text
    cleaned = _CHUNK_ID_CITATION_RE.sub("", text)
    # The removal can leave " and ." or doubled spaces where a list collapsed.
    cleaned = re.sub(r"\s+(and|,)\s*([.;])", r"\2", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return re.sub(r"\s+([.,;])", r"\1", cleaned).strip()
