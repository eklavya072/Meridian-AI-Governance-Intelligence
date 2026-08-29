from __future__ import annotations

import structlog
from typing import Any

from src.framework_sync import load_frameworks_config
from src.vectorstore import VectorStore

logger = structlog.get_logger()


# Per-framework chunk counts, keyed by the collection size at the time they
# were computed. The corpus only changes when something is ingested or purged,
# and both move the total, so the key is a sufficient invalidation signal.
_COUNT_CACHE: dict[int, dict[str, int]] = {}


def _framework_chunk_counts(vector_store: VectorStore) -> dict[str, int]:
    """Count chunks per framework in ONE pass over the collection metadata.

    This used to be one ChromaDB query per configured framework — 33 queries
    for 33 frameworks, each scanning a ~38k-chunk collection. The endpoint took
    4.5 seconds on the current corpus and 19.6 seconds on a larger one, and the
    Analysis page awaits it before it renders anything, so the workspace
    dropdown and the analysis body both sat empty for the duration.

    One paged sweep plus a dict is the same information at a fraction of the
    cost, and the result is cached so repeated page loads are free.
    """
    total = vector_store.collection.count()
    cached = _COUNT_CACHE.get(total)
    if cached is not None:
        return cached

    counts: dict[str, int] = {}
    offset = 0
    while True:
        rows = vector_store.collection.get(
            include=["metadatas"], limit=5000, offset=offset
        )
        metadatas = rows.get("metadatas") or []
        if not metadatas:
            break
        for m in metadatas:
            name = (m or {}).get("framework") or ""
            if name:
                counts[name] = counts.get(name, 0) + 1
        offset += len(metadatas)

    # Single-entry cache: an older key is stale by definition once the
    # collection size has moved.
    _COUNT_CACHE.clear()
    _COUNT_CACHE[total] = counts
    logger.info(
        "framework_chunk_counts_computed",
        collection_size=total,
        frameworks_with_chunks=len(counts),
    )
    return counts


def get_framework_library(vector_store: VectorStore) -> list[dict[str, Any]]:
    frameworks_config = load_frameworks_config()
    counts = _framework_chunk_counts(vector_store)
    library: list[dict[str, Any]] = []

    for fw in frameworks_config:
        name = fw.get("name", "Unknown")
        indexed_count = counts.get(name, 0)
        library.append({
            "name": name,
            "version": fw.get("version", ""),
            "website": fw.get("website", ""),
            "official_source_url": fw.get("pdf_url", ""),
            "indexed": indexed_count > 0,
            "chunk_count": indexed_count,
            "status": "indexed" if indexed_count > 0 else "not_indexed",
        })

    return library
