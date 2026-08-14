from __future__ import annotations

import os
import structlog
from typing import Any

from pydantic import BaseModel

from src.models import VerificationStatus
from src.nli_verifier import NLIVerifier
from src.vectorstore import VectorStore
from src.utils import cosine_similarity, compute_keyword_overlap, l2_normalize

logger = structlog.get_logger()

SEMANTIC_VERIFICATION = os.getenv("SEMANTIC_VERIFICATION", "true").lower() == "true"
SEMANTIC_THRESHOLD = float(os.getenv("SEMANTIC_VERIFICATION_THRESHOLD", "0.65"))
KEYWORD_OVERLAP_THRESHOLD = float(os.getenv("KEYWORD_VERIFICATION_THRESHOLD", "0.30"))


class CitationVerificationResult(BaseModel):
    chunk_exists: bool
    page_exists: bool
    text_supports_claim: bool
    passed: bool
    failure_reason: str | None = None
    semantic_similarity: float | None = None
    verification_method: str = ""
    verification_status: str = ""
    verification_confidence: float = 0.0
    verification_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_exists": self.chunk_exists,
            "page_exists": self.page_exists,
            "text_supports_claim": self.text_supports_claim,
            "passed": self.passed,
            "failure_reason": self.failure_reason,
            "semantic_similarity": self.semantic_similarity,
            "verification_method": self.verification_method,
            "verification_status": self.verification_status,
            "verification_confidence": self.verification_confidence,
            "verification_reason": self.verification_reason,
        }


class Citation(BaseModel):
    chunk_id: str
    text: str
    page_number: int | None
    source_framework: str
    claim: str | None = None
    verification: CitationVerificationResult | None = None


def _compute_semantic_similarity(
    text_a: str,
    text_b: str,
    vector_store: VectorStore,
) -> float:
    emb_a = vector_store.embedding_service.embed_query(text_a[:500])
    emb_b = vector_store.embedding_service.embed_query(text_b[:500])
    dot = sum(ai * bi for ai, bi in zip(emb_a, emb_b))
    na = math.sqrt(sum(ai * ai for ai in emb_a))
    nb = math.sqrt(sum(bi * bi for bi in emb_b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


import math


def _compute_keyword_overlap(claim_text: str, chunk_text: str) -> float:
    return compute_keyword_overlap(claim_text, chunk_text)


def verify_citation(
    chunk_id: str,
    claim_text: str,
    page_number: int | None,
    source_framework: str,
    vector_store: VectorStore,
    document_total_pages: int | None = None,
    nli_verifier: NLIVerifier | None = None,
) -> CitationVerificationResult:
    failures: list[str] = []

    chunk = vector_store.get_chunk(chunk_id)
    chunk_exists = chunk is not None
    if not chunk_exists:
        failures.append("Cited chunk_id does not exist in the vector store.")
        return CitationVerificationResult(
            chunk_exists=False,
            page_exists=False,
            text_supports_claim=False,
            passed=False,
            failure_reason="; ".join(failures),
            verification_method="identity_check",
        )

    chunk_metadata = chunk["metadata"]
    chunk_page_str = chunk_metadata.get("page_number", "")
    chunk_page: int | None = None
    if chunk_page_str and chunk_page_str.strip():
        try:
            chunk_page = int(chunk_page_str)
        except (ValueError, TypeError):
            chunk_page = None

    page_exists = True
    if page_number is not None and chunk_page is not None:
        if page_number != chunk_page:
            page_exists = False
            failures.append(
                f"Claimed page {page_number} does not match stored page {chunk_page}."
            )
    if document_total_pages and page_number:
        if page_number > document_total_pages:
            page_exists = False
            failures.append(f"Page {page_number} exceeds document length ({document_total_pages} pages).")

    chunk_text = chunk["text"]

    verification_status = ""
    verification_confidence = 0.0
    verification_reason = ""

    if nli_verifier is not None and nli_verifier.is_available:
        nli_result = nli_verifier.verify(claim_text, chunk_text, chunk_id)
        text_supports_claim = nli_result.status in (
            VerificationStatus.SUPPORTS,
            VerificationStatus.PARTIALLY_SUPPORTS,
        )
        verification_method = f"nli_{nli_result.method}"
        verification_status = nli_result.status.value
        verification_confidence = nli_result.confidence
        verification_reason = nli_result.reason
        semantic_sim = nli_result.semantic_similarity

        if not text_supports_claim:
            failures.append(
                f"NLI verification: {nli_result.status.value} "
                f"(confidence: {nli_result.confidence:.3f})"
            )

    elif SEMANTIC_VERIFICATION:
        try:
            semantic_sim = _compute_semantic_similarity(claim_text, chunk_text, vector_store)
        except Exception as exc:
            logger.warning("semantic_verification_failed", chunk_id=chunk_id, error=str(exc))
            semantic_sim = None

        keyword_overlap = _compute_keyword_overlap(claim_text, chunk_text)

        if semantic_sim is not None:
            text_supports_claim = semantic_sim >= SEMANTIC_THRESHOLD
            verification_method = "semantic"
            verification_confidence = semantic_sim
            if not text_supports_claim and keyword_overlap >= KEYWORD_OVERLAP_THRESHOLD:
                text_supports_claim = True
                verification_method = "hybrid_keyword_fallback"
                verification_confidence = keyword_overlap
                verification_reason = f"Keyword fallback overlap: {keyword_overlap:.2f}"
            else:
                verification_reason = f"Semantic similarity: {semantic_sim:.3f}"
        else:
            key_terms = [w for w in claim_text.lower().split() if len(w) > 3]
            if len(key_terms) <= 3:
                key_terms = claim_text.lower().split()
            overlap_count = sum(1 for term in key_terms if term in chunk_text.lower())
            text_supports_claim = overlap_count >= max(3, len(key_terms) * KEYWORD_OVERLAP_THRESHOLD)
            verification_method = "keyword_only"
            verification_confidence = overlap_count / max(len(key_terms), 1)
            verification_reason = f"Keyword overlap: {overlap_count}/{len(key_terms)}"
            semantic_sim = None

        if not text_supports_claim:
            if semantic_sim is not None:
                failures.append(
                    f"Semantic similarity {semantic_sim:.3f} below threshold {SEMANTIC_THRESHOLD} "
                    f"(keyword overlap: {keyword_overlap:.2f})."
                )
            else:
                failures.append(
                    "The retrieved chunk's text does not contain sufficient evidence "
                    "to support the claimed statement (insufficient term overlap)."
                )
    else:
        semantic_sim = None
        text_supports_claim = True
        verification_method = "disabled"
        verification_confidence = 1.0

    passed = chunk_exists and page_exists and text_supports_claim
    if not passed and not failures:
        failures.append("Citation verification failed: unknown reason.")

    result = CitationVerificationResult(
        chunk_exists=chunk_exists,
        page_exists=page_exists,
        text_supports_claim=text_supports_claim,
        passed=passed,
        failure_reason="; ".join(failures) if failures else None,
        semantic_similarity=round(semantic_sim, 4) if semantic_sim is not None else None,
        verification_method=verification_method,
        verification_status=verification_status,
        verification_confidence=round(verification_confidence, 4),
        verification_reason=verification_reason,
    )

    logger.info(
        "citation_verified",
        chunk_id=chunk_id,
        passed=passed,
        method=verification_method,
        status=verification_status,
        confidence=verification_confidence,
        failure_reason=result.failure_reason,
    )

    return result


def verify_chat_citation(
    source_framework: str,
    quote_text: str,
    vector_store: VectorStore,
) -> CitationVerificationResult:
    """Verify an LLM-generated chat citation by searching the vector store.

    Since LLM-generated citations do not carry a real chunk_id, this function
    searches the vector store for the quoted text within the claimed framework,
    finds the best matching chunk, and runs semantic verification against it.
    """
    # 1. Search for the quote text within the claimed framework
    framework_filter = None
    if source_framework and source_framework not in ("Uploaded Document", ""):
        framework_filter = [source_framework]

    results = vector_store.retrieve(
        query=quote_text[:500],
        top_k=5,
        framework_filter=framework_filter,
    )

    # If nothing found within the claimed framework, broaden the search
    if not results:
        results = vector_store.retrieve(
            query=quote_text[:500],
            top_k=5,
        )

    if not results:
        return CitationVerificationResult(
            chunk_exists=False,
            page_exists=False,
            text_supports_claim=False,
            passed=False,
            failure_reason="No matching chunk found in vector store for this citation.",
            verification_method="chat_lookup",
        )

    # 2. Find the best matching chunk by comparing quoted text against chunk text
    quote_lower = quote_text.lower().strip()
    quote_terms = set(w for w in quote_lower.split() if len(w) > 3)
    if not quote_terms:
        quote_terms = set(quote_lower.split())

    best_match = None
    best_score = 0.0
    for r in results:
        chunk_text = r.get("text", "")
        chunk_lower = chunk_text.lower()
        if quote_terms:
            overlap = sum(1 for t in quote_terms if t in chunk_lower) / len(quote_terms)
            if overlap > best_score:
                best_score = overlap
                best_match = r

    if not best_match or best_score < 0.25:
        return CitationVerificationResult(
            chunk_exists=False,
            page_exists=False,
            text_supports_claim=False,
            passed=False,
            failure_reason=(
                f"Could not find a sufficiently matching chunk for this citation "
                f"(best term overlap: {best_score:.2f})."
            ),
            verification_method="chat_lookup",
        )

    # 3. Verify the matched chunk's framework aligns with the cited source
    chunk_id = best_match["chunk_id"]
    chunk_text = best_match["text"]
    chunk_meta = best_match.get("metadata", {})
    chunk_framework = chunk_meta.get("framework", "")

    # If the best match came from the broadened search, confirm framework alignment
    if framework_filter and chunk_framework.lower() != source_framework.lower():
        # Check for partial framework name overlap (e.g. "OECD AI Principles" ≈ "OECD")
        sf_lower = source_framework.lower()
        cf_lower = chunk_framework.lower()
        if sf_lower not in cf_lower and cf_lower not in sf_lower:
            # Framework mismatch — mark as unverified
            return CitationVerificationResult(
                chunk_exists=True,
                page_exists=False,
                text_supports_claim=False,
                passed=False,
                failure_reason=(
                    f"Matched chunk belongs to '{chunk_framework}' but citation "
                    f"references '{source_framework}'."
                ),
                verification_method="chat_lookup",
            )

    try:
        semantic_sim = _compute_semantic_similarity(quote_text, chunk_text, vector_store)
    except Exception:
        semantic_sim = None

    keyword_overlap = _compute_keyword_overlap(quote_text, chunk_text)

    if semantic_sim is not None and semantic_sim >= SEMANTIC_THRESHOLD:
        text_supports_claim = True
        verification_method = "chat_semantic"
        verification_confidence = semantic_sim
        verification_reason = f"Semantic similarity: {semantic_sim:.3f}"
    elif keyword_overlap >= KEYWORD_OVERLAP_THRESHOLD:
        text_supports_claim = True
        verification_method = "chat_keyword"
        verification_confidence = keyword_overlap
        verification_reason = f"Keyword overlap: {keyword_overlap:.2f}"
    else:
        text_supports_claim = False
        verification_method = "chat_lookup"
        verification_confidence = max(semantic_sim or 0, keyword_overlap)
        if semantic_sim is not None:
            verification_reason = (
                f"Semantic similarity {semantic_sim:.3f} below threshold {SEMANTIC_THRESHOLD}, "
                f"keyword overlap: {keyword_overlap:.2f}"
            )
        else:
            verification_reason = f"Insufficient overlap: {keyword_overlap:.2f}"

    page_number = chunk_meta.get("page_number")
    if page_number:
        try:
            page_number = int(page_number)
        except (ValueError, TypeError):
            page_number = None

    result = CitationVerificationResult(
        chunk_exists=True,
        page_exists=True,
        text_supports_claim=text_supports_claim,
        passed=text_supports_claim,
        failure_reason=None if text_supports_claim else verification_reason,
        semantic_similarity=round(semantic_sim, 4) if semantic_sim is not None else None,
        verification_method=verification_method,
        verification_status="supports" if text_supports_claim else "contradicts",
        verification_confidence=round(verification_confidence, 4),
        verification_reason=verification_reason,
    )

    logger.info(
        "chat_citation_verified",
        chunk_id=chunk_id,
        source_framework=source_framework,
        passed=result.passed,
        method=verification_method,
        confidence=verification_confidence,
        best_overlap=best_score,
    )

    return result


def verify_gap_analysis_citations(
    gap: dict[str, Any],
    vector_store: VectorStore,
    document_total_pages: int | None = None,
    nli_verifier: NLIVerifier | None = None,
) -> list[dict[str, Any]]:
    verified_evidence: list[dict[str, Any]] = []
    for ev in gap.get("evidence", []):
        chunk_id = ev.get("chunk_id")
        if not chunk_id:
            continue
        text = ev.get("text", "")
        page = ev.get("page_number")

        result = verify_citation(
            chunk_id=chunk_id,
            claim_text=text[:200],
            page_number=page,
            source_framework=ev.get("source_framework", ""),
            vector_store=vector_store,
            document_total_pages=document_total_pages,
            nli_verifier=nli_verifier,
        )

        ev_entry = dict(ev)
        ev_entry["verification"] = result.to_dict()
        ev_entry["verified"] = result.passed
        verified_evidence.append(ev_entry)

    return verified_evidence
