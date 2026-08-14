from __future__ import annotations

import structlog
from typing import Any

from src.framework_sync import load_frameworks_config
from src.vectorstore import VectorStore

logger = structlog.get_logger()


def get_framework_library(vector_store: VectorStore) -> list[dict[str, Any]]:
    frameworks_config = load_frameworks_config()
    library: list[dict[str, Any]] = []

    for fw in frameworks_config:
        name = fw.get("name", "Unknown")
        indexed_count = vector_store.count_chunks(framework_filter=[name])
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
