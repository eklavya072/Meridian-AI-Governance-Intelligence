from __future__ import annotations

import math
import os
import threading
from typing import Any

import structlog

from src.models import CitationVerification, VerificationStatus
from src.utils import compute_keyword_overlap, cosine_similarity, l2_normalize

logger = structlog.get_logger()

ENABLE_NLI_VERIFICATION = os.getenv("ENABLE_NLI_VERIFICATION", "false").lower() == "true"
NLI_MODEL = os.getenv("NLI_MODEL", "cross-encoder/nli-deberta-v3-base")
NLI_THRESHOLD_ENTAILMENT = float(os.getenv("NLI_THRESHOLD_ENTAILMENT", "0.6"))
NLI_THRESHOLD_CONTRADICTION = float(os.getenv("NLI_THRESHOLD_CONTRADICTION", "0.4"))


# Positional label order is NOT a constant across NLI checkpoints, and
# guessing it wrong is silent: every score still parses, the numbers still
# look like scores, and the verdicts are simply inverted.
# cross-encoder/nli-deberta-v3-base reports
# {0: 'contradiction', 1: 'entailment', 2: 'neutral'} — so the previous
# positional read of [entailment, neutral, contradiction] took contradiction
# for entailment and neutral for contradiction. Measured on 403 real stored
# citations, 85.4% of which quote text that is literally inside the chunk
# they cite, it labelled 362 of them (89.8%) "contradicts". Read the map.
_DEFAULT_LABEL_INDEX = {"entailment": 0, "neutral": 1, "contradiction": 2}


def _resolve_label_index(model: Any) -> dict[str, int]:
    """Map entailment/neutral/contradiction onto this checkpoint's own order."""
    id2label = getattr(getattr(model, "config", None), "id2label", None) or {}
    resolved: dict[str, int] = {}
    for idx, raw in id2label.items():
        name = str(raw).strip().lower()
        for key in ("entailment", "neutral", "contradiction"):
            if key in name:
                resolved[key] = int(idx)
    if len(resolved) == 3:
        return resolved
    logger.warning("nli_label_map_unreadable", id2label=id2label)
    return dict(_DEFAULT_LABEL_INDEX)


def _softmax(values: list[float]) -> list[float]:
    """CrossEncoder.predict returns LOGITS for a multi-class head, not
    probabilities — observed range roughly -6 to +6. Comparing those to the
    0.6 / 0.4 thresholds below is meaningless: a logit of 5.8 for `neutral`
    cleared a 0.4 "contradiction" bar simply by being a large number."""
    if not values:
        return []
    peak = max(values)
    exps = [math.exp(v - peak) for v in values]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


class NLIVerifier:
    def __init__(self, model_name: str = NLI_MODEL, embed_function=None):
        self._model_name = model_name
        self._model = None
        self._load_attempted = False
        self._embed = embed_function
        # Overwritten from the checkpoint's own id2label at load time.
        self._label_index: dict[str, int] = dict(_DEFAULT_LABEL_INDEX)
        # The parallel analysis loop verifies citations from multiple
        # dimension threads; the shared CrossEncoder/embed fn is not safe
        # for concurrent inference, so serialize verification.
        self._lock = threading.Lock()

    def _load(self):
        if self._load_attempted:
            return
        self._load_attempted = True
        if not ENABLE_NLI_VERIFICATION:
            logger.info("nli_verification_disabled")
            return
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name)
            self._label_index = _resolve_label_index(self._model)
            logger.info(
                "nli_model_loaded",
                model=self._model_name,
                label_index=self._label_index,
            )
        except Exception as exc:
            logger.error("nli_model_load_failed", model=self._model_name, error=str(exc))
            self._model = None

    @property
    def is_available(self) -> bool:
        if not ENABLE_NLI_VERIFICATION:
            return False
        if not self._load_attempted:
            self._load()
        return self._model is not None

    def verify(
        self,
        claim: str,
        chunk_text: str,
        chunk_id: str = "",
    ) -> CitationVerification:
        with self._lock:
            return self._verify_unlocked(claim, chunk_text, chunk_id)

    def _verify_unlocked(
        self,
        claim: str,
        chunk_text: str,
        chunk_id: str = "",
    ) -> CitationVerification:
        if not claim or not chunk_text:
            return CitationVerification(
                claim=claim,
                chunk_id=chunk_id,
                chunk_text=chunk_text,
                status=VerificationStatus.IRRELEVANT,
                confidence=0.0,
                reason="Empty claim or chunk text",
                method="none",
            )

        if self.is_available:
            return self._verify_nli(claim, chunk_text, chunk_id)

        if self._embed is not None:
            return self._verify_embedding(claim, chunk_text, chunk_id)

        return self._verify_keyword(claim, chunk_text, chunk_id)

    def _verify_nli(
        self,
        claim: str,
        chunk_text: str,
        chunk_id: str,
    ) -> CitationVerification:
        try:
            # Premise first, hypothesis second. The chunk is the evidence and
            # the claim is what it is being asked to support; the reverse
            # order asks whether the claim implies the whole document, which
            # is a different and much harder question.
            pair = (chunk_text[:512], claim[:256])
            scores = self._model.predict([pair])
            row = scores[0]
            scores_list = [float(v) for v in row] if hasattr(row, "__len__") else [float(row)]

            if len(scores_list) >= 3:
                probs = _softmax(scores_list)
                idx = self._label_index
                entailment = probs[idx["entailment"]]
                neutral = probs[idx["neutral"]]
                contradiction = probs[idx["contradiction"]]
            elif len(scores_list) == 1:
                # Single-logit (binary) head: squash to a probability rather
                # than treating the logit itself as one.
                entailment = 1.0 / (1.0 + math.exp(-scores_list[0]))
                neutral = 0.0
                contradiction = 1.0 - entailment
            else:
                entailment = 0.0
                neutral = 0.0
                contradiction = 0.0

            if entailment >= NLI_THRESHOLD_ENTAILMENT:
                status = VerificationStatus.SUPPORTS
                confidence = entailment
                reason = f"NLI entailment score: {entailment:.3f}"
            elif contradiction >= NLI_THRESHOLD_CONTRADICTION:
                status = VerificationStatus.CONTRADICTS
                confidence = contradiction
                reason = f"NLI contradiction score: {contradiction:.3f}"
            elif entailment >= 0.3:
                status = VerificationStatus.PARTIALLY_SUPPORTS
                confidence = entailment
                reason = f"NLI partial entailment: {entailment:.3f}, neutral: {neutral:.3f}"
            else:
                status = VerificationStatus.IRRELEVANT
                confidence = max(entailment, neutral)
                reason = f"NLI irrelevant: entailment={entailment:.3f}, contradiction={contradiction:.3f}"

            return CitationVerification(
                claim=claim,
                chunk_id=chunk_id,
                chunk_text=chunk_text[:200],
                status=status,
                confidence=round(confidence, 4),
                reason=reason,
                method="nli_cross_encoder",
                nli_score=round(entailment, 4),
                semantic_similarity=round(entailment, 4),
            )

        except Exception as exc:
            logger.warning("nli_verification_failed", chunk_id=chunk_id, error=str(exc))
            return self._verify_embedding(claim, chunk_text, chunk_id)

    def _verify_embedding(
        self,
        claim: str,
        chunk_text: str,
        chunk_id: str,
    ) -> CitationVerification:
        try:
            emb_c = l2_normalize(self._embed(claim[:500]))
            emb_t = l2_normalize(self._embed(chunk_text[:500]))
            similarity = cosine_similarity(emb_c, emb_t)
        except Exception as exc:
            logger.warning("embedding_verification_failed", chunk_id=chunk_id, error=str(exc))
            return self._verify_keyword(claim, chunk_text, chunk_id)

        keyword_overlap = compute_keyword_overlap(claim, chunk_text)

        if similarity >= 0.65:
            status = VerificationStatus.SUPPORTS
            confidence = similarity
            reason = f"Embedding similarity: {similarity:.3f}"
        elif similarity >= 0.45:
            status = VerificationStatus.PARTIALLY_SUPPORTS
            confidence = similarity
            reason = f"Partial embedding similarity: {similarity:.3f}"
        elif keyword_overlap >= 0.3:
            status = VerificationStatus.PARTIALLY_SUPPORTS
            confidence = keyword_overlap
            reason = f"Keyword overlap fallback: {keyword_overlap:.2f}"
        else:
            status = VerificationStatus.IRRELEVANT
            confidence = max(similarity, keyword_overlap)
            reason = f"Low similarity: {similarity:.3f}, keyword overlap: {keyword_overlap:.2f}"

        return CitationVerification(
            claim=claim,
            chunk_id=chunk_id,
            chunk_text=chunk_text[:200],
            status=status,
            confidence=round(confidence, 4),
            reason=reason,
            method="embedding_similarity",
            semantic_similarity=round(similarity, 4),
            keyword_overlap=round(keyword_overlap, 4),
        )

    def _verify_keyword(
        self,
        claim: str,
        chunk_text: str,
        chunk_id: str,
    ) -> CitationVerification:
        overlap = compute_keyword_overlap(claim, chunk_text)

        if overlap >= 0.5:
            status = VerificationStatus.SUPPORTS
            confidence = overlap
            reason = f"Keyword overlap: {overlap:.2f}"
        elif overlap >= 0.2:
            status = VerificationStatus.PARTIALLY_SUPPORTS
            confidence = overlap
            reason = f"Partial keyword overlap: {overlap:.2f}"
        else:
            status = VerificationStatus.IRRELEVANT
            confidence = overlap
            reason = f"Insufficient keyword overlap: {overlap:.2f}"

        return CitationVerification(
            claim=claim,
            chunk_id=chunk_id,
            chunk_text=chunk_text[:200],
            status=status,
            confidence=round(confidence, 4),
            reason=reason,
            method="keyword_only",
            keyword_overlap=round(overlap, 4),
        )


def verify_citation_nli(
    claim: str,
    chunk_text: str,
    chunk_id: str = "",
    embed_function=None,
) -> CitationVerification:
    verifier = NLIVerifier(embed_function=embed_function)
    return verifier.verify(claim, chunk_text, chunk_id)
