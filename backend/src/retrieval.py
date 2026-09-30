from __future__ import annotations

import os
import re as _re
import threading
from typing import Any

import structlog
from pydantic import BaseModel, Field

from src.deterministic import _chunk_matches_dimension, is_low_information_fragment
from src.models import DimensionProfile
from src.tracing import traced
from src.utils import batch_fetch_chunk_metadata, l2_normalize, reciprocal_rank_fusion


def _dedup_key(text: str) -> str:
    """Normalized alphanumeric signature used for near-duplicate detection."""
    return _re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _is_near_duplicate(key: str, accepted_keys: list[str]) -> bool:
    """True when `key` is a containment near-duplicate of something accepted.

    Exact-text dedup is not enough. Chunk boundaries drift between ingestions
    and overlapping windows re-emit the same passage shifted by a few
    characters, so the same provision reappears as many textually DISTINCT
    chunks ("...fostering sustainable growth" vs "...sustainable growth"). A
    fixed candidate budget spent on those copies would surface only a few real
    passages. Containment catches truncation at either end, which is exactly
    the shape this artifact takes.
    """
    if not key:
        return True
    for k in accepted_keys:
        if key in k or k in key:
            return True
    return False


logger = structlog.get_logger()


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
# Module 1 — the LLM judges THE DOCUMENT, not the frameworks. Six chunks lets a
# long legal text's operative articles (penalties, disclosure duties) reach the
# prompt alongside its recitals. This costs prompt tokens, not extra requests.
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
# MODULE4_MAX_PER_DOCUMENT: without a cap, one large report takes every slot.
# Two slots lets a genuinely dominant source stay dominant while still
# guaranteeing a second, independent case reaches the prompt.
MODULE4_CANDIDATE_POOL = int(os.getenv("MODULE4_CANDIDATE_POOL", "60"))
MODULE4_MAX_PER_DOCUMENT = int(os.getenv("MODULE4_MAX_PER_DOCUMENT", "2"))
MODULE34_DOC_TOP_K = int(os.getenv("MODULE34_DOC_TOP_K", "2"))

# Module buckets are de-duplicated on normalized text (same as the document
# bucket) so two near-duplicate overlapping chunks cannot both consume slots in
# the small per-bucket budget. Headroom multiplier: pull extra candidates so
# dedup can drop redundant text and still fill the budget with DISTINCT content.
MODULE_DEDUP_HEADROOM = int(os.getenv("MODULE_DEDUP_HEADROOM", "3"))

# Sparse BM25 fused with the dense sweep by reciprocal rank fusion, applied to
# the workspace-document bucket: recall insurance, not a scoring change.
USE_HYBRID_SEARCH = os.getenv("USE_HYBRID_SEARCH", "true").lower() == "true"

# Scoring pool: feeds deterministic pattern scoring, not an LLM prompt, so it
# is sized for coverage of the document rather than for a token budget.
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


class RetrievalPipeline:
    def __init__(self, vectorstore):
        self.vectorstore = vectorstore
        self._doc_corpus_cache: dict[str, list[dict[str, Any]]] = {}
        # Per-instance cache (NOT class-level — a class-level dict would
        # leak every workspace's full chunk text across every analysis run
        # for the process lifetime). See _workspace_chunk_texts.
        self._lexical_cache: dict[str, list[tuple[str, str]]] = {}
        # Per-workspace lock so concurrent dimension workers coalesce into one
        # fetch of the workspace document instead of each re-fetching it
        # before the cache is warm. See _workspace_chunk_texts.
        self._lexical_cache_locks: dict[str, threading.Lock] = {}
        self._lexical_cache_locks_guard = threading.Lock()

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
            key = str(md.get("document_name") or md.get("doc_id") or c.get("chunk_id") or id(c))
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

        definitions: dict[str, str] = {
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

        core = {"Transparency", "Accountability", "Fairness", "Privacy", "Safety", "Human Autonomy"}

        # Stored, not just returned: the early return above is the cache.
        for dim, definition in definitions.items():
            DIMENSION_PROFILES[dim] = DimensionProfile(
                dimension=dim,
                definition=definition,
                aspects=self._generate_aspects(dim, definition),
                is_core=dim in core,
            )

        return DIMENSION_PROFILES

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
        except Exception as exc:
            # Silence here is indistinguishable from "the store holds nothing
            # relevant". A failed query shrinks the candidate pool that every
            # verdict is computed from, so it has to be visible in the run's
            # own log rather than inferred later from a thin evidence set.
            logger.warning(
                "vector_query_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                top_k=top_k,
                where=where,
            )
        return scored

    # ── Module 1 + Module 2 combined budget retrieval ─────────────────

    _PREAMBLE_MARKERS = (
        "intentionally left blank",
        "acknowledgment",
        "acknowledgement",
        "table of contents",
        "contents",
        "copyright",
        "all rights reserved",
        "this page has been intentionally left blank",
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
        # page_number inside metadata, not at the top level.
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

    def _prioritize_substantive(self, bucket: list[dict[str, Any]]) -> list[dict[str, Any]]:
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

        # Coalesce concurrent callers onto ONE fetch: every dimension worker can
        # call this in the same instant, before the cache is warm. Per-workspace
        # (not a single global lock) so unrelated workspaces never block each
        # other.
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
                logger.warning(
                    "workspace_chunk_fetch_failed", workspace_id=workspace_id, error=str(exc)
                )
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

        Embedding similarity can rank recital paraphrases above the operative
        articles within the dense candidate window. A term-overlap score against
        the dimension's high-precision vocabulary (DIMENSION_CORE_TERMS) plus
        the query text catches exact statutory language ("penalties",
        "Article 99", "shall notify"), and because it scores every chunk in the
        document it can surface a chunk dense search never returned at all.
        """
        from src.deterministic import DIMENSION_CORE_TERMS

        # Core terms (curated, high-precision governance vocabulary — "data
        # protection", "grievance", "carbon footprint") are kept SEPARATE
        # from the incidental words in query_texts, which is usually a
        # dimension's full definition prose. Pooled together, generic overlap
        # with that prose would outscore a chunk that only matches the curated
        # core terms — exactly the signal this hybrid pass exists to protect.
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
        dimension across many sections using varied terminology. So the
        dimension's definition and aspects are embedded separately and
        RRF-fused. Module buckets keep a single query (they are small,
        role-tagged framework sets).

        HYBRID: a lexical/keyword rank list (see _lexical_candidates) is
        RRF-fused alongside the dense rank lists, so exact statutory
        vocabulary a paraphrase embedding under-ranks — or never returns as
        a candidate at all — still gets a fair shot at the budget.
        """
        profiles = self.get_or_build_profiles()
        profile = profiles.get(dimension)

        where: dict[str, Any] = {"workspace_id": {"$in": [workspace_id]}}
        # The bare dimension name ("Accountability") is the LEAST specific
        # query vector and ranks off-topic paragraphs (an events calendar) into
        # the bucket. The definition + aspect queries carry the constrained
        # phrasing, so the bare name is dropped unless dim_query carries real
        # user intent (e.g. chat), where it is preserved verbatim.
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
        # One batched embed call for all query variants (definition + aspects,
        # typically 4-6 texts) instead of one call per variant.
        try:
            query_embs = list(self.vectorstore.embedding_service.embed(query_texts))
            if len(query_embs) != len(query_texts):
                raise ValueError("batch embed returned mismatched length")
        except Exception:
            query_embs = [self.vectorstore.embed_query(t) for t in query_texts]
        for _text, emb in zip(query_texts, query_embs):
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
        # Weighted 3x in the fusion, not 1x. The query texts expand to 4-7
        # dense variants, and a chunk that ranks decently across several of
        # them accumulates more RRF score than a single rank-0 lexical vote can
        # offset — so a one-line statutory duty inside an unrelated table would
        # never win a slot. Appending the lexical list several times gives its
        # exact-term signal real weight without changing the shared
        # reciprocal_rank_fusion() utility.
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
            out.append(
                {
                    "chunk_id": cid,
                    "text": m.get("text", ""),
                    "metadata": {
                        "page_number": m.get("page_number"),
                        "section": m.get("section_title"),
                        "framework": m.get("source_framework", ""),
                        "document_name": m.get("document_name", ""),
                    },
                    "similarity_score": round(best_sim.get(cid, 0.0), 4),
                }
            )
        return out

    @traced("retrieve", "dimension")
    def retrieve_scoring_pool(
        self,
        dimension: str,
        workspace_id: str | None = None,
        candidates: int = SCORING_POOL_CANDIDATES,
        max_chunks: int = SCORING_POOL_MAX,
    ) -> list[dict[str, Any]]:
        """Wide sweep of the workspace document for deterministic scoring.

        The pattern scorer in evidence_strength.py costs nothing per chunk, so
        it sees as much of the document as possible: a long statute would
        otherwise be scored from a sliver of itself. The preamble filter is not
        applied; recitals state purpose in soft language, which the tier system
        already grades as weak.
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
        reserved_in_budget = [c for c in clean if c.get("source_framework") in reserved_names]
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

    def _workspace_doc_corpus(self, workspace_id: str) -> list[dict[str, Any]]:
        """Every chunk of the workspace's own uploaded documents.

        BM25 searches this rather than the dense candidate pool — the
        difference between re-ordering and RECOVERY. Fused over the dense pool
        alone, sparse retrieval can only reshuffle what dense already found.

        Cached per workspace for the life of the pipeline instance: the set is
        small (~150 chunks for a two-document workspace) and would otherwise be
        re-read once per dimension per module role.
        """
        cached = self._doc_corpus_cache.get(workspace_id)
        if cached is not None:
            return cached
        corpus: list[dict[str, Any]] = []
        try:
            raw = self.vectorstore.collection.get(
                where={"workspace_id": workspace_id},
                include=["metadatas", "documents"],
            )
            for cid, text, md in zip(
                raw.get("ids") or [], raw.get("documents") or [], raw.get("metadatas") or []
            ):
                corpus.append({"chunk_id": cid, "text": text or "", "metadata": md or {}})
        except Exception as exc:
            logger.error("workspace_doc_corpus_failed", workspace_id=workspace_id, error=str(exc))
        self._doc_corpus_cache[workspace_id] = corpus
        return corpus

    def _apply_hybrid(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        corpus: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Re-rank the candidate pool by fusing BM25 ranks with the dense order.

        Any failure returns the input untouched: worse ordering is recoverable,
        a dropped provision is not.
        """
        try:
            from src.hybrid_search import hybrid_search, sparse_only_recall

            # Raw vector-store hits key their id as "id"; entries already
            # through _to_entry use "chunk_id". Normalise onto a private key so
            # fusion works at either stage without mutating the caller's shape.
            normalised = []
            for c in candidates:
                cid = c.get("chunk_id") or c.get("id")
                if not cid:
                    return candidates
                normalised.append({**c, "_fuse_id": cid})

            search_corpus = normalised
            if corpus:
                seen = {c["_fuse_id"] for c in normalised}
                search_corpus = normalised + [
                    {**c, "_fuse_id": c["chunk_id"]}
                    for c in corpus
                    if c.get("chunk_id") and c["chunk_id"] not in seen
                ]

            fused = hybrid_search(
                query,
                dense_results=normalised,
                corpus=search_corpus,
                top_k=len(normalised),
                id_key="_fuse_id",
            )
            if len(fused) < len(candidates):
                logger.warning(
                    "hybrid_dropped_candidates", before=len(candidates), after=len(fused)
                )
                return candidates
            logger.info("hybrid_applied", promoted_by_bm25=sparse_only_recall(fused))
            return [{k: v for k, v in c.items() if k != "_fuse_id"} for c in fused]
        except Exception as exc:
            logger.error("hybrid_search_failed", error=str(exc))
            return candidates

    @traced("retrieve", "dimension")
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
        are never framework-filtered. When omitted, all module_1_normative
        sources are eligible.

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
        # Workspace document (preamble-filtered), by multi-query RRF. Fetch extra
        # raw candidates because recursive splitting produces many
        # text-identical overlapping chunks — dedup needs enough distinct
        # material to fill the small document budget.
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

        # Fuse over the WORKSPACE DOCUMENT bucket specifically. This bucket
        # decides verdicts — it holds the country's own provisions — and its
        # budget is small, so which candidates survive the cut matters more
        # here than anywhere else in the pipeline. A statutory clause a dense
        # sweep ranks low because its phrasing is unusual ("shall ensure
        # automatic recording of events") is exactly what BM25 recovers, and a
        # provision that never reaches the prompt produces a Missing verdict
        # indistinguishable from genuine absence.
        if USE_HYBRID_SEARCH and doc_filtered and workspace_id:
            doc_filtered = self._apply_hybrid(
                dim_query, doc_filtered, self._workspace_doc_corpus(workspace_id)
            )

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
            [self._truncate_chunk(_to_entry(c, "module_1_normative")) for c in module1_regional_raw]
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

    @traced("retrieve", "dimension")
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
          are used instead of a bare dimension-name query, which is the least
          specific vector and ranks off-topic content.
        - Module 4 incident chunks additionally require the dimension-grounding
          check downstream (gap_analyzer), so an off-topic incident can never
          match on raw similarity alone.
        - The document slice is preamble-filtered like the Module 1 doc bucket.
        """
        profiles = self.get_or_build_profiles()
        profile = profiles.get(dimension)
        query_texts: list[str] = []
        if profile is not None:
            # Constrained, aspect-specific phrasing — NOT the bare dimension name.
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
        # every incident with the same _chunk_matches_dimension gate, so an
        # ungrounded chunk retrieved into this bucket would silently consume one
        # of the few slots. Filtering first spends every slot on a chunk that
        # can survive to the output.
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
