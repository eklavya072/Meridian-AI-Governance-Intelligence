from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import chromadb
import structlog
from chromadb.api.types import Documents, EmbeddingFunction
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from src.ingestion import Chunk

logger = structlog.get_logger()

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
COLLECTION_NAME = "policy_chunks"
TOP_K = 10

HYBRID_RETRIEVAL = os.getenv("HYBRID_RETRIEVAL", "true").lower() == "true"
HYBRID_ALPHA = float(os.getenv("HYBRID_ALPHA", "0.7"))

# Role filtering happens in Python (see retrieve()): we pull a wider candidate
# set than the caller's top_k, then filter by role membership on the
# comma-joined roles metadata. This is robust to multi-role chunks (a chunk
# tagged "module_2_practical,module_3_implementation" matches BOTH single-role
# queries), which a ChromaDB equality where-clause can never express.
ROLE_CANDIDATE_MULTIPLIER = int(os.getenv("ROLE_CANDIDATE_MULTIPLIER", "5"))


class NullEmbeddingFunction(EmbeddingFunction):
    def __call__(self, input: Documents) -> list:
        return [[0.0] * 384 for _ in range(len(input))]


# One encode at a time, process-wide. On Apple silicon the model runs on the
# GPU (MPS), which is not safe to drive from several threads at once: three
# dimension workers embedding together took the whole API down with a
# segfault (exit 139), leaving the run stuck in PROCESSING. An encode takes
# milliseconds, so queueing them costs nothing, and the vectors are the same.
_ENCODE_LOCK = threading.Lock()


class EmbeddingService:
    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME):
        self.model = SentenceTransformer(model_name)
        get_dim = (
            getattr(self.model, "get_embedding_dimension", None)
            or self.model.get_sentence_embedding_dimension
        )
        self.dimension = get_dim()
        logger.info("embedding_model_loaded", model=model_name, dimension=self.dimension)

    def embed(self, texts: list[str]) -> list[list[float]]:
        BATCH = 64
        all_embs = []
        failed = 0
        for i in range(0, len(texts), BATCH):
            batch = texts[i : i + BATCH]
            try:
                with _ENCODE_LOCK:
                    embs = self.model.encode(
                        batch, normalize_embeddings=True, batch_size=32, show_progress_bar=False
                    )
                all_embs.extend(embs.tolist())
            except Exception as exc:
                failed += len(batch)
                logger.error(
                    "embedding_batch_failed", batch_start=i, batch_size=len(batch), error=str(exc)
                )
                raise

        logger.info(
            "stage_4_embedding_complete",
            total_texts=len(texts),
            embeddings_created=len(all_embs),
            failed_texts=failed,
            dimension=self.dimension,
            batches=((len(texts) - 1) // BATCH) + 1,
        )
        return all_embs

    def embed_query(self, text: str) -> list[float]:
        with _ENCODE_LOCK:
            return self.model.encode(text, normalize_embeddings=True).tolist()


def _build_client(persist_dir: Path):
    """An embedded client, or an HTTP one when CHROMA_HOST is set.

    Embedded Chroma writes to a local directory, so two API processes pointed
    at the same path corrupt each other's HNSW segment — which is why this
    service could only ever run one instance. Setting CHROMA_HOST moves the
    store out of the process and behind a network boundary, and from there the
    API is stateless with respect to vectors and can be replicated.

    The default stays embedded: a single-container deployment should not have
    to run a second service, and every existing data directory keeps working.
    """
    host = os.getenv("CHROMA_HOST", "").strip()
    if not host:
        persist_dir.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(
            path=str(persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
    port = int(os.getenv("CHROMA_PORT", "8000"))
    ssl = os.getenv("CHROMA_SSL", "false").lower() == "true"
    logger.info("vector_store_remote", host=host, port=port, ssl=ssl)
    return chromadb.HttpClient(
        host=host,
        port=port,
        ssl=ssl,
        settings=Settings(anonymized_telemetry=False),
    )


def _open_collection(client):
    try:
        return client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
            embedding_function=NullEmbeddingFunction(),
        )
    except ValueError as e:
        if "embedding function already exists" in str(e):
            return client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        raise


def open_collection(persist_dir: str | Path = CHROMA_PERSIST_DIR):
    """The chunk collection alone, without loading the embedding model.

    For readers that only page stored text and metadata. Building a full
    VectorStore for them loaded a second copy of the model into the process.
    """
    return _open_collection(_build_client(Path(persist_dir)))


def iter_library_chunks(collection, page_size: int = 5000):
    """Every reference-library chunk as (text, metadata), paged, with no cap.

    Library chunks are the ones with an empty workspace_id; a country
    document, live or retired, is never part of the reference corpus.
    """
    offset = 0
    while True:
        rows = collection.get(
            where={"workspace_id": ""},
            include=["documents", "metadatas"],
            limit=page_size,
            offset=offset,
        )
        metadatas = rows.get("metadatas") or []
        if not metadatas:
            return
        yield from zip(rows.get("documents") or [""] * len(metadatas), metadatas, strict=True)
        offset += len(metadatas)


class VectorStore:
    def __init__(
        self,
        persist_dir: str = CHROMA_PERSIST_DIR,
        embedding_service: EmbeddingService | None = None,
    ):
        self.persist_dir = Path(persist_dir)
        self.embedding_service = embedding_service or EmbeddingService()
        self.client = _build_client(self.persist_dir)
        self.collection = _open_collection(self.client)
        logger.info(
            "vector_store_initialized",
            backend="remote" if os.getenv("CHROMA_HOST", "").strip() else "embedded",
            persist_dir=str(self.persist_dir),
        )

    def stored_document_chunks(
        self, workspace_id: str, document_name: str, ingest_key: str
    ) -> list[Chunk]:
        """A workspace document's chunks, if they were indexed from this exact file.

        Empty unless every chunk the ingestion produced is present under the
        same key, so a run interrupted halfway through indexing is read again
        rather than reused short.
        """
        try:
            raw = self.collection.get(
                where={
                    "$and": [
                        {"workspace_id": workspace_id},
                        {"document_name": document_name},
                        {"ingest_key": ingest_key},
                    ]
                },
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            logger.warning("stored_document_lookup_failed", document=document_name, error=str(exc))
            return []
        ids, texts, metas = (
            raw.get("ids") or [],
            raw.get("documents") or [],
            raw.get("metadatas") or [],
        )
        expected = int((metas[0] or {}).get("ingest_total") or 0) if metas else 0
        if not ids or len(ids) != expected:
            return []
        out = []
        for cid, text, md in zip(ids, texts, metas):
            md = md or {}
            page = str(md.get("page_number") or "")
            out.append(
                Chunk(
                    chunk_id=cid,
                    text=text or "",
                    metadata=dict(md),
                    page_number=int(page) if page.isdigit() else None,
                    section_title=md.get("section") or None,
                    workspace_id=workspace_id,
                )
            )
        return out

    def add_chunks(self, chunks: list[Chunk]) -> int:
        if not chunks:
            logger.warning("stage_5_vectorstore_no_chunks_to_index")
            return 0

        doc_ids = set()
        source_files = set()
        frameworks = set()
        for c in chunks:
            did = c.metadata.get("doc_id")
            if did:
                doc_ids.add(str(did))
            sf = c.metadata.get("source_file")
            if sf:
                source_files.add(str(sf))
            fw = c.framework_name or c.metadata.get("framework")
            if fw:
                frameworks.add(str(fw))

        ids = [c.chunk_id for c in chunks]
        texts = [c.text for c in chunks]
        metadatas = [
            {
                "doc_id": str(c.metadata.get("doc_id") or ""),
                "source_file": str(c.metadata.get("source_file") or ""),
                "document_name": str(c.metadata.get("document_name") or ""),
                "framework": str(c.framework_name or c.metadata.get("framework") or ""),
                "section": str(c.section_title or ""),
                "page_number": str(c.page_number) if c.page_number is not None else "",
                "chunk_id": str(c.chunk_id),
                "workspace_id": str(c.metadata.get("workspace_id") or c.workspace_id or ""),
                "roles": str(c.metadata.get("roles") or ""),
                "source_type": str(c.metadata.get("source_type") or "framework"),
                "ingest_key": str(c.metadata.get("ingest_key") or ""),
                "ingest_total": int(c.metadata.get("ingest_total") or 0),
            }
            for c in chunks
        ]

        embeddings = self.embedding_service.embed(texts)
        BATCH_SIZE = 200
        for i in range(0, len(ids), BATCH_SIZE):
            end = i + BATCH_SIZE
            self.collection.add(
                ids=ids[i:end],
                documents=texts[i:end],
                embeddings=embeddings[i:end],
                metadatas=metadatas[i:end],
            )
            logger.info(
                "stage_5_vectorstore_batch_indexed",
                batch_num=(i // BATCH_SIZE) + 1,
                batch_size=end - i,
                collection_name=COLLECTION_NAME,
            )

        logger.info(
            "stage_5_vectorstore_indexing_complete",
            total_chunks=len(chunks),
            unique_doc_ids=list(doc_ids),
            source_files=list(source_files),
            frameworks=list(frameworks),
            collection_name=COLLECTION_NAME,
            batches=((len(chunks) - 1) // BATCH_SIZE) + 1,
        )
        return len(chunks)

    def get_workspace_documents(self, workspace_id: str) -> list[str]:
        """Distinct clean document names ingested into one workspace.

        Supports multi-document analysis (e.g. Singapore NAIS + Model AI
        Governance Framework): every chunk carries a `document_name` metadata
        value (set at ingestion), so the set of evaluated inputs is derived
        from the store itself rather than a single workspace column.
        """
        try:
            data = self.collection.get(
                where={"workspace_id": workspace_id},
                include=["metadatas"],
            )
        except Exception:
            return []
        names: set[str] = set()
        for m in data.get("metadatas") or []:
            name = (m or {}).get("document_name") or ""
            if name:
                names.add(name)
        return sorted(names)

    @staticmethod
    def _matches_role(metadata: dict[str, Any], role_filter: list[str]) -> bool:
        """Membership check on the comma-joined roles metadata string.

        A chunk tagged with multiple roles ("module_2_practical,"
        "module_3_implementation") matches a single-role query for EITHER role.
        Missing/empty roles metadata matches nothing.
        """
        stored = [r.strip() for r in str(metadata.get("roles") or "").split(",") if r.strip()]
        return any(r in stored for r in role_filter)

    def _query_rows(
        self,
        results: dict[str, Any],
        query_embedding: list[float],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not results.get("ids") or not results["ids"][0]:
            return rows
        for i in range(len(results["ids"][0])):
            rows.append(
                {
                    "chunk_id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    # Cosine distance ranges [0, 2] in ChromaDB's cosine space;
                    # 1.0 - d goes negative for d > 1 and is NOT a valid 0-1
                    # similarity. 1.0 - d/2 is the correct normalization.
                    "similarity_score": max(0.0, float(1.0 - results["distances"][0][i] / 2.0))
                    if results.get("distances")
                    else None,
                    "embedding": query_embedding,
                }
            )
        return rows

    def retrieve(
        self,
        query: str,
        top_k: int = TOP_K,
        framework_filter: list[str] | None = None,
        workspace_filter: list[str] | None = None,
        role_filter: list[str] | None = None,
        frameworks_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Dense retrieval with optional scope filters.

        `frameworks_only` restricts the search to the reference library (chunks
        with no workspace). With no scope at all the search also reaches every
        workspace's uploaded documents, so on a shared deployment one visitor's
        PDF could be quoted in another visitor's general answer.
        """
        query_embedding = self.embedding_service.embed_query(query)

        where_parts: list[dict[str, Any]] = []
        if framework_filter:
            where_parts.append({"framework": {"$in": framework_filter}})
        if workspace_filter:
            where_parts.append({"workspace_id": {"$in": workspace_filter}})
        elif frameworks_only:
            where_parts.append({"workspace_id": ""})

        where: dict[str, Any] | None = None
        if len(where_parts) == 1:
            where = where_parts[0]
        elif len(where_parts) > 1:
            where = {"$and": where_parts}

        role_filter_clean = [r for r in (role_filter or []) if r]

        # ── Query 1 — broad recall (no role constraint) ──────────────
        # Pull a wider candidate set than top_k, then Python-filter by role
        # membership below. This is what makes comma-joined multi-role chunks
        # retrievable: an equality where-clause could never match
        # "module_2_practical,module_3_implementation".
        dense_k = top_k * 3 if HYBRID_RETRIEVAL else top_k
        if role_filter_clean:
            dense_k = max(dense_k, top_k * ROLE_CANDIDATE_MULTIPLIER)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=dense_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        retrieved = self._query_rows(results, query_embedding)

        # ── Query 2 — role-scoped guarantee (only when role-filtered) ─
        # Tiny role buckets (e.g. module_4_incident has just 2 chunks in the
        # whole collection) would rarely rank inside the broad recall query's
        # top-N, silently starving Module 4 matching. A role-scoped $in query
        # guarantees every chunk carrying the requested role is at least
        # considered; the same Python membership filter + rerank then apply
        # to the merged set. (Multi-role comma-joined values still rely on the
        # broad query + Python filter — $in only matches the per-role copies
        # the sync layer produces.)
        if role_filter_clean:
            role_where: dict[str, Any] = {"roles": {"$in": role_filter_clean}}
            if where:
                role_where = {"$and": [where, role_where]}
            try:
                role_results = self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=max(top_k * 2, len(role_filter_clean) * top_k * 2),
                    where=role_where,
                    include=["documents", "metadatas", "distances"],
                )
                retrieved.extend(self._query_rows(role_results, query_embedding))
            except Exception as exc:
                logger.warning("role_scoped_query_failed", error=str(exc))

        # Deduplicate across the merged queries, then apply the Python role
        # membership filter (handles comma-joined multi-role values that $in
        # cannot match).
        seen_ids: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for r in retrieved:
            cid = r.get("chunk_id")
            if cid and cid in seen_ids:
                continue
            if cid:
                seen_ids.add(cid)
            if role_filter_clean and not self._matches_role(
                r.get("metadata") or {}, role_filter_clean
            ):
                continue
            deduped.append(r)
        retrieved = deduped

        if HYBRID_RETRIEVAL and retrieved:
            retrieved = self._hybrid_rerank(query, retrieved, top_k)

        logger.info(
            "retrieval_complete",
            query=query[:80],
            framework_filter=framework_filter,
            workspace_filter=workspace_filter,
            role_filter=role_filter_clean,
            results=len(retrieved),
            method="hybrid" if HYBRID_RETRIEVAL else "dense_only",
        )

        for r in retrieved:
            r.pop("embedding", None)

        return retrieved

    def _hybrid_rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        query_terms = {
            w.lower() for w in query.split() if len(w) > 2 and w.lower() not in self._stopwords()
        }

        scored = []
        for item in candidates:
            dense_score = item.get("similarity_score", 0.0) or 0.0

            text = item.get("text", "").lower()
            if query_terms:
                matches = sum(1 for t in query_terms if t in text)
                bm25_like = matches / (len(text.split()) + 1)
            else:
                bm25_like = 0.0

            combined = HYBRID_ALPHA * dense_score + (1.0 - HYBRID_ALPHA) * bm25_like
            scored.append((combined, dense_score, item))

        scored.sort(key=lambda x: x[0], reverse=True)

        result = []
        for combined, dense, item in scored[:top_k]:
            item["similarity_score"] = round(combined, 4)
            item["dense_score"] = round(dense, 4)
            result.append(item)

        return result

    def _stopwords(self) -> set[str]:
        return {
            "the",
            "and",
            "for",
            "are",
            "was",
            "has",
            "had",
            "but",
            "not",
            "its",
            "can",
            "all",
            "any",
            "each",
            "their",
            "that",
            "this",
            "with",
            "from",
            "have",
            "been",
            "would",
            "could",
            "should",
            "about",
            "which",
            "than",
            "into",
            "over",
            "such",
            "also",
        }

    def count_chunks(self, framework_filter: list[str] | None = None) -> int:
        if framework_filter:
            where = {"framework": {"$in": framework_filter}}
            results = self.collection.get(where=where)
            return len(results["ids"])
        return self.collection.count()

    def chunk_exists(self, chunk_id: str) -> bool:
        results = self.collection.get(ids=[chunk_id])
        return len(results["ids"]) > 0

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        results = self.collection.get(ids=[chunk_id])
        if not results["ids"]:
            return None
        return {
            "chunk_id": results["ids"][0],
            "text": results["documents"][0],
            "metadata": results["metadatas"][0],
        }

    def get_all_frameworks(self) -> list[str]:
        frameworks: set[str] = set()
        offset = 0
        batch_size = 1000
        while True:
            results = self.collection.get(
                include=["metadatas"],
                limit=batch_size,
                offset=offset,
            )
            if not results["ids"]:
                break
            for m in results["metadatas"]:
                fw = m.get("framework", "")
                if fw:
                    frameworks.add(fw)
            offset += batch_size
        return sorted(frameworks)

    def embed_query(self, text: str) -> list[float]:
        return self.embedding_service.embed_query(text)

    def delete_workspace_document(self, workspace_id: str, document_name: str) -> int:
        """Remove a single document's chunks from one workspace.

        Makes re-uploading a document IDEMPOTENT. Chunk ids were once fresh
        uuid4s per ingestion, so `collection.add` never collided with a previous
        copy — it appended, and every re-run stacked another complete copy of
        the document into the workspace. The pipeline now uses
        `retire_workspace_document`, which keeps chunks stored analyses cite.

        The damage was severe and silent. A measured audit of the live store
        found the EU AI Act workspace holding 15,363 chunks of which only
        ~1,450 were unique — roughly 90% duplicates — with Kenya, Nigeria and
        Zambia between 50% and 80%. Retrieval then spent its candidate budget
        re-reading the same passages: a 300-candidate sweep over a 90%-duplicate
        corpus surfaces only ~30 distinct chunks, so the scorer saw a fraction
        of the document and under-counted provisions on exactly the largest,
        most binding instruments. Dimensions looked thin because retrieval was
        starved, not because the policy was silent.

        Scoped to (workspace_id, document_name) rather than the whole
        workspace so multi-document workspaces (e.g. India's DPDPA + AI
        Governance Guidelines) keep their other documents intact.
        """
        if not workspace_id or not document_name:
            return 0
        try:
            results = self.collection.get(
                where={
                    "$and": [
                        {"workspace_id": {"$eq": str(workspace_id)}},
                        {"document_name": {"$eq": str(document_name)}},
                    ]
                }
            )
        except Exception as exc:
            logger.warning(
                "workspace_document_delete_query_failed",
                workspace_id=workspace_id,
                document_name=document_name,
                error=str(exc),
            )
            return 0
        ids = results.get("ids") or []
        if ids:
            self.collection.delete(ids=ids)
        logger.info(
            "workspace_document_chunks_deleted",
            workspace_id=workspace_id,
            document_name=document_name,
            count=len(ids),
        )
        return len(ids)

    def retire_workspace_document(
        self,
        workspace_id: str,
        document_name: str,
        keep_ids: set[str],
        replacing_ids: set[str],
    ) -> tuple[int, int]:
        """Take a document's chunks out of its workspace before re-indexing it.

        `delete_workspace_document` removes them outright, which is right for
        retrieval (no stale duplicates) and wrong for the record: stored
        analyses cite chunks by id, and a re-read under newer ingestion rules
        mints new ids wherever the text changed, so every earlier run of that
        country was left citing chunks that no longer existed.

        So a chunk a stored analysis still cites is RETIRED instead — moved to a
        `retired:<workspace>` scope that no workspace query matches, while a
        lookup by id still resolves. Everything else is deleted. A chunk whose id
        the new ingestion re-creates is deleted too: the id encodes the text, so
        the replacement is the same passage, and Chroma silently ignores an add
        for an id that already exists.

        Returns (deleted, retired).
        """
        if not workspace_id or not document_name:
            return 0, 0
        try:
            found = self.collection.get(
                where={
                    "$and": [
                        {"workspace_id": {"$eq": str(workspace_id)}},
                        {"document_name": {"$eq": str(document_name)}},
                    ]
                },
                include=["metadatas"],
            )
        except Exception as exc:
            logger.warning("workspace_document_retire_query_failed", error=str(exc))
            return 0, 0
        ids = found.get("ids") or []
        metas = found.get("metadatas") or []
        retire = [
            (cid, md) for cid, md in zip(ids, metas) if cid in keep_ids and cid not in replacing_ids
        ]
        retire_ids = {cid for cid, _ in retire}
        doomed = [cid for cid in ids if cid not in retire_ids]
        if retire:
            self.collection.update(
                ids=[cid for cid, _ in retire],
                metadatas=[
                    {**(md or {}), "workspace_id": f"retired:{workspace_id}"} for _, md in retire
                ],
            )
        if doomed:
            self.collection.delete(ids=doomed)
        logger.info(
            "workspace_document_retired",
            workspace_id=workspace_id,
            document_name=document_name,
            deleted=len(doomed),
            retired=len(retire),
        )
        return len(doomed), len(retire)

    def delete_framework_chunks(self, framework_name: str) -> int:
        results = self.collection.get(where={"framework": framework_name})
        ids = results["ids"]
        if ids:
            self.collection.delete(ids=ids)
        logger.info("framework_chunks_deleted", framework=framework_name, count=len(ids))
        return len(ids)
