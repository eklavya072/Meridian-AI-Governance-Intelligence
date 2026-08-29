from __future__ import annotations

import os
import threading

import structlog

from src.models import CitationVerification, VerificationStatus
from src.utils import compute_keyword_overlap, cosine_similarity, l2_normalize

logger = structlog.get_logger()

ENABLE_NLI_VERIFICATION = os.getenv("ENABLE_NLI_VERIFICATION", "false").lower() == "true"
NLI_MODEL = os.getenv("NLI_MODEL", "cross-encoder/nli-deberta-v3-base")
NLI_THRESHOLD_ENTAILMENT = float(os.getenv("NLI_THRESHOLD_ENTAILMENT", "0.6"))
NLI_THRESHOLD_CONTRADICTION = float(os.getenv("NLI_THRESHOLD_CONTRADICTION", "0.4"))


class NLIVerifier:
    def __init__(self, model_name: str = NLI_MODEL, embed_function=None):
        self._model_name = model_name
        self._model = None
        self._load_attempted = False
        self._embed = embed_function
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
            logger.info("nli_model_loaded", model=self._model_name)
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
            pair = (claim[:256], chunk_text[:512])
            scores = self._model.predict([pair])
            scores_list = scores[0] if isinstance(scores[0], (list, tuple)) else scores

            if len(scores_list) >= 3:
                entailment = float(scores_list[0])
                neutral = float(scores_list[1])
                contradiction = float(scores_list[2])
            elif len(scores_list) == 1:
                entailment = float(scores_list[0])
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
