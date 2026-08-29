from __future__ import annotations

import os
from typing import Any

from src.models import AspectGroup, EvidenceGraph, EvidenceItem
from src.utils import cosine_similarity, l2_normalize

EVIDENCE_SIMILARITY_THRESHOLD = float(os.getenv("EVIDENCE_SIMILARITY_THRESHOLD", "0.88"))
MIN_EVIDENCE_TEXT_LENGTH = int(os.getenv("MIN_EVIDENCE_TEXT_LENGTH", "30"))


class EvidenceGraphBuilder:
    def __init__(self, embed_function):
        self._embed = embed_function
        self._profiles: dict[str, dict[str, Any]] = {}

    def set_dimension_profiles(self, profiles: dict[str, dict[str, Any]]):
        self._profiles = profiles

    def build_graph(
        self,
        dimension: str,
        document_chunks: list[dict[str, Any]],
        framework_chunks: list[dict[str, Any]],
    ) -> EvidenceGraph:
        if not document_chunks and not framework_chunks:
            profile = self._profiles.get(dimension, {})
            aspects = profile.get("aspects", [dimension])
            return EvidenceGraph(
                dimension=dimension,
                aspect_groups=[],
                missing_aspects=aspects,
                evidence_quality_score=0.0,
                total_chunks_retrieved=0,
                total_chunks_after_synthesis=0,
            )

        all_items = self._build_evidence_items(dimension, document_chunks, framework_chunks)
        deduped = self._deduplicate(all_items)
        aspect_groups = self._cluster_by_aspect(dimension, deduped)
        missing_aspects = self._find_missing_aspects(dimension, aspect_groups)

        for group in aspect_groups:
            self._compute_group_quality(group)
            group.synthesized_claim = self._synthesize_claim(group)

        quality_score, quality_factors = self._compute_overall_quality(
            aspect_groups, missing_aspects
        )
        source_div = self._compute_source_diversity(all_items)
        redundancy = self._compute_redundancy(len(all_items), len(deduped))
        completeness = self._compute_coverage_completeness(dimension, aspect_groups)

        return EvidenceGraph(
            dimension=dimension,
            aspect_groups=aspect_groups,
            missing_aspects=missing_aspects,
            evidence_quality_score=quality_score,
            quality_factors=quality_factors,
            source_diversity_score=source_div,
            coverage_completeness=completeness,
            redundancy_ratio=redundancy,
            total_chunks_retrieved=len(all_items),
            total_chunks_after_synthesis=len(deduped),
        )

    def _build_evidence_items(
        self,
        dimension: str,
        document_chunks: list[dict[str, Any]],
        framework_chunks: list[dict[str, Any]],
    ) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        seen = set()

        for chunk in document_chunks:
            text = (chunk.get("text") or chunk.get("content") or "").strip()
            if len(text) < MIN_EVIDENCE_TEXT_LENGTH:
                continue
            cid = chunk.get("chunk_id") or text[:100]
            if cid in seen:
                continue
            seen.add(cid)
            items.append(
                EvidenceItem(
                    chunk_id=cid,
                    text=text,
                    page_number=chunk.get("page_number"),
                    section_title=chunk.get("section_title"),
                    source_framework=chunk.get("source_framework", "document"),
                    similarity_score=chunk.get("reranker_score")
                    or chunk.get("rrf_score")
                    or chunk.get("similarity_score"),
                    is_document=True,
                )
            )

        for chunk in framework_chunks:
            text = (chunk.get("text") or chunk.get("content") or "").strip()
            if len(text) < MIN_EVIDENCE_TEXT_LENGTH:
                continue
            cid = chunk.get("chunk_id") or text[:100]
            if cid in seen:
                continue
            seen.add(cid)
            items.append(
                EvidenceItem(
                    chunk_id=cid,
                    text=text,
                    page_number=chunk.get("page_number"),
                    section_title=chunk.get("section_title"),
                    source_framework=chunk.get("source_framework", "framework"),
                    similarity_score=chunk.get("reranker_score")
                    or chunk.get("rrf_score")
                    or chunk.get("similarity_score"),
                    is_document=False,
                )
            )

        return items

    def _deduplicate(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        if len(items) <= 1:
            return items

        embeddings = [self._embed(item.text) for item in items]
        normalized = [l2_normalize(e) for e in embeddings]

        keep = [True] * len(items)
        for i in range(len(items)):
            if not keep[i]:
                continue
            for j in range(i + 1, len(items)):
                if not keep[j]:
                    continue
                sim = cosine_similarity(normalized[i], normalized[j])
                if sim >= EVIDENCE_SIMILARITY_THRESHOLD:
                    merged = self._merge_evidence(items[i], items[j], sim)
                    items[i] = merged
                    keep[j] = False

        return [items[i] for i in range(len(items)) if keep[i]]

    def _merge_evidence(self, a: EvidenceItem, b: EvidenceItem, similarity: float) -> EvidenceItem:
        longer = a if len(a.text) >= len(b.text) else b
        shorter = b if len(a.text) >= len(b.text) else a
        if longer.page_number is None:
            longer.page_number = shorter.page_number
        if longer.similarity_score is None:
            longer.similarity_score = shorter.similarity_score
        elif shorter.similarity_score is not None:
            longer.similarity_score = max(longer.similarity_score, shorter.similarity_score)
        return longer

    def _cluster_by_aspect(self, dimension: str, items: list[EvidenceItem]) -> list[AspectGroup]:
        profile = self._profiles.get(dimension, {})
        aspects = profile.get("aspects", [dimension])
        aspect_embeddings = {asp: l2_normalize(self._embed(asp)) for asp in aspects}

        group_map: dict[str, list[EvidenceItem]] = {asp: [] for asp in aspects}
        unclustered: list[EvidenceItem] = []

        for item in items:
            item_emb = l2_normalize(self._embed(item.text))
            best_aspect = aspects[0]
            best_score = 0.0
            for asp, asp_emb in aspect_embeddings.items():
                score = cosine_similarity(item_emb, asp_emb)
                if score > best_score:
                    best_score = score
                    best_aspect = asp
            if best_score >= 0.35:
                item.aspect = best_aspect
                item.semantic_relevance = best_score
                group_map.setdefault(best_aspect, []).append(item)
            else:
                unclustered.append(item)

        if unclustered:
            group_map.setdefault(aspects[0], []).extend(unclustered)

        return [
            AspectGroup(aspect=asp, evidence=items) for asp, items in group_map.items() if items
        ]

    def _find_missing_aspects(self, dimension: str, aspect_groups: list[AspectGroup]) -> list[str]:
        profile = self._profiles.get(dimension, {})
        aspects = profile.get("aspects", [])
        covered = {g.aspect for g in aspect_groups}
        return [a for a in aspects if a not in covered]

    def _compute_group_quality(self, group: AspectGroup):
        if not group.evidence:
            group.coverage_quality = 0.0
            group.coverage_estimate = "missing"
            return

        scores = [e.semantic_relevance for e in group.evidence if e.semantic_relevance > 0]
        avg_relevance = sum(scores) / len(scores) if scores else 0.0

        has_multiple_sources = len({e.source_framework for e in group.evidence}) > 1
        has_verification = any(e.verified for e in group.evidence)
        text_density = sum(len(e.text) for e in group.evidence)
        reranker_scores = [
            e.similarity_score
            for e in group.evidence
            if e.similarity_score is not None and e.similarity_score > 1.0
        ]
        has_reranker = len(reranker_scores) > 0

        quality = avg_relevance * 0.4
        if has_multiple_sources:
            quality += 0.2
        if has_verification:
            quality += 0.1
        if has_reranker:
            quality += 0.15
        quality += min(1.0, text_density / 5000) * (0.15 if has_reranker else 0.3)

        group.coverage_quality = round(min(1.0, quality), 3)

        if group.coverage_quality >= 0.7:
            group.coverage_estimate = "covered"
        elif group.coverage_quality >= 0.35:
            group.coverage_estimate = "partial"
        else:
            group.coverage_estimate = "weak"

    def _synthesize_claim(self, group: AspectGroup) -> str:
        if not group.evidence:
            return ""
        texts = [e.text for e in group.evidence[:3]]
        combined = " ".join(texts)
        if len(combined) > 800:
            combined = combined[:800] + "..."
        return combined

    def _compute_overall_quality(
        self, aspect_groups: list[AspectGroup], missing_aspects: list[str]
    ) -> tuple[float, dict[str, float]]:
        if not aspect_groups:
            return 0.0, {"no_aspect_groups": 1.0}

        avg_group_quality = sum(g.coverage_quality for g in aspect_groups) / len(aspect_groups)

        total_aspects = len(aspect_groups) + len(missing_aspects)
        coverage_ratio = len(aspect_groups) / total_aspects if total_aspects > 0 else 0.0

        all_evidence = [e for g in aspect_groups for e in g.evidence]
        doc_sources = len({e.source_framework for e in all_evidence if e.is_document})
        fw_sources = len({e.source_framework for e in all_evidence if not e.is_document})
        total_sources = doc_sources + fw_sources
        source_bonus = min(0.15, total_sources * 0.03)

        diversity = len({e.source_framework for e in all_evidence})
        diversity_bonus = min(0.1, diversity * 0.02)

        reranker_bonus = 0.0
        if all_evidence:
            has_reranker = any(
                e.similarity_score is not None and e.similarity_score > 1.0 for e in all_evidence
            )
            if has_reranker:
                reranker_bonus = 0.05

        quality = (
            avg_group_quality * 0.5
            + coverage_ratio * 0.25
            + source_bonus * 0.1
            + diversity_bonus * 0.1
            + reranker_bonus * 0.05
        )

        factors = {
            "avg_group_quality": round(avg_group_quality, 3),
            "coverage_ratio": round(coverage_ratio, 3),
            "source_bonus": round(source_bonus, 3),
            "diversity_bonus": round(diversity_bonus, 3),
            "reranker_bonus": round(reranker_bonus, 3),
        }

        return round(min(1.0, quality), 3), factors

    def _compute_source_diversity(self, items: list[EvidenceItem]) -> float:
        if not items:
            return 0.0
        sources = {e.source_framework for e in items}
        return min(1.0, len(sources) / 5.0)

    def _compute_redundancy(self, before: int, after: int) -> float:
        if before == 0:
            return 0.0
        return round(1.0 - (after / before), 3)

    def _compute_coverage_completeness(
        self, dimension: str, aspect_groups: list[AspectGroup]
    ) -> float:
        profile = self._profiles.get(dimension, {})
        aspects = profile.get("aspects", [])
        if not aspects:
            return 1.0
        covered = {g.aspect for g in aspect_groups if g.coverage_quality >= 0.35}
        return round(len(covered) / len(aspects), 3)
