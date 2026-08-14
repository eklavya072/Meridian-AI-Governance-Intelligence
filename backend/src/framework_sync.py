from __future__ import annotations

import hashlib
import os
import structlog
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

from src.vectorstore import VectorStore
from src.ingestion import Chunk, ingest_document

logger = structlog.get_logger()

FRAMEWORKS_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "frameworks.yaml"
RAW_POLICIES_DIR = Path(__file__).parent.parent / "data" / "raw_policies"


def load_frameworks_config() -> list[dict[str, Any]]:
    with open(FRAMEWORKS_CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)
    return config.get("frameworks", [])


def compute_file_hash(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class FrameworkSyncService:
    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store
        RAW_POLICIES_DIR.mkdir(parents=True, exist_ok=True)

    def sync_all(self) -> list[dict[str, Any]]:
        frameworks = load_frameworks_config()
        results: list[dict[str, Any]] = []

        for fw in frameworks:
            result = self.sync_framework(fw)
            results.append(result)

        return results

    def sync_framework(self, fw_config: dict[str, Any]) -> dict[str, Any]:
        name = fw_config["name"]
        pdf_url = fw_config.get("pdf_url", "")
        expected_version = fw_config.get("version", "")

        local_path = RAW_POLICIES_DIR / f"{name.replace(' ', '_').replace('/', '_')}.pdf"
        framework_known_path = fw_config.get("local_path")

        if framework_known_path:
            # Relative local_path values in config/frameworks.yaml are written
            # relative to the project ROOT (e.g. "backend/data/raw_policies/…"),
            # so resolve them against it — the sync must work from any CWD.
            resolved_path = Path(framework_known_path)
            if not resolved_path.is_absolute():
                resolved_path = Path(__file__).parent.parent.parent / resolved_path
            local_path = resolved_path
        elif not local_path.exists():
            if pdf_url:
                try:
                    local_path = self.download_pdf(name, pdf_url, local_path)
                except Exception as exc:
                    logger.error("framework_download_failed", name=name, error=str(exc))
                    return {
                        "name": name,
                        "version": expected_version,
                        "status": "error",
                        "error": f"Download failed: {exc}",
                        "chunk_count": 0,
                    }
            else:
                logger.warning("no_pdf_url_for_framework", name=name)
                return {
                    "name": name,
                    "version": expected_version,
                    "status": "error",
                    "error": "No PDF URL configured.",
                    "chunk_count": 0,
                }

        if not local_path.exists():
            return {
                "name": name,
                "version": expected_version,
                "status": "error",
                "error": "Local PDF not found and download failed.",
                "chunk_count": 0,
            }

        current_hash = compute_file_hash(local_path)
        stored_hash = fw_config.get("checksum")

        if stored_hash and current_hash == stored_hash:
            existing_count = self.vector_store.count_chunks(framework_filter=[name])
            if existing_count > 0:
                logger.info("framework_unchanged_skipping", name=name)
                return {
                    "name": name,
                    "version": expected_version,
                    "status": "synced",
                    "checksum": current_hash,
                    "chunk_count": existing_count,
                }

        # INGEST FIRST, then delete the old chunks. Deleting before ingestion
        # means an interrupted sync (crash, download/parse failure, process
        # kill) silently leaves the framework with ZERO chunks — this is what
        # happened to the ASEAN Guide during an interrupted backend re-sync.
        try:
            chunks = ingest_document(
                file_path=local_path,
                framework_name=name,
                roles=fw_config.get("roles"),
                source_type=fw_config.get("source_type"),
            )
            # ChromaDB's `roles` metadata filter is EQUALITY-ONLY (this
            # version rejects $contains/$in/$or on strings). A framework with
            # multiple roles (e.g. a practical tool that also serves as an
            # implementation mechanism) would store one comma-joined roles
            # string that matches NEITHER single-role query. Expand such
            # frameworks into per-role chunk copies — each copy carries a
            # single role so role-filtered retrieval matches.
            role_list = fw_config.get("roles") or []
            if len(role_list) > 1:
                expanded: list[Chunk] = []
                for role in role_list:
                    for c in chunks:
                        copy = c.model_copy(deep=True)
                        copy.chunk_id = str(uuid.uuid4())
                        copy.metadata["roles"] = role
                        expanded.append(copy)
                chunks = expanded
                logger.info(
                    "framework_multi_role_expanded",
                    name=name,
                    roles=role_list,
                    base_chunks=len(chunks) // len(role_list),
                    expanded_chunks=len(chunks),
                )
        except Exception as exc:
            logger.error("framework_ingestion_failed", name=name, error=str(exc))
            return {
                "name": name,
                "version": expected_version,
                "status": "error",
                "error": str(exc),
                "chunk_count": 0,
            }

        # Ingestion succeeded — safe to replace the previous version's chunks.
        existing_count_before = self.vector_store.count_chunks(framework_filter=[name])
        if existing_count_before > 0:
            self.vector_store.delete_framework_chunks(name)
            logger.info("framework_reindexing", name=name, previous_chunks=existing_count_before)

        try:
            added = self.vector_store.add_chunks(chunks)
            logger.info("framework_indexed", name=name, chunks=added, roles=fw_config.get("roles"))
            return {
                "name": name,
                "version": expected_version,
                "status": "synced",
                "checksum": current_hash,
                "chunk_count": added,
            }
        except Exception as exc:
            logger.error("framework_indexing_failed", name=name, error=str(exc))
            return {
                "name": name,
                "version": expected_version,
                "status": "error",
                "error": str(exc),
                "chunk_count": 0,
            }

    def download_pdf(self, name: str, url: str, target_path: Path) -> Path:
        logger.info("downloading_framework_pdf", name=name, url=url)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "application/pdf,text/html,application/xhtml+xml,*/*;q=0.8",
        }
        response = httpx.get(url, headers=headers, follow_redirects=True, timeout=120.0)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        is_pdf = content_type.startswith("application/pdf") or response.content[:5] == b"%PDF-"
        if not is_pdf:
            raise RuntimeError(
                f"Downloaded content is not a PDF (content-type={content_type}, "
                f"{len(response.content)} bytes). The publisher may block automated downloads."
            )
        target_path.write_bytes(response.content)
        logger.info("pdf_downloaded", name=name, path=str(target_path), size=len(response.content))
        return target_path

    def get_framework_status(self) -> list[dict[str, Any]]:
        frameworks_config = load_frameworks_config()
        results: list[dict[str, Any]] = []
        for fw in frameworks_config:
            name = fw["name"]
            local_path = RAW_POLICIES_DIR / f"{name.replace(' ', '_').replace('/', '_')}.pdf"
            indexed_chunks = self.vector_store.count_chunks(framework_filter=[name])
            results.append({
                "name": name,
                "version": fw.get("version", ""),
                "website": fw.get("website", ""),
                "is_indexed": indexed_chunks > 0,
                "chunk_count": indexed_chunks,
                "local_file_exists": local_path.exists(),
            })
        return results
