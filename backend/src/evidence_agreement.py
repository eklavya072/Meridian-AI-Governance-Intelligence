from __future__ import annotations

import os
import structlog
from typing import Any

from src.models import EvidenceAgreement, EvidenceItem, EvidencePair
from src.utils import cosine_similarity, l2_normalize

logger = structlog.get_logger()

AGREEMENT_SIMILARITY_THRESHOLD = float(os.getenv("AGREEMENT_SIMILARITY_THRESHOLD", "0.75"))
CONFLICT_KEYWORD_THRESHOLD = float(os.getenv("CONFLICT_KEYWORD_THRESHOLD", "0.3"))


def _contains_negation(text: str) -> bool:
    negation_words = {
        "not", "no", "never", "nor", "neither", "cannot", "can't",
        "don't", "doesn't", "didn't", "won't", "wouldn't", "shouldn't",
        "isn't", "aren't", "wasn't", "weren't", "hasn't", "haven't",
        "does not", "do not", "will not", "shall not", "must not",
        "absence", "lack", "without", "fails to", "failure to",
    }
    text_lower = text.lower()
    for word in negation_words:
        if word in text_lower:
            return True
    return False


def _has_contradictory_phrasing(text_a: str, text_b: str) -> bool:
    a_neg = _contains_negation(text_a)
    b_neg = _contains_negation(text_b)
    return a_neg != b_neg


def analyze_evidence_agreement(
    items: list[EvidenceItem],
    embed_function: Any | None = None,
    batch_embed_function: Any | None = None,
) -> list[EvidencePair]:
    if len(items) < 2:
        return []

    embeddings = None
    # Prefer ONE batched call (batch_embed_function(list[str]) ->
    # list[vector]) over N individual embed_function(text) calls — each
    # individual SentenceTransformer .encode() pays its own tokenization/
    # dispatch overhead, which a single batch amortizes. embed_function
    # stays supported for callers that only have a single-item embedder.
    if batch_embed_function is not None:
        try:
            raw = batch_embed_function([item.text[:500] for item in items])
            embeddings = [l2_normalize(e) for e in raw]
        except Exception:
            embeddings = None
    if embeddings is None and embed_function is not None:
        try:
            embeddings = [l2_normalize(embed_function(item.text[:500])) for item in items]
        except Exception:
            embeddings = None

    pairs: list[EvidencePair] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            pair = _classify_pair(a, b, embeddings[i] if embeddings else None,
                                 embeddings[j] if embeddings else None)
            if pair is not None:
                pairs.append(pair)

    return pairs


def _classify_pair(
    a: EvidenceItem,
    b: EvidenceItem,
    emb_a: list[float] | None,
    emb_b: list[float] | None,
) -> EvidencePair | None:
    text_a = a.text[:500].lower()
    text_b = b.text[:500].lower()

    if text_a == text_b:
        return EvidencePair(
            item_a_id=a.chunk_id,
            item_b_id=b.chunk_id,
            agreement=EvidenceAgreement.DUPLICATE,
            score=1.0,
            reason="Identical text",
        )

    if emb_a is not None and emb_b is not None:
        similarity = cosine_similarity(emb_a, emb_b)
    else:
        words_a = set(text_a.split())
        words_b = set(text_b.split())
        if not words_a or not words_b:
            return None
        similarity = len(words_a & words_b) / len(words_a | words_b)

    min_len = min(len(a.text), len(b.text))
    if min_len < 30:
        return None

    has_conflict_phrasing = _has_contradictory_phrasing(text_a, text_b)

    if similarity >= AGREEMENT_SIMILARITY_THRESHOLD:
        if has_conflict_phrasing:
            return EvidencePair(
                item_a_id=a.chunk_id,
                item_b_id=b.chunk_id,
                agreement=EvidenceAgreement.CONFLICTING,
                score=round(similarity, 3),
                reason=f"High similarity ({similarity:.3f}) with contradictory phrasing",
            )
        if a.is_document == b.is_document and a.source_framework == b.source_framework:
            return EvidencePair(
                item_a_id=a.chunk_id,
                item_b_id=b.chunk_id,
                agreement=EvidenceAgreement.DUPLICATE,
                score=round(similarity, 3),
                reason=f"Semantically duplicate ({similarity:.3f})",
            )
        return EvidencePair(
            item_a_id=a.chunk_id,
            item_b_id=b.chunk_id,
            agreement=EvidenceAgreement.SUPPORTING,
            score=round(similarity, 3),
            reason=f"Supporting evidence (sim={similarity:.3f})",
        )

    if similarity >= 0.4:
        return EvidencePair(
            item_a_id=a.chunk_id,
            item_b_id=b.chunk_id,
            agreement=EvidenceAgreement.INDEPENDENT,
            score=round(similarity, 3),
            reason=f"Independent evidence (sim={similarity:.3f})",
        )

    return EvidencePair(
        item_a_id=a.chunk_id,
        item_b_id=b.chunk_id,
        agreement=EvidenceAgreement.WEAK,
        score=round(similarity, 3),
        reason=f"Weak evidence connection (sim={similarity:.3f})",
    )


def compute_evidence_agreement_score(pairs: list[EvidencePair]) -> float:
    if not pairs:
        return 1.0

    scores = []
    for p in pairs:
        if p.agreement == EvidenceAgreement.SUPPORTING:
            scores.append(p.score)
        elif p.agreement == EvidenceAgreement.CONFLICTING:
            scores.append(-p.score)
        elif p.agreement == EvidenceAgreement.DUPLICATE:
            scores.append(0.5)
        elif p.agreement == EvidenceAgreement.INDEPENDENT:
            scores.append(0.3)
        else:
            scores.append(0.1)

    avg = sum(scores) / len(scores)
    return round(max(0.0, min(1.0, (avg + 1.0) / 2.0)), 3)
