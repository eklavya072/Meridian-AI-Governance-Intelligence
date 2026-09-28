"""Re-reading a document must not strand the citations of earlier runs.

Stored analyses cite chunks by id. A re-read under newer ingestion rules mints
new ids wherever the text changed, and the old chunks used to be deleted, so
every earlier run of that country cited chunks that no longer existed. Chunks a
stored run cites are now retired out of the workspace instead: invisible to
every workspace query, still resolvable by id.
"""

import pytest

from src.ingestion import Chunk
from src.tasks import cited_chunk_ids


class _FlatEmbedder:
    dimension = 2

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


@pytest.fixture
def store(tmp_path):
    from src.vectorstore import VectorStore

    return VectorStore(persist_dir=str(tmp_path / "chroma"), embedding_service=_FlatEmbedder())


def _chunk(cid, text, ws="w1", doc="Act.pdf"):
    return Chunk(
        chunk_id=cid,
        text=text,
        metadata={"workspace_id": ws, "document_name": doc},
        workspace_id=ws,
    )


def test_cited_chunks_are_retired_and_the_rest_deleted(store):
    store.add_chunks([_chunk("old-cited", "a"), _chunk("old-free", "b"), _chunk("same", "c")])

    deleted, retired = store.retire_workspace_document(
        "w1", "Act.pdf", keep_ids={"old-cited", "same"}, replacing_ids={"same", "new"}
    )

    assert (deleted, retired) == (2, 1)
    # Still resolvable by id — that is what stored citations do.
    assert store.get_chunk("old-cited") is not None
    assert store.get_chunk("old-free") is None
    # ...but no longer part of the workspace.
    in_ws = store.collection.get(where={"workspace_id": "w1"})["ids"]
    assert "old-cited" not in in_ws


def test_a_replaced_id_is_deleted_so_the_new_copy_can_land(store):
    """Chroma ignores an add for an existing id; a retired copy would win."""
    store.add_chunks([_chunk("same", "c")])
    store.retire_workspace_document("w1", "Act.pdf", keep_ids={"same"}, replacing_ids={"same"})
    store.add_chunks([_chunk("same", "c")])

    assert store.collection.get(where={"workspace_id": "w1"})["ids"] == ["same"]


def test_citations_are_found_wherever_the_stored_json_puts_them():
    gaps = [
        {
            "evidence": [{"chunk_id": "e1"}],
            "module_1": {"document_evidence": [{"chunk_id": "d1"}]},
            "module_3": {"citations": [{"chunk_id": "r1"}]},
            "module_4": {"incident_matches": [{"citation": {"chunk_id": "i1"}}]},
        }
    ]
    assert cited_chunk_ids([gaps]) == {"e1", "d1", "r1", "i1"}


def test_framework_only_retrieval_never_reaches_a_workspace_document(store):
    store.add_chunks(
        [
            Chunk(chunk_id="fw", text="framework text", metadata={"framework": "OECD"}),
            _chunk("private", "a visitor's upload", ws="someone-else"),
        ]
    )
    hits = {r["chunk_id"] for r in store.retrieve("text", top_k=5, frameworks_only=True)}
    assert hits == {"fw"}
