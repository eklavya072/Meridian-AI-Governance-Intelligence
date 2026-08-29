from __future__ import annotations

import os
import threading
import time
import structlog
from typing import Any

import numpy as np

from pydantic import BaseModel, Field

import re as _re

from src.models import DimensionProfile, RetrievalResult
from src.utils import l2_normalize, reciprocal_rank_fusion, batch_fetch_chunk_metadata
from src.deterministic import is_low_information_fragment, _chunk_matches_dimension


def _dedup_key(text: str) -> str:
    """Normalized alphanumeric signature used for near-duplicate detection."""
    return _re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _is_near_duplicate(key: str, accepted_keys: list[str]) -> bool:
    """True when `key` is a containment near-duplicate of something accepted.

    Exact-text dedup is not enough. Chunk boundaries drift between ingestions
    and overlapping windows re-emit the same passage shifted by a few
    characters, so the same provision reappears as many textually DISTINCT
    chunks ("...fostering sustainable growth" vs "...sustainable growth").
    Measured on the live store after exact-duplicate cleanup: Kenya still held
    4,973 distinct chunk texts that collapse to just 88 genuinely distinct
    passages, and the EU AI Act 1,450 that collapse to 359.

    The practical cost is retrieval recall. A fixed candidate budget spent on
    a corpus that is ~98% near-duplicates surfaces only a few dozen real
    passages, so the scorer never sees most of the document and reports
    dimensions as thin when the text is simply never retrieved. Containment
    catches truncation at either end, which is exactly the shape this
    artifact takes.
    """
    if not key:
        return True
    for k in accepted_keys:
        if key in k or k in key:
            return True
    return False

logger = structlog.get_logger()

USE_RERANKER = os.getenv("USE_RERANKER", "false").lower() == "true"
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

ASPECT_TOP_K = int(os.getenv("ASPECT_TOP_K", "5"))
DEFINITION_TOP_K = int(os.getenv("DEFINITION_TOP_K", "10"))
RERANKER_CANDIDATE_MULTIPLIER = int(os.getenv("RERANKER_CANDIDATE_MULTIPLIER", "3"))
TOP_K_AFTER_RERANK = int(os.getenv("TOP_K_AFTER_RERANK", "10"))
CONFIDENCE_FILTER_THRESHOLD = float(os.getenv("CONFIDENCE_FILTER_THRESHOLD", "0.1"))

# Module budget: tuned to stay well under Gemini free-tier per-minute/per-day limits
MODULE1_TOP_K = int(os.getenv("MODULE1_TOP_K", "4"))
MODULE2_TOP_K = int(os.getenv("MODULE2_TOP_K", "3"))
# Regional reserve: when the document's country routes regional frameworks
# (Singapore Model AI Governance Framework for ASEAN, AU Continental
# Strategy for AU members), reserve this many Module 1 budget slots for
# them. Without this, the always-on core frameworks can win every
# similarity slot and the country's own framework never surfaces in its
# own analysis. The reserved chunk is picked from a separate retrieval
# restricted to the regional frameworks, then merged into the final budget.
MODULE1_REGIONAL_RESERVE = int(os.getenv("MODULE1_REGIONAL_RESERVE", "1"))
# Dimension reserve (Module 2/3): a dimension-tagged practical tool or
# implementation source (e.g. CDEI bias review for Fairness, the carbon
# scoping review for Environmental Sustainability) is guaranteed this many
# slots in its dimension's Module 2/3 budget. Same rationale as the
# regional reserve: role+query similarity alone can starve a source that
# was deliberately routed for the dimension being evaluated.
MODULE2_DIMENSION_RESERVE = int(os.getenv("MODULE2_DIMENSION_RESERVE", "1"))
MODULE3_DIMENSION_RESERVE = int(os.getenv("MODULE3_DIMENSION_RESERVE", "1"))
# Document bucket budget: the uploaded policy is the PRIMARY evidence for
# Module 1 — the LLM judges THE DOCUMENT, not the frameworks. 4 chunks
# (each truncated to ~800 chars) is the minimum that lets a substantive
# national strategy show its commitments; 3 was starving it to 1-2 chunks.
# Raised 4 -> 6: confirmed live miss on a long, dense legal text (EU AI
# Act) where Article 99 (penalties) and Article 50 (disclosure duty) never
# reached the Accountability/Transparency prompts at 4 — the LLM saw only
# recital paraphrases and honestly under-reported. This costs LLM PROMPT
# TOKENS, not extra API REQUESTS (same one call per dimension), so it does
# not touch the Gemini free-tier request quota.
DOC_TOP_K = int(os.getenv("MODULE_DOC_TOP_K", "6"))
MODULE_CHUNK_MAX_CHARS = int(os.getenv("MODULE_CHUNK_MAX_CHARS", "800"))

# Module 3+4 budget (the conditional second call per dimension). Deliberately
# tight — this call's context stays near the ~10-chunk Module 1+2 budget:
#   3 implementation chunks + 4 incident chunks + 2 document chunks
# (document chunks are for responsible-agency grounding, per the no-fabrication
# rule). The carried-forward Module 1+2 gap reasoning travels as TEXT, not
# re-retrieved chunks, so this call does not balloon in size.
MODULE3_TOP_K = int(os.getenv("MODULE3_TOP_K", "3"))
MODULE4_TOP_K = int(os.getenv("MODULE4_TOP_K", "4"))

# Module 4 is CASE intelligence — the plural matters. Two knobs keep it that
# way, and both exist because the raw similarity ranking does not.
#
# MODULE4_CANDIDATE_POOL: the incident corpus is wildly uneven (one royal
# commission report is ~2000 chunks; a court ruling is 4). A generalist harm
# taxonomy therefore ranks in the top-60 for EVERY dimension and buries the
# specific case that actually speaks to it. Pulling a wide pool and selecting
# from it — instead of trusting the first handful — is what gives the smaller,
# sharper source a chance to be seen.
#
# MODULE4_MAX_PER_DOCUMENT: without a cap, one document routinely takes every
# slot (Accountability, Safety and Fairness each returned the same report 3x
# before this). Two slots lets a genuinely dominant source stay dominant while
# still guaranteeing a second, independent case reaches the prompt.
MODULE4_CANDIDATE_POOL = int(os.getenv("MODULE4_CANDIDATE_POOL", "60"))
MODULE4_MAX_PER_DOCUMENT = int(os.getenv("MODULE4_MAX_PER_DOCUMENT", "2"))
MODULE34_DOC_TOP_K = int(os.getenv("MODULE34_DOC_TOP_K", "2"))

# Module buckets are de-duplicated on normalized text (same as the document
# bucket) so two near-duplicate overlapping chunks cannot both consume slots in
# the small per-bucket budget. Headroom multiplier: pull extra candidates so
# dedup can drop redundant text and still fill the budget with DISTINCT content.
MODULE_DEDUP_HEADROOM = int(os.getenv("MODULE_DEDUP_HEADROOM", "3"))

# Comprehensive-evidence pool: a broad semantic sweep of the workspace
# document BEYOND the prompt-budget bucket. The LLM judges the document on
# the small DOC_TOP_K budget; a governance mechanism expressed in the
# policy's own terminology can rank outside it and be missed. The pool feeds
# the deterministic ladder's R1/R2 evidence check so a mechanism the prompt
# never showed can still floor Missing -> Partial instead of being erased.
# Local, embedding-only operation — no LLM/API cost — so a wider sweep is
# cheap. Raised (40->60 / 18->24) alongside the hybrid lexical fusion in
# _retrieve_doc_bucket_multi_query, so the ladder's R1/R2 evidence check
# sees a genuinely wider net, not just a wider dense-only one.
EVIDENCE_POOL_CANDIDATES = int(os.getenv("EVIDENCE_POOL_CANDIDATES", "60"))
EVIDENCE_POOL_MAX = int(os.getenv("EVIDENCE_POOL_MAX", "24"))

# Scoring pool — feeds deterministic pattern scoring, NOT an LLM prompt, so it
# is sized for document coverage rather than token budget (see
# retrieve_scoring_pool). Large instruments were being scored from as few as
# four chunks under the prompt-sized pool, which penalised long statutes
# purely for being long.
SCORING_POOL_CANDIDATES = int(os.getenv("SCORING_POOL_CANDIDATES", "300"))
SCORING_POOL_MAX = int(os.getenv("SCORING_POOL_MAX", "160"))

DIMENSION_PROFILES: dict[str, DimensionProfile] = {}


class ModuleRetrievalResult(BaseModel):
    """Budgeted retrieval split across Module 1 normative, Module 2 practical, and the workspace document."""

    dimension: str
    document_chunks: list[dict[str, Any]] = Field(default_factory=list)
    module1_chunks: list[dict[str, Any]] = Field(default_factory=list)
    module2_chunks: list[dict[str, Any]] = Field(default_factory=list)
    total_chunks: int = 0
    retrieval_queries: list[str] = Field(default_factory=list)

    def all_chunks_labeled(self) -> list[dict[str, Any]]:
        """All chunks with a role label for the prompt builder."""
        labeled: list[dict[str, Any]] = []
        for c in self.document_chunks:
            labeled.append({**c, "module_role": "document"})
        for c in self.module1_chunks:
            labeled.append({**c, "module_role": "module_1_normative"})
        for c in self.module2_chunks:
            labeled.append({**c, "module_role": "module_2_practical"})
        return labeled


class Module34RetrievalResult(BaseModel):
    """Budgeted retrieval for the conditional Module 3 + Module 4 second call.

    role-tagged buckets (module_3_implementation / module_4_incident) plus a
    small document slice for responsible-agency grounding. Kept tight so the
    combined second call stays near the Module 1+2 context budget.
    """

    dimension: str
    module3_chunks: list[dict[str, Any]] = Field(default_factory=list)
    module4_chunks: list[dict[str, Any]] = Field(default_factory=list)
    document_chunks: list[dict[str, Any]] = Field(default_factory=list)
    total_chunks: int = 0

    def all_chunks_labeled(self) -> list[dict[str, Any]]:
        labeled: list[dict[str, Any]] = []
        for c in self.module3_chunks:
            labeled.append({**c, "module_role": "module_3_implementation"})
        for c in self.module4_chunks:
            labeled.append({**c, "module_role": "module_4_incident"})
        for c in self.document_chunks:
            labeled.append({**c, "module_role": "document"})
        return labeled


class CrossEncoderReranker:
    def __init__(self, model_name: str = RERANKER_MODEL):
        self._model_name = model_name
        self._model = None
        self._load_attempted = False

    def _load(self):
        if self._load_attempted:
            return
        self._load_attempted = True
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self._model_name)
            logger.info("reranker_loaded", model=self._model_name)
        except Exception as exc:
            logger.error("reranker_load_failed", model=self._model_name, error=str(exc))
            self._model = None

    @property
    def is_available(self) -> bool:
        if not self._load_attempted:
            self._load()
        return self._model is not None

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []
        if not self.is_available:
            return candidates[:top_k] if top_k else candidates

        pairs = [(query, c.get("text", "")[:512]) for c in candidates]
        try:
            scores = self._model.predict(pairs)
        except Exception as exc:
            logger.error("reranker_predict_failed", error=str(exc))
            return candidates[:top_k] if top_k else candidates

        scored = [
            (c, float(s)) for c, s in zip(candidates, scores)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        if top_k is not None:
            scored = scored[:top_k]

        result = []
        for c, s in scored:
            c["reranker_score"] = s
            result.append(c)
        return result


class RetrievalPipeline:
    def __init__(self, vectorstore):
        self.vectorstore = vectorstore
        self._reranker = None
        # Per-instance cache (NOT class-level — a class-level dict would
        # leak every workspace's full chunk text across every analysis run
        # for the process lifetime). See _workspace_chunk_texts.
        self._lexical_cache: dict[str, list[tuple[str, str]]] = {}
        # Per-workspace lock so the 8 concurrent dimension workers (the
        # analysis loop's bounded-parallel ThreadPoolExecutor) COALESCE into
        # one real fetch instead of racing: without this, all 8 workers can
        # hit _workspace_chunk_texts in the same first second, before any of
        # them has populated the cache, each independently re-fetching the
        # entire workspace document from Chroma. On a large document (the EU
        # AI Act runs ~1000+ chunks) that is 7 wasted full-collection fetches
        # stacking up as real wall-clock time — a self-inflicted latency
        # regression from the lexical-hybrid fix, not the intended cost of
        # having it. Locking makes it "fetch once, every worker reads the
        # same cached list" as originally intended.
        self._lexical_cache_locks: dict[str, threading.Lock] = {}
        self._lexical_cache_locks_guard = threading.Lock()

    def _get_reranker(self) -> CrossEncoderReranker:
        if self._reranker is None:
            self._reranker = CrossEncoderReranker()
        return self._reranker

    @staticmethod
    def _select_incident_pool(
        candidates: list[dict[str, Any]],
        dimension: str,
        limit: int,
        max_per_document: int = MODULE4_MAX_PER_DOCUMENT,
    ) -> list[dict[str, Any]]:
        """Pick incident chunks that are on-topic AND from more than one case.

        Two passes over the ranked candidates, both preserving rank order:
        drop anything the dimension-grounding gate would reject downstream,
        then allow each source document at most `max_per_document` slots.

        If grounding leaves too few chunks to fill `limit`, the ungrounded
        remainder backfills in rank order. That is deliberate: gap_analyzer
        re-checks grounding and drops them anyway, so backfilling cannot put a
        bad case in the output — but it does keep the LLM's context from
        collapsing to one or two chunks on a dimension where the corpus is
        genuinely thin, which reads as "no evidence" rather than "no match".
        """
        if not candidates:
            return []

        grounded: list[dict[str, Any]] = []
        rest: list[dict[str, Any]] = []
        for c in candidates:
            text = c.get("text") or c.get("chunk_text") or ""
            (grounded if _chunk_matches_dimension(text, dimension) else rest).append(c)

        selected: list[dict[str, Any]] = []
        overflow: list[dict[str, Any]] = []
        per_doc: dict[str, int] = {}
        for c in grounded:
            md = c.get("metadata") or {}
            # Fall back to doc_id, then chunk_id: a chunk with no
            # document_name must not share a cap bucket with every OTHER
            # unnamed chunk, which would silently cap them collectively at 2.
            key = str(
                md.get("document_name")
                or md.get("doc_id")
                or c.get("chunk_id")
                or id(c)
            )
            if per_doc.get(key, 0) >= max_per_document:
                overflow.append(c)
                continue
            per_doc[key] = per_doc.get(key, 0) + 1
            selected.append(c)

        # Overflow before ungrounded: a 3rd chunk of a well-matched case still
        # beats an off-topic one.
        for pool in (overflow, rest):
            if len(selected) >= limit:
                break
            selected.extend(pool[: limit - len(selected)])

        return selected[:limit]

    def get_or_build_profiles(self) -> dict[str, DimensionProfile]:
        if DIMENSION_PROFILES:
            return DIMENSION_PROFILES

        profiles: dict[str, str] = {
            "Transparency": (
                "The extent to which AI systems disclose information about their "
                "operations, data sources, decision-making processes, and limitations. "
                "This includes public reporting, documentation practices, explainability "
                "mechanisms, audit trail availability, and stakeholder access to "
                "meaningful information about how AI systems function."
            ),
            "Accountability": (
                "The assignment and enforcement of responsibility for AI system outcomes. "
                "This includes legal liability frameworks, human oversight mechanisms, "
                "governance structures with clear ownership, redress and grievance "
                "procedures, audit requirements, and consequences for harms caused by "
                "AI systems."
            ),
            "Fairness": (
                "The absence of bias and equitable treatment across all population groups "
                "in AI system design, development, deployment, and outcomes. This includes "
                "bias testing and mitigation, demographic parity considerations, "
                "accessibility provisions, inclusive design practices, and protection "
                "against discrimination based on protected characteristics."
            ),
            "Privacy": (
                "The protection of personal data and individual autonomy over information "
                "in AI systems. This includes data minimization, consent mechanisms, "
                "anonymization practices, data security, purpose limitation, data subject "
                "rights, and compliance with regulatory frameworks for data protection."
            ),
            "Safety": (
                "The assurance that AI systems operate reliably and without causing "
                "unintended harm under all expected conditions. This includes robustness "
                "testing, fail-safe mechanisms, adversarial resistance, system monitoring, "
                "incident reporting, emergency shut-off capabilities, and pre-deployment "
                "certification processes."
            ),
            "Human Autonomy": (
                "The preservation of human agency and self-determination in the presence "
                "of AI systems. This includes meaningful human control, opt-out "
                "mechanisms, human-in-the-loop requirements, the right to non-automated "
                "decision-making, and protections against undue manipulation or "
                "nudging by AI systems."
            ),
            "Inclusivity": (
                "The active engagement of diverse stakeholders in AI system governance "
                "and the equitable distribution of AI benefits across society. This "
                "includes public participation mechanisms, multi-stakeholder governance, "
                "digital divide considerations, accessibility for persons with "
                "disabilities, linguistic diversity, and cultural representation."
            ),
            "Environmental Sustainability": (
                "The consideration and minimization of environmental impacts throughout "
                "the AI lifecycle. This includes energy efficiency, carbon footprint "
                "reporting, hardware lifecycle management, computational resource "
                "optimization, and alignment with environmental protection goals."
            ),
        }

        core = {
            "Transparency", "Accountability", "Fairness",
            "Privacy", "Safety", "Human Autonomy"
        }

        for dim, definition in profiles.items():
            profiles[dim] = DimensionProfile(
                dimension=dim,
                definition=definition,
                aspects=self._generate_aspects(dim, definition),
                is_core=dim in core,
            )

        return profiles

    def _generate_aspects(self, dimension: str, definition: str) -> list[str]:
        aspects_map: dict[str, list[str]] = {
            "Transparency": [
                "Public disclosure of AI system capabilities and limitations",
                "Explainability of individual AI decisions",
                "Documentation of training data and methodologies",
                "Audit trail and logging of AI system operations",
                "Stakeholder access to meaningful information about AI operations",
            ],
            "Accountability": [
                "Legal liability for AI-caused harms",
                "Human oversight and governance structures",
                "Grievance and redress mechanisms for affected individuals",
                "Audit and independent review of AI systems",
                "Assignment of responsibility for AI system outcomes",
            ],
            "Fairness": [
                "Bias detection and mitigation in AI systems",
                "Equitable access to AI benefits and services",
                "Protection against algorithmic discrimination",
                "Inclusive design and accessibility",
                "Demographic fairness in AI training data",
            ],
            "Privacy": [
                "Consent mechanisms for personal data collection",
                "Data minimization and purpose limitation",
                "Anonymization and pseudonymization practices",
                "Individual rights over personal data",
                "Data security and breach notification procedures",
            ],
            "Safety": [
                "Robustness testing and validation of AI systems",
                "Adversarial resistance and security measures",
                "Fail-safe and emergency shut-off mechanisms",
                "Continuous monitoring and performance assurance",
                "Incident reporting and response procedures",
            ],
            "Human Autonomy": [
                "Meaningful human control over AI decisions",
                "Opt-out mechanisms from automated decision-making",
                "Human-in-the-loop requirements for critical decisions",
                "Protection against manipulation and undue influence",
                "Right to non-automated decision-making",
            ],
            "Inclusivity": [
                "Multi-stakeholder participation in AI governance",
                "Digital divide and access inequality considerations",
                "Accessibility for persons with disabilities",
                "Cultural and linguistic diversity in AI design",
                "Equitable distribution of AI benefits",
            ],
            "Environmental Sustainability": [
                "Energy efficiency of AI training and inference",
                "Carbon footprint reporting and reduction targets",
                "Computational resource optimization",
                "Hardware lifecycle and e-waste management",
                "Alignment with environmental sustainability goals",
            ],
        }
        return aspects_map.get(dimension, [definition])

    def build_dimension_embeddings(
        self, profiles: dict[str, DimensionProfile]
    ) -> dict[str, dict[str, list[float]]]:
        result: dict[str, dict[str, list[float]]] = {}
        for dim, profile in profiles.items():
            definition_emb = self.vectorstore.embed_query(profile.definition)
            aspect_embs = [
                self.vectorstore.embed_query(aspect)
                for aspect in profile.aspects
            ]
            result[dim] = {
                "definition": definition_emb,
                "aspects": aspect_embs,
            }
        return result

    def retrieve_for_dimension(
        self,
        dimension: str,
        user_query: str = "",
        top_k_definition: int | None = None,
        top_k_aspect: int | None = None,
    ) -> RetrievalResult:
        dim_query = dimension
        if user_query:
            dim_query = f"{dimension}: {user_query}"

        top_k_def = top_k_definition or DEFINITION_TOP_K
        top_k_asp = top_k_aspect or ASPECT_TOP_K
        candidate_k_def = top_k_def * RERANKER_CANDIDATE_MULTIPLIER if USE_RERANKER else top_k_def
        candidate_k_asp = top_k_asp * RERANKER_CANDIDATE_MULTIPLIER if USE_RERANKER else top_k_asp

        t0 = time.time()

        profiles = self.get_or_build_profiles()
        profile = profiles.get(dimension)
        if profile is None:
            all_chunks = self._search_vectorstore(dim_query, candidate_k_def)
            if USE_RERANKER:
                all_chunks = self._apply_reranker(dim_query, all_chunks, top_k_def)
            t1 = time.time()
            return RetrievalResult(
                document_chunks=[c for c in all_chunks if c.get("is_document", True)],
                framework_chunks=[c for c in all_chunks if not c.get("is_document", True)],
                retrieval_queries=[dim_query],
                retrieval_latency=t1 - t0,
                total_candidates=len(all_chunks),
            )

        dim_embs = self.build_dimension_embeddings(profiles)
        dim_data = dim_embs.get(dimension)
        if dim_data is None:
            all_chunks = self._search_vectorstore(dim_query, candidate_k_def)
            if USE_RERANKER:
                all_chunks = self._apply_reranker(dim_query, all_chunks, top_k_def)
            t1 = time.time()
            return RetrievalResult(
                document_chunks=[c for c in all_chunks if c.get("is_document", True)],
                framework_chunks=[c for c in all_chunks if not c.get("is_document", True)],
                retrieval_queries=[dim_query],
                retrieval_latency=t1 - t0,
                total_candidates=len(all_chunks),
            )

        definition_emb = dim_data["definition"]
        aspect_embs = dim_data["aspects"]

        queries = [dim_query]
        rank_lists: list[list[tuple[str, float]]] = []

        def_scores = self._query_by_embedding(definition_emb, candidate_k_def)
        if def_scores:
            rank_lists.append(def_scores)
            queries.append(f"definition_embedding:{dimension}")

        for i, asp_emb in enumerate(aspect_embs):
            asp_scores = self._query_by_embedding(asp_emb, candidate_k_asp)
            if asp_scores:
                rank_lists.append(asp_scores)
                queries.append(f"aspect_{i}_embedding:{dimension}")

        if user_query:
            user_emb = self.vectorstore.embed_query(user_query)
            user_scores = self._query_by_embedding(user_emb, candidate_k_def)
            if user_scores:
                rank_lists.append(user_scores)
                queries.append(f"user_query:{user_query}")

        fused = reciprocal_rank_fusion(rank_lists)
        all_fused_ids = [cid for cid, _ in fused]

        chunk_metadata = batch_fetch_chunk_metadata(self.vectorstore, all_fused_ids)

        doc_chunks: list[dict[str, Any]] = []
        fw_chunks: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        all_candidates: list[dict[str, Any]] = []

        for chunk_id, rr_score in fused:
            if chunk_id in seen_ids:
                continue
            seen_ids.add(chunk_id)
            chunk_data = chunk_metadata.get(chunk_id, {})
            entry = {
                "chunk_id": chunk_id,
                "text": chunk_data.get("text", ""),
                "page_number": chunk_data.get("page_number"),
                "section_title": chunk_data.get("section_title"),
                "source_framework": chunk_data.get("source_framework", ""),
                "rrf_score": rr_score,
                "is_document": chunk_data.get("is_document", not bool(chunk_data.get("source_framework", ""))),
            }
            all_candidates.append(entry)
            if chunk_data.get("is_document", True):
                doc_chunks.append(entry)
            else:
                fw_chunks.append(entry)

        rerank_latency = 0.0
        if USE_RERANKER and all_candidates:
            t_rerank = time.time()
            rerank_input = len(all_candidates)
            reranked = self._apply_reranker(dim_query, all_candidates, TOP_K_AFTER_RERANK)
            rerank_latency = time.time() - t_rerank
            reranked = [c for c in reranked if c.get("reranker_score", 0.0) >= CONFIDENCE_FILTER_THRESHOLD]
            doc_chunks = [c for c in reranked if c.get("is_document", True)]
            fw_chunks = [c for c in reranked if not c.get("is_document", True)]
            logger.info(
                "stage_6_retrieval_rerank",
                dimension=dimension,
                reranker_input=rerank_input,
                reranker_output=len(reranked),
                reranker_used=USE_RERANKER,
                rerank_latency_s=round(rerank_latency, 3),
            )

        t1 = time.time()

        doc_scores = [c.get("rrf_score", c.get("similarity_score", 0.0)) for c in doc_chunks]
        fw_scores = [c.get("rrf_score", c.get("similarity_score", 0.0)) for c in fw_chunks]
        all_scores = doc_scores + fw_scores
        avg_score = round(sum(all_scores) / max(len(all_scores), 1), 4) if all_scores else 0.0

        logger.info(
            "stage_6_retrieval_complete",
            dimension=dimension,
            num_queries=len(queries),
            doc_chunks_retrieved=len(doc_chunks),
            framework_chunks_retrieved=len(fw_chunks),
            total_candidates=len(all_candidates),
            avg_similarity_score=avg_score,
            min_score=round(min(all_scores), 4) if all_scores else 0.0,
            max_score=round(max(all_scores), 4) if all_scores else 0.0,
            reranker_used=USE_RERANKER,
            latency_s=round((t1 - t0) + rerank_latency, 3),
        )

        return RetrievalResult(
            document_chunks=doc_chunks,
            framework_chunks=fw_chunks,
            retrieval_queries=queries,
            retrieval_latency=(t1 - t0) + rerank_latency,
            total_candidates=len(all_candidates),
        )

    def _search_vectorstore(
        self, query: str, top_k: int = 10
    ) -> list[dict[str, Any]]:
        is_doc = "document" in query.lower() or "report" in query.lower()
        results = self.vectorstore.search(query, top_k=top_k)
        chunks = []
        for r in results:
            md = r.get("metadata", {})
            chunks.append({
                "chunk_id": r.get("id", ""),
                "text": r.get("text", r.get("content", "")),
                "page_number": md.get("page_number"),
                "section_title": md.get("section_title"),
                "source_framework": md.get("source_framework", md.get("framework", "")),
                "similarity_score": r.get("similarity", r.get("score", 0.0)),
                "is_document": md.get("is_document", not bool(md.get("framework", ""))),
            })
        return chunks

    def _query_by_embedding(
        self,
        query_emb: list[float],
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[tuple[str, float]]:
        query_emb_n = l2_normalize(query_emb)
        scored: list[tuple[str, float]] = []
        try:
            results = self.vectorstore.collection.query(
                query_embeddings=[query_emb_n],
                n_results=top_k,
                where=where,
                include=["distances"],
            )
            if results and results.get("ids"):
                for i, cid in enumerate(results["ids"][0]):
                    dist = results["distances"][0][i] if results.get("distances") else 0.0
                    sim = max(0.0, 1.0 - dist / 2.0)
                    scored.append((cid, sim))
        except Exception:
            pass
        return scored

    def _apply_reranker(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        reranker = self._get_reranker()
        if not reranker.is_available:
            logger.warning("reranker_unavailable", query=query, candidates=len(candidates))
            return candidates[:top_k] if top_k else candidates
        return reranker.rerank(query, candidates, top_k=top_k)

    # ── Module 1 + Module 2 combined budget retrieval ─────────────────

    _PREAMBLE_MARKERS = (
        "intentionally left blank", "acknowledgment", "acknowledgement",
        "table of contents", "contents", "copyright",
        "all rights reserved", "this page has been intentionally left blank",
    )

    def _is_preamble_chunk(self, chunk: dict[str, Any]) -> bool:
        """True only for genuine boilerplate (cover/TOC/copyright pages).

        Conservative on purpose: a national strategy's substantive content often
        starts on page 2, and phrases like "This page has been intentionally
        left blank" or "acknowledgment" can appear inside otherwise-rich chunks.
        Only short chunks that are dominated by boilerplate markers (or cover
        pages) are dropped.
        """
        text_lower = chunk.get("text", "").lower().strip()
        if len(text_lower) < 150:
            return True
        # vectorstore.retrieve() / _retrieve_doc_bucket_multi_query() carry
        # page_number inside metadata, NOT at the top level. Reading only the
        # top-level key made page default to 0 for EVERY doc chunk, which
        # silently dropped every chunk under 400 chars as a "cover page" — a
        # systematic doc-bucket starvation bug.
        md = chunk.get("metadata") or {}
        raw_page = chunk.get("page_number") or md.get("page_number")
        try:
            page = int(raw_page or 0)
        except (TypeError, ValueError):
            page = 0
        # Cover / title pages: very early page AND short text.
        if page <= 1 and len(text_lower) < 400:
            return True
        # Short chunks dominated by TOC/copyright markers are boilerplate.
        if len(text_lower) < 400 and any(m in text_lower for m in self._PREAMBLE_MARKERS):
            return True
        return False

    def _truncate_chunk(self, chunk: dict[str, Any]) -> dict[str, Any]:
        text = chunk.get("text", "") or ""
        if len(text) > MODULE_CHUNK_MAX_CHARS:
            chunk = {**chunk, "text": text[:MODULE_CHUNK_MAX_CHARS]}
        return chunk

    def _prioritize_substantive(
        self, bucket: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Stable reorder: substantive chunks first, low-information fragments last.

        Glossary/index fragments (a term + footnote number like
        "Explainability15", or a bare heading) can rank high on embedding
        similarity and would otherwise consume the small per-bucket budgets
        ahead of real content. Keeping the original RRF order within each
        class means each budget fills with substantive chunks first; a
        fragment only survives when there is genuinely nothing else for the
        dimension. Applies to every bucket (document + module), so a
        substantive chunk is always preferred over a thin fragment.
        """
        return sorted(
            bucket,
            key=lambda c: is_low_information_fragment(c.get("text") or ""),
        )

    def _workspace_chunk_texts(self, workspace_id: str) -> list[tuple[str, str]]:
        """All (chunk_id, text) pairs for one workspace document — a single
        cheap metadata-only fetch (no vector search), cached per workspace
        for the life of this pipeline instance so repeated dimension calls
        don't refetch. A national policy PDF is at most a few hundred
        chunks, so scoring all of them lexically in Python is trivial."""
        # Lazy-init: some tests construct RetrievalPipeline via __new__
        # (bypassing __init__), and this cache is a pure optimization, not
        # a required piece of state — getattr keeps both paths working.
        cache = getattr(self, "_lexical_cache", None)
        if cache is None:
            cache = {}
            self._lexical_cache = cache
        cached = cache.get(workspace_id)
        if cached is not None:
            return cached

        # Coalesce concurrent callers onto ONE fetch. The 8-worker analysis
        # loop can have every dimension call this within the same instant,
        # before the cache is warm — without a lock, each would independently
        # re-fetch the entire workspace document from Chroma (real wall-clock
        # cost on a large document). Per-workspace (not a single global lock)
        # so unrelated workspaces never block each other.
        locks_guard = getattr(self, "_lexical_cache_locks_guard", None)
        if locks_guard is None:
            # Same defensive fallback as the cache itself (tests via __new__).
            self._lexical_cache_locks_guard = threading.Lock()
            self._lexical_cache_locks = {}
            locks_guard = self._lexical_cache_locks_guard
        with locks_guard:
            lock = self._lexical_cache_locks.setdefault(workspace_id, threading.Lock())

        with lock:
            # Re-check: another thread may have populated the cache while
            # this one waited for the lock.
            cached = cache.get(workspace_id)
            if cached is not None:
                return cached
            out: list[tuple[str, str]] = []
            try:
                data = self.vectorstore.collection.get(
                    where={"workspace_id": {"$in": [workspace_id]}},
                    include=["documents"],
                )
                ids = data.get("ids") or []
                docs = data.get("documents") or []
                out = [(cid, txt or "") for cid, txt in zip(ids, docs)]
            except Exception as exc:
                logger.warning("workspace_chunk_fetch_failed", workspace_id=workspace_id, error=str(exc))
            self._lexical_cache[workspace_id] = out
            return out

    def _workspace_document_texts(self, workspace_id: str) -> list[str]:
        """The workspace's text grouped BY DOCUMENT, one string per file.

        Citation checking needs the division numbering of each instrument kept
        apart: the India Guidelines enumerate 1-7 and the DPDP Act 1-44, so a
        single joined string would lend the Guidelines an ordinal they do not
        have and clear a citation to a "Principle 8" that does not exist.
        """
        by_document: dict[str, list[str]] = {}
        try:
            data = self.vectorstore.collection.get(
                where={"workspace_id": {"$in": [workspace_id]}},
                include=["documents", "metadatas"],
            )
            docs = data.get("documents") or []
            metas = data.get("metadatas") or []
            for txt, meta in zip(docs, metas):
                meta = meta or {}
                key = meta.get("document_name") or meta.get("source_file") or ""
                by_document.setdefault(key, []).append(txt or "")
        except Exception as exc:
            logger.warning(
                "workspace_document_text_fetch_failed",
                workspace_id=workspace_id,
                error=str(exc),
            )
            return []
        return [" ".join(parts) for parts in by_document.values()]

    def _lexical_candidates(
        self,
        workspace_id: str,
        dimension: str,
        query_texts: list[str],
        limit: int,
    ) -> list[tuple[str, float]]:
        """Keyword/lexical ranking over the FULL workspace document — the
        hybrid half of retrieval that dense-embedding search (which caps at
        a candidate window) can silently miss entirely.

        Fixes a confirmed live gap: the EU AI Act's Article 99 penalty
        regime and Article 50 disclosure duty never reached the Accountability
        / Transparency dimension prompts because embedding similarity ranked
        recital/preamble paraphrases above the operative articles within the
        small candidate window. A term-overlap score against the dimension's
        own high-precision vocabulary (DIMENSION_CORE_TERMS) plus the query
        text catches exact statutory language ("penalties", "Article 99",
        "shall notify") that a paraphrase-trained embedding can under-rank,
        and — because it scores every chunk in the document, not just the
        embedding model's top-N — it can surface a chunk dense search never
        returned as a candidate at all.
        """
        from src.deterministic import DIMENSION_CORE_TERMS

        # Core terms (curated, high-precision governance vocabulary — "data
        # protection", "grievance", "carbon footprint") are kept SEPARATE
        # from the incidental words in query_texts. query_texts is usually
        # the dimension's full definition + aspect prose (several sentences,
        # not a short keyword list), so pooling every >3-char word from it
        # into one undifferentiated term set let generic overlap with that
        # prose (articles, connectives, topic-adjacent words) outscore a
        # chunk that only matches the curated core terms — exactly the
        # exact-statutory-language signal this hybrid pass exists to protect.
        # Confirmed live: a chunk containing "Enforce the Data Protection &
        # Privacy law" (2 core-term hits) ranked below dozens of chunks that
        # merely shared incidental words with a six-sentence Privacy
        # definition, so it never reached the lexical top-K at all.
        core_terms = {t.lower() for t in DIMENSION_CORE_TERMS.get(dimension, ())}
        query_terms: set[str] = set()
        for qt in query_texts:
            query_terms.update(w.lower() for w in qt.split() if len(w) > 3)
        query_terms -= core_terms
        if not core_terms and not query_terms:
            return []

        scored: list[tuple[str, float]] = []
        for cid, text in self._workspace_chunk_texts(workspace_id):
            if not text:
                continue
            lower = text.lower()
            core_hits = sum(1 for t in core_terms if t in lower)
            query_hits = sum(1 for t in query_terms if t in lower)
            if core_hits == 0 and query_hits == 0:
                continue
            # Core-term hits are weighted well above incidental query-prose
            # overlap — a curated term match is a much stronger signal of
            # dimension relevance than sharing a handful of common words with
            # a long definition sentence.
            weighted_hits = core_hits * 4 + query_hits
            # Normalize by length so a short, dense hit (a single operative
            # sentence) isn't buried under a long chunk that merely contains
            # the term once among unrelated content.
            score = weighted_hits / (len(lower.split()) + 1) ** 0.5
            scored.append((cid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def _retrieve_doc_bucket_multi_query(
        self,
        dimension: str,
        dim_query: str,
        workspace_id: str,
        candidates: int,
    ) -> list[dict[str, Any]]:
        """Multi-query RRF retrieval scoped to the workspace document.

        The document bucket is the PRIMARY evidence for Module 1 — the LLM
        judges THE DOCUMENT, not the frameworks. A single string query cannot
        represent a governance dimension: national strategies address each
        dimension across many sections using varied terminology. The original
        retrieve_for_dimension used multi-query RRF (dimension definition +
        aspects, embedded separately, RRF-fused); retrieve_module_chunks
        regressed to one plain string query, which systematically missed the
        document's substantive commitments (e.g. the NITI Aayog strategy's
        "Explainable AI (XAI) program" — an explicit implementation
        commitment — never reached the Transparency prompt, so the LLM
        honestly reported Partial/Missing). This restores multi-query recall
        for the document bucket only; module buckets keep their single query
        (they are small, role-tagged framework sets).

        HYBRID: a lexical/keyword rank list (see _lexical_candidates) is
        RRF-fused alongside the dense rank lists, so exact statutory
        vocabulary a paraphrase embedding under-ranks — or never returns as
        a candidate at all — still gets a fair shot at the budget.
        """
        profiles = self.get_or_build_profiles()
        profile = profiles.get(dimension)

        where: dict[str, Any] = {"workspace_id": {"$in": [workspace_id]}}
        # The bare dimension name ("Accountability") is the LEAST specific
        # query vector — it is what ranked a UN advisory-body participation
        # paragraph (sim 0.859) and an events-calendar paragraph (sim
        # 0.869-0.875) into the Accountability / Inclusivity document
        # buckets. The definition + aspect queries ARE the constrained
        # phrasing (liability/redress/grievance for Accountability;
        # accessibility/non-discrimination/digital divide for Inclusivity);
        # the bare name only adds generic recall without topical precision.
        # Drop it unless dim_query carries real user intent (e.g. chat),
        # where it must be preserved verbatim.
        query_texts: list[str] = []
        if dim_query.strip().lower() != dimension.strip().lower():
            query_texts.append(dim_query)
        if profile is not None:
            query_texts.append(profile.definition)
            query_texts.extend(profile.aspects)
        if not query_texts:
            query_texts = [dim_query]

        rank_lists: list[list[tuple[str, float]]] = []
        # Best dense similarity per chunk (max across the query variants) so
        # downstream confidence scoring gets a real 0-1 score instead of 0.0.
        best_sim: dict[str, float] = {}
        # One batched embed call for all query variants (definition +
        # aspects, typically 4-6 texts) instead of one individual call per
        # variant — same embeddings, less per-call model overhead. This
        # function runs twice per dimension (document bucket + evidence
        # pool), so the saving compounds across the 8-dimension pipeline.
        try:
            query_embs = list(self.vectorstore.embedding_service.embed(query_texts))
            if len(query_embs) != len(query_texts):
                raise ValueError("batch embed returned mismatched length")
        except Exception:
            query_embs = [self.vectorstore.embed_query(t) for t in query_texts]
        for text, emb in zip(query_texts, query_embs):
            scored = self._query_by_embedding(emb, candidates, where=where)
            if scored:
                rank_lists.append(scored)
            for cid, sim in scored:
                best_sim[cid] = max(best_sim.get(cid, 0.0), sim)

        # HYBRID: fuse in a lexical/keyword rank list scored over the WHOLE
        # workspace document (not just the dense candidate window) — see
        # _lexical_candidates. This is what lets exact statutory language a
        # paraphrase embedding under-ranks (or never surfaces as a dense
        # candidate at all) still win a budget slot.
        #
        # Weighted 3x in the fusion, not 1x. A confirmed live miss (Rwanda's
        # "Enforce the Data Protection & Privacy law" — one line inside an
        # otherwise-unrelated 2787-char implementation-plan table) ranked #1
        # on the lexical pass across the ENTIRE workspace corpus, yet still
        # lost every fused-list slot: with `query_texts` typically expanding
        # to 4-7 dense variants (definition + aspects), a chunk that merely
        # ranks decently across several of them accumulates more combined RRF
        # score than a single rank-0 lexical vote can offset (1/(k+0) from
        # one list vs. several 1/(k+rank) contributions from many). Appending
        # the lexical list multiple times gives its exact-term signal real
        # weight against that dilution without touching the shared, generic
        # reciprocal_rank_fusion() utility used elsewhere.
        lexical = self._lexical_candidates(workspace_id, dimension, query_texts, candidates)
        if lexical:
            rank_lists.extend([lexical] * 3)

        if not rank_lists:
            return []

        fused = reciprocal_rank_fusion(rank_lists)
        fused_ids = [cid for cid, _ in fused][:candidates]
        meta = batch_fetch_chunk_metadata(self.vectorstore, fused_ids)

        out: list[dict[str, Any]] = []
        for cid in fused_ids:
            m = meta.get(cid, {})
            if not m.get("text"):
                continue
            out.append({
                "chunk_id": cid,
                "text": m.get("text", ""),
                "metadata": {
                    "page_number": m.get("page_number"),
                    "section": m.get("section_title"),
                    "framework": m.get("source_framework", ""),
                    "document_name": m.get("document_name", ""),
                },
                "similarity_score": round(best_sim.get(cid, 0.0), 4),
            })
        return out

    def retrieve_document_evidence_pool(
        self,
        dimension: str,
        workspace_id: str | None = None,
        candidates: int = EVIDENCE_POOL_CANDIDATES,
        max_chunks: int = EVIDENCE_POOL_MAX,
    ) -> list[dict[str, Any]]:
        """Broad semantic sweep of the workspace document for a dimension.

        Anti-false-negative net for the Module 1 verdict: the prompt-budget
        document bucket (DOC_TOP_K) is what the LLM sees, and a governance
        mechanism expressed in the policy's own terminology can rank outside
        it. This pool pulls a wider candidate set with the same multi-query
        RRF (dimension definition + aspects — semantic similarity, NOT a
        keyword checklist), filters preamble / low-information fragments, and
        returns the surviving dimension-relevant chunks for the deterministic
        ladder's R1/R2 comprehensive-evidence check. The ladder only ever
        reads real chunks (real chunk_ids, real text), so a mechanism the
        prompt missed can still floor Missing -> Partial instead of being
        erased into a false Missing.
        """
        if not workspace_id:
            return []
        raw = self._retrieve_doc_bucket_multi_query(
            dimension=dimension,
            dim_query=dimension,
            workspace_id=workspace_id,
            candidates=candidates,
        )
        filtered = [c for c in raw if not self._is_preamble_chunk(c)]
        out: list[dict[str, Any]] = []
        accepted_keys: list[str] = []
        for c in filtered:
            text = (c.get("text") or "").strip()
            if not text:
                continue
            if is_low_information_fragment(text):
                continue
            # Containment dedup (see _is_near_duplicate). This pool feeds the
            # LLM prompt, where a duplicate costs tokens AND crowds out a
            # distinct passage the model would otherwise have seen.
            key = _dedup_key(text)
            if _is_near_duplicate(key, accepted_keys):
                continue
            accepted_keys.append(key)
            out.append(c)
            if len(out) >= max_chunks:
                break
        if out:
            logger.info(
                "document_evidence_pool_retrieved",
                dimension=dimension,
                workspace_id=workspace_id,
                raw_candidates=len(raw),
                after_preamble_filter=len(filtered),
                pool_size=len(out),
            )
        return out

    def retrieve_scoring_pool(
        self,
        dimension: str,
        workspace_id: str | None = None,
        candidates: int = SCORING_POOL_CANDIDATES,
        max_chunks: int = SCORING_POOL_MAX,
    ) -> list[dict[str, Any]]:
        """Wide sweep of the workspace document for DETERMINISTIC scoring.

        Separate from retrieve_document_evidence_pool because the two serve
        different consumers with opposite constraints:

          - the evidence pool feeds an LLM prompt, so it is deliberately small
            and aggressively trimmed (preamble filter, 24-chunk cap) to protect
            the token budget;
          - this pool feeds regex/pattern scoring in evidence_strength.py,
            which costs nothing per chunk, so it should see as much of the
            document as possible.

        Reusing the small prompt-budget pool for scoring was starving the
        scorer on large instruments: a 144-page regulation returned as few as
        FOUR chunks for a dimension, and every strength signal was computed
        from that sliver — so long, dense statutes scored LOWER than short
        strategies purely because retrieval showed the scorer less of them.
        That is a document-length artifact, not a governance finding.

        The preamble filter is also deliberately NOT applied here. Recitals and
        preambles are exactly where a statute states purpose in soft language
        ("should", "is appropriate to") — the tier system already grades that
        as weak, so including them adds real signal instead of discarding a
        large share of the document unscored.
        """
        if not workspace_id:
            return []
        raw = self._retrieve_doc_bucket_multi_query(
            dimension=dimension,
            dim_query=dimension,
            workspace_id=workspace_id,
            candidates=candidates,
        )
        out: list[dict[str, Any]] = []
        accepted_keys: list[str] = []
        for c in raw:
            text = (c.get("text") or "").strip()
            if not text:
                continue
            if is_low_information_fragment(text):
                continue
            # Containment dedup, not exact-match — see _is_near_duplicate for
            # why exact matching leaves the budget almost entirely full of
            # re-emitted copies of the same passage.
            key = _dedup_key(text)
            if _is_near_duplicate(key, accepted_keys):
                continue
            accepted_keys.append(key)
            out.append(c)
            if len(out) >= max_chunks:
                break
        if out:
            logger.info(
                "scoring_pool_retrieved",
                dimension=dimension,
                workspace_id=workspace_id,
                raw_candidates=len(raw),
                pool_size=len(out),
            )
        return out

    def _enforce_reserve(
        self,
        clean: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        reserve: int,
        budget: int,
        seen_text: set[str],
        reserved_names: set[str],
        dimension: str,
        bucket: str,
    ) -> None:
        """Guarantee at least `reserve` chunks from `reserved_names` survive
        the bucket's deduped budget.

        The general pool ranks on similarity, so a source that was
        deliberately routed for this dimension/region (regional framework,
        dimension-tagged practical tool) can be crowded out by the always-on
        core sources. When fewer reserved chunks survived than promised,
        swap the lowest-priority non-reserved chunk for the best reserved
        candidate that isn't a text duplicate of what remains.

        NOTE: do NOT skip candidates on `chunk_id in seen` — the dedup loop
        adds EVERY candidate's id to its `seen` set before the budget cap
        rejects it, so a reserved chunk the general pool saw but dropped
        would be wrongly blocked here. The text-dedup check against the
        SURVIVING budget is the correct guard.
        """
        if not candidates or reserve <= 0:
            return
        reserved_in_budget = [
            c for c in clean if c.get("source_framework") in reserved_names
        ]
        missing = reserve - len(reserved_in_budget)
        inserted = 0
        for rc in candidates:
            if missing <= 0:
                break
            text_key = " ".join((rc.get("text") or "").split()).lower()
            if text_key in seen_text:
                continue
            # Find the lowest-priority non-reserved chunk to evict (scan
            # from the end: the bucket is ordered by substance, so the tail
            # holds the weakest entries).
            evict_idx = -1
            for idx in range(len(clean) - 1, -1, -1):
                if clean[idx].get("source_framework") not in reserved_names:
                    evict_idx = idx
                    break
            if evict_idx == -1:
                if len(clean) >= budget:
                    # Budget full and every slot is reserved — done.
                    break
                clean.append(rc)
            else:
                clean[evict_idx] = rc
            seen_text.add(text_key)
            missing -= 1
            inserted += 1
        if inserted:
            logger.info(
                "module_reserve_filled",
                dimension=dimension,
                bucket=bucket,
                reserved_frameworks=sorted(reserved_names),
                reserved=reserve,
                inserted=inserted,
            )

    def retrieve_module_chunks(
        self,
        dimension: str,
        workspace_id: str | None = None,
        user_query: str = "",
        module1_top_k: int = MODULE1_TOP_K,
        module2_top_k: int = MODULE2_TOP_K,
        doc_top_k: int = DOC_TOP_K,
        module1_frameworks: list[str] | None = None,
        module1_regional_frameworks: list[str] | None = None,
        module2_dimension_frameworks: list[str] | None = None,
    ) -> ModuleRetrievalResult:
        """Per-dimension budgeted retrieval for the combined Module 1+2 call.

        Pulls at most `module1_top_k` chunks tagged module_1_normative,
        `module2_top_k` tagged module_2_practical, and `doc_top_k` chunks from
        the workspace document (with preamble filter). Deduplicates by chunk_id
        and truncates each chunk to ~700-800 chars. Total stays around 10-11
        chunks per dimension call to stay inside Gemini free-tier limits.

        `module1_frameworks` is the deterministic routing result from
        src/framework_router.resolve_frameworks() — when provided, Module 1
        retrieval is restricted to exactly those framework names (core +
        dimension-specific + regional). Module 2 and the workspace document
        are never framework-filtered. When omitted, behaviour is unchanged
        (all module_1_normative sources are eligible).

        `module1_regional_frameworks` is the country's region-routed subset
        (e.g. Singapore Model AI Governance Framework for ASEAN) from
        src/framework_router.resolve_regional_frameworks(). When provided,
        at least MODULE1_REGIONAL_RESERVE of the final Module 1 budget is
        guaranteed to come from these frameworks — a separate retrieval
        restricted to them runs, and if the general budget was filled by
        core frameworks alone, the lowest-priority general chunk is swapped
        for the best regional chunk. This keeps a country's own frameworks
        from being silently crowded out of its own analysis.

        The document bucket uses multi-query RRF (dimension + definition +
        aspects, workspace-scoped) so the uploaded policy's own substantive
        treatment of the dimension reliably reaches the prompt — this is the
        evidence that determines the Module 1 coverage verdict.
        """
        dim_query = dimension if not user_query else f"{dimension}: {user_query}"
        queries = [dim_query]

        # Module 1 — normative sources (top_k=4), restricted to the routed
        # framework set when routing is active (deterministic, backend-only).
        # Extra headroom: text-level dedup below drops overlapping duplicates,
        # so pull more candidates than the final budget.
        module1_raw = self.vectorstore.retrieve(
            query=dim_query,
            top_k=module1_top_k * MODULE_DEDUP_HEADROOM,
            role_filter=["module_1_normative"],
            framework_filter=module1_frameworks,
        )
        # Regional reserve pool: a second, narrower retrieval restricted to
        # the country's region-routed frameworks, so a guaranteed budget slot
        # can be enforced below regardless of how the general pool ranks.
        module1_regional_raw: list[dict[str, Any]] = []
        if module1_regional_frameworks:
            module1_regional_raw = self.vectorstore.retrieve(
                query=dim_query,
                top_k=MODULE1_REGIONAL_RESERVE * MODULE_DEDUP_HEADROOM,
                role_filter=["module_1_normative"],
                framework_filter=module1_regional_frameworks,
            )
        # Module 2 dimension reserve pool: dimension-tagged practical tools
        # (role module_2_practical) get their own restricted retrieval so the
        # reserve below can guarantee them budget for their dimension.
        module2_dimension_raw: list[dict[str, Any]] = []
        if module2_dimension_frameworks:
            module2_dimension_raw = self.vectorstore.retrieve(
                query=dim_query,
                top_k=MODULE2_DIMENSION_RESERVE * MODULE_DEDUP_HEADROOM,
                role_filter=["module_2_practical"],
                framework_filter=module2_dimension_frameworks,
            )
        # Module 2 — practical toolkits (top_k=3)
        module2_raw = self.vectorstore.retrieve(
            query=dim_query,
            top_k=module2_top_k * MODULE_DEDUP_HEADROOM,
            role_filter=["module_2_practical"],
        )
        # Workspace document (top_k=4, preamble-filtered). Multi-query RRF
        # restores the recall the old pipeline had; fetch extra raw candidates
        # because recursive splitting produces many text-identical overlapping
        # chunks — dedup needs enough distinct material to fill the small
        # document budget.
        doc_raw: list[dict[str, Any]] = []
        if workspace_id:
            doc_raw = self._retrieve_doc_bucket_multi_query(
                dimension=dimension,
                dim_query=dim_query,
                workspace_id=workspace_id,
                candidates=doc_top_k * 5,
            )
        # NOTE: do NOT slice to doc_top_k here — dedup must run first (below),
        # otherwise text-identical overlapping chunks consume the whole budget
        # and distinct document content never reaches the prompt.
        doc_filtered = [c for c in doc_raw if not self._is_preamble_chunk(c)]

        def _to_entry(r: dict[str, Any], role: str) -> dict[str, Any]:
            md = r.get("metadata", {}) or {}
            return {
                "chunk_id": r.get("chunk_id") or r.get("id"),
                "text": r.get("text", ""),
                "page_number": md.get("page_number") or r.get("page_number"),
                "section_title": md.get("section") or r.get("section_title"),
                "source_framework": md.get("framework", "") or r.get("source_framework", ""),
                "document_name": md.get("document_name", "") or r.get("document_name", ""),
                "similarity_score": r.get("similarity_score") or r.get("similarity", 0.0),
                "module_role": role,
                "roles": md.get("roles", ""),
            }

        module1 = self._prioritize_substantive(
            [self._truncate_chunk(_to_entry(c, "module_1_normative")) for c in module1_raw]
        )
        module1_regional = self._prioritize_substantive(
            [
                self._truncate_chunk(_to_entry(c, "module_1_normative"))
                for c in module1_regional_raw
            ]
        )
        module2_dimension = self._prioritize_substantive(
            [
                self._truncate_chunk(_to_entry(c, "module_2_practical"))
                for c in module2_dimension_raw
            ]
        )
        module2 = self._prioritize_substantive(
            [self._truncate_chunk(_to_entry(c, "module_2_practical")) for c in module2_raw]
        )
        doc = self._prioritize_substantive(
            [self._truncate_chunk(_to_entry(c, "document")) for c in doc_filtered]
        )

        # Deduplicate by chunk_id across the three pulls; drop near-identical
        # text in EVERY bucket (recursive splitting with overlap can produce
        # multiple chunk_ids with the same body, which would waste the small
        # per-bucket budgets on one repeated passage). Headroom requested above
        # means dedup drops redundant text while each bucket still fills to its
        # budget cap with DISTINCT content.
        seen: set[str] = set()
        seen_doc_text: set[str] = set()
        # PER-BUCKET text sets: the same passage can legitimately appear in a
        # normative and a practical source (a framework quoted in both), so
        # module1 and module2 must not share a dedup key.
        seen_module1_text: set[str] = set()
        seen_module2_text: set[str] = set()
        doc_clean: list[dict[str, Any]] = []
        module1_clean: list[dict[str, Any]] = []
        module2_clean: list[dict[str, Any]] = []
        for bucket in (module1, module2, doc):
            for c in bucket:
                cid = c.get("chunk_id")
                if cid and cid in seen:
                    continue
                if cid:
                    seen.add(cid)
                role = c.get("module_role")
                # Full normalized text key: cheap, and avoids false collisions
                # from repeated document headers/footers that a short prefix
                # key would produce.
                text_key = " ".join((c.get("text") or "").split()).lower()
                if role == "document":
                    # Cap the deduped document bucket at doc_top_k so the
                    # budget is filled with DISTINCT content.
                    if len(doc_clean) >= doc_top_k:
                        continue
                    if text_key in seen_doc_text:
                        continue
                    seen_doc_text.add(text_key)
                    doc_clean.append(c)
                elif role == "module_1_normative":
                    if len(module1_clean) >= module1_top_k:
                        continue
                    if text_key in seen_module1_text:
                        continue
                    seen_module1_text.add(text_key)
                    module1_clean.append(c)
                else:
                    if len(module2_clean) >= module2_top_k:
                        continue
                    if text_key in seen_module2_text:
                        continue
                    seen_module2_text.add(text_key)
                    module2_clean.append(c)

        # Guaranteed slots: at least one chunk from routed sources that the
        # similarity ranking would otherwise crowd out of the budget — the
        # country's region-routed frameworks (Singapore/AU) in Module 1, and
        # dimension-tagged practical tools in Module 2. Same eviction logic
        # for both buckets (see _enforce_reserve).
        if module1_regional_frameworks and module1_regional:
            self._enforce_reserve(
                clean=module1_clean,
                candidates=module1_regional,
                reserve=MODULE1_REGIONAL_RESERVE,
                budget=module1_top_k,
                seen_text=seen_module1_text,
                reserved_names=set(module1_regional_frameworks),
                dimension=dimension,
                bucket="module_1_regional",
            )
        if module2_dimension_frameworks and module2_dimension:
            self._enforce_reserve(
                clean=module2_clean,
                candidates=module2_dimension,
                reserve=MODULE2_DIMENSION_RESERVE,
                budget=module2_top_k,
                seen_text=seen_module2_text,
                reserved_names=set(module2_dimension_frameworks),
                dimension=dimension,
                bucket="module_2_dimension",
            )

        result = ModuleRetrievalResult(
            dimension=dimension,
            document_chunks=doc_clean,
            module1_chunks=module1_clean,
            module2_chunks=module2_clean,
            retrieval_queries=queries,
        )
        result.total_chunks = len(doc_clean) + len(module1_clean) + len(module2_clean)

        # Doc-bucket starvation guard: the module buckets can be healthy while
        # the uploaded document contributes nothing (e.g. a polluted query
        # string or an over-aggressive preamble filter). The LLM then assesses
        # the dimension without the document's own evidence — silently wrong
        # verdicts. Flag it loudly so regressions are visible in logs.
        if workspace_id and not doc_clean:
            logger.warning(
                "doc_bucket_starved",
                dimension=dimension,
                workspace_id=workspace_id,
                doc_candidates=len(doc_raw),
                doc_after_preamble_filter=len(doc_filtered),
                reason="No document chunks survived retrieval/filtering for this dimension.",
            )

        logger.info(
            "module_retrieval_complete",
            dimension=dimension,
            module1_chunks=len(module1_clean),
            module2_chunks=len(module2_clean),
            doc_chunks=len(doc_clean),
            total_chunks=result.total_chunks,
            module1_frameworks=module1_frameworks,
        )
        return result

    # ── Module 3 + Module 4 conditional budget retrieval ───────────────

    def retrieve_module34_chunks(
        self,
        dimension: str,
        workspace_id: str | None = None,
        module3_top_k: int = MODULE3_TOP_K,
        module4_top_k: int = MODULE4_TOP_K,
        doc_top_k: int = MODULE34_DOC_TOP_K,
        module3_dimension_frameworks: list[str] | None = None,
    ) -> Module34RetrievalResult:
        """Budgeted role-tagged retrieval for the conditional Module 3+4 call.

        Pulls at most `module3_top_k` chunks tagged module_3_implementation,
        `module4_top_k` tagged module_4_incident, and a small document slice
        (for responsible-agency grounding). Same discipline as Module 1+2
        retrieval:

        - The dimension's ASPECT-SPECIFIC query texts (definition + aspects)
          are used instead of a bare dimension-name query — the same fix that
          stopped the Module 1+2 doc-bucket leak. The bare name is the least
          specific vector and ranks off-topic content; aspects carry the
          constrained vocabulary (liability/redress for Accountability,
          accessibility/digital divide for Inclusivity, etc.).
        - Module 4 incident chunks additionally require the dimension-grounding
          check downstream (gap_analyzer), so an off-topic incident can never
          match on raw similarity alone.
        - The document slice is preamble-filtered like the Module 1 doc bucket.
        """
        profiles = self.get_or_build_profiles()
        profile = profiles.get(dimension)
        query_texts: list[str] = []
        if profile is not None:
            # Constrained, aspect-specific phrasing — NOT the bare dimension
            # name (the Module 1+2 retrieval fix, applied here too).
            query_texts.append(profile.definition)
            query_texts.extend(profile.aspects)
        if not query_texts:
            query_texts = [dimension]
        # A single combined query string for the role-filtered retrieve calls.
        # Keep it bounded (~3 texts) so it stays dimension-focused.
        combined_query = " | ".join(query_texts[:4])

        module3_raw = self.vectorstore.retrieve(
            query=combined_query,
            top_k=module3_top_k * 2,
            role_filter=["module_3_implementation"],
        )
        # Module 3 dimension reserve pool: dimension-tagged implementation
        # sources (role module_3_implementation) get their own restricted
        # retrieval so the reserve below can guarantee them budget.
        module3_dimension_raw: list[dict[str, Any]] = []
        if module3_dimension_frameworks:
            module3_dimension_raw = self.vectorstore.retrieve(
                query=combined_query,
                top_k=MODULE3_DIMENSION_RESERVE * 2,
                role_filter=["module_3_implementation"],
                framework_filter=module3_dimension_frameworks,
            )
        # Grounding is applied HERE, not only downstream. gap_analyzer re-checks
        # every incident with the same _chunk_matches_dimension gate before it
        # writes a Module 4 entry, so an ungrounded chunk retrieved into this
        # bucket is not merely useless — it silently consumes one of the few
        # slots and the dimension ends up reporting fewer cases than it paid
        # for. Privacy was shipping 1 usable case out of 3 for exactly this
        # reason. Filtering first costs nothing and spends every slot on a
        # chunk that can actually survive to the output.
        module4_raw = self._select_incident_pool(
            self.vectorstore.retrieve(
                query=combined_query,
                top_k=max(MODULE4_CANDIDATE_POOL, module4_top_k * 2),
                role_filter=["module_4_incident"],
            ),
            dimension=dimension,
            limit=module4_top_k * 2,
        )

        doc_raw: list[dict[str, Any]] = []
        if workspace_id:
            doc_raw = self._retrieve_doc_bucket_multi_query(
                dimension=dimension,
                dim_query=dimension,
                workspace_id=workspace_id,
                candidates=doc_top_k * 5,
            )
        doc_filtered = [c for c in doc_raw if not self._is_preamble_chunk(c)]

        def _to_entry(r: dict[str, Any], role: str) -> dict[str, Any]:
            md = r.get("metadata", {}) or {}
            return {
                "chunk_id": r.get("chunk_id") or r.get("id"),
                "text": r.get("text", ""),
                "page_number": md.get("page_number") or r.get("page_number"),
                "section_title": md.get("section") or r.get("section_title"),
                "source_framework": md.get("framework", "") or r.get("source_framework", ""),
                "document_name": md.get("document_name", "") or r.get("document_name", ""),
                "similarity_score": r.get("similarity_score") or r.get("similarity", 0.0),
                "module_role": role,
                "roles": md.get("roles", ""),
            }

        module3_dimension = self._prioritize_substantive(
            [
                self._truncate_chunk(_to_entry(c, "module_3_implementation"))
                for c in module3_dimension_raw
            ]
        )
        module3 = self._prioritize_substantive(
            [self._truncate_chunk(_to_entry(c, "module_3_implementation")) for c in module3_raw]
        )
        module4 = self._prioritize_substantive(
            [self._truncate_chunk(_to_entry(c, "module_4_incident")) for c in module4_raw]
        )
        doc = self._prioritize_substantive(
            [self._truncate_chunk(_to_entry(c, "document")) for c in doc_filtered]
        )

        seen: set[str] = set()
        module3_clean: list[dict[str, Any]] = []
        module4_clean: list[dict[str, Any]] = []
        doc_clean: list[dict[str, Any]] = []
        # Module 3 text-dedup set (Module 4 and doc buckets don't text-dedup
        # here; module 3's reserve below needs it to avoid inserting a
        # duplicate of a surviving implementation chunk).
        seen_module3_text: set[str] = set()
        # ENFORCE the per-bucket budget AFTER dedup (the raw pulls request 2x
        # for dedup headroom, but the prompt budget is fixed at module3_top_k
        # + module4_top_k + doc_top_k). Without this slice, up to 6+6 chunks
        # would reach the combined Module 3+4 call, ballooning its context
        # past the ~10-chunk Module 1+2 budget.
        for bucket, clean, cap in (
            (module3, module3_clean, module3_top_k),
            (module4, module4_clean, module4_top_k),
            (doc, doc_clean, doc_top_k),
        ):
            for c in bucket:
                if len(clean) >= cap:
                    break
                cid = c.get("chunk_id")
                if cid and cid in seen:
                    continue
                if cid:
                    seen.add(cid)
                if bucket is module3:
                    text_key = " ".join((c.get("text") or "").split()).lower()
                    if text_key in seen_module3_text:
                        continue
                    seen_module3_text.add(text_key)
                clean.append(c)

        # Module 3 dimension reserve: same guarantee as Module 1/2 — a
        # dimension-tagged implementation source keeps a budget slot for its
        # dimension even when the general pool ranks other sources higher.
        if module3_dimension_frameworks and module3_dimension:
            self._enforce_reserve(
                clean=module3_clean,
                candidates=module3_dimension,
                reserve=MODULE3_DIMENSION_RESERVE,
                budget=module3_top_k,
                seen_text=seen_module3_text,
                reserved_names=set(module3_dimension_frameworks),
                dimension=dimension,
                bucket="module_3_dimension",
            )

        result = Module34RetrievalResult(
            dimension=dimension,
            module3_chunks=module3_clean,
            module4_chunks=module4_clean,
            document_chunks=doc_clean,
        )
        result.total_chunks = len(module3_clean) + len(module4_clean) + len(doc_clean)

        logger.info(
            "module34_retrieval_complete",
            dimension=dimension,
            module3_chunks=len(module3_clean),
            module4_chunks=len(module4_clean),
            doc_chunks=len(doc_clean),
            total_chunks=result.total_chunks,
        )
        return result
