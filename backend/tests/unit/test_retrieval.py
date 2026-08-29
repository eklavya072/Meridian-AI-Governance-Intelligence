import pytest

from src.retrieval import CrossEncoderReranker, RetrievalPipeline


def test_reranker_initialization():
    reranker = CrossEncoderReranker("BAAI/bge-reranker-v2-m3")
    assert reranker._model_name == "BAAI/bge-reranker-v2-m3"
    assert reranker._model is None
    assert not reranker._load_attempted


def test_reranker_unavailable_if_not_loaded():
    reranker = CrossEncoderReranker("nonexistent-model")
    assert not reranker.is_available or reranker._model is None


def test_reranker_empty_candidates():
    reranker = CrossEncoderReranker()
    result = reranker.rerank("test query", [])
    assert result == []


def test_rrf_score():
    from src.utils import rrf_score

    assert rrf_score(0) > rrf_score(1)
    assert rrf_score(0, 60) == 1.0 / 60.0
    assert rrf_score(1, 60) == 1.0 / 61.0


def test_reciprocal_rank_fusion():
    from src.utils import reciprocal_rank_fusion

    list_a = [("c1", 0.8), ("c2", 0.7)]
    list_b = [("c2", 0.9), ("c1", 0.6)]

    fused = reciprocal_rank_fusion([list_a, list_b])
    assert fused[0][0] in ("c1", "c2")
    assert len(fused) == 2


def test_reciprocal_rank_fusion_empty():
    from src.utils import reciprocal_rank_fusion

    assert reciprocal_rank_fusion([]) == []


def test_batch_fetch_chunk_metadata_empty():
    from src.utils import batch_fetch_chunk_metadata

    result = batch_fetch_chunk_metadata(None, [])
    assert result == {}


def test_l2_normalize():
    from src.utils import l2_normalize

    vec = [3.0, 4.0]
    normalized = l2_normalize(vec)
    import math

    assert abs(math.sqrt(sum(v * v for v in normalized)) - 1.0) < 1e-6

    zero_vec = [0.0, 0.0]
    assert l2_normalize(zero_vec) == zero_vec


def test_cosine_similarity():
    from src.utils import cosine_similarity

    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(a, b) == 0.0

    assert abs(cosine_similarity([1.0, 1.0], [1.0, 1.0]) - 1.0) < 1e-6

    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_keyword_overlap():
    from src.utils import compute_keyword_overlap

    a = "transparency and accountability in AI systems"
    b = "transparency requires accountability in AI governance"
    overlap = compute_keyword_overlap(a, b)
    assert 0 < overlap <= 1.0

    assert compute_keyword_overlap("a b c", "x y z") == 0.0
    assert compute_keyword_overlap("", "") == 0.0


def test_search_vectorstore_empty():
    retrieval = RetrievalPipeline.__new__(RetrievalPipeline)
    retrieval.vectorstore = None
    retrieval._reranker = None
    from unittest.mock import MagicMock

    retrieval.vectorstore = MagicMock()
    retrieval.vectorstore.search.return_value = []
    result = retrieval._search_vectorstore("test", top_k=5)
    assert result == []


class _FakePoolCollection:
    def __init__(self, chunks):
        self._chunks = chunks

    def query(self, query_embeddings=None, n_results=10, where=None, include=None):
        ids = [c["chunk_id"] for c in self._chunks]
        distances = [[1.0 - c.get("score", 0.5) for c in self._chunks]]
        return {"ids": [ids], "distances": distances}

    def get(self, ids=None, include=None, limit=None, offset=None):
        out_ids, out_docs, out_mds = [], [], []
        for c in self._chunks:
            if ids is None or c["chunk_id"] in ids:
                out_ids.append(c["chunk_id"])
                out_docs.append(c["text"])
                out_mds.append(c["metadata"])
        return {"ids": out_ids, "documents": out_docs, "metadatas": out_mds}


class _FakePoolStore:
    def __init__(self, chunks):
        self._chunks = chunks
        self.collection = _FakePoolCollection(chunks)

    def embed_query(self, text):
        return [0.0, 1.0]

    def get_chunk(self, chunk_id):
        for c in self._chunks:
            if c["chunk_id"] == chunk_id:
                return c
        return None


LONG_SAFETY_PASSAGE = (
    "The Authority shall publish an annual report on the safety and "
    "reliability of high-impact AI systems, including incident records, "
    "risk assessments, and compliance with the national certification "
    "scheme, so that the public can independently verify that operators "
    "meet their obligations under this Act and that oversight remains "
    "effective and transparent over time."
)


def test_document_evidence_pool_filters_and_dedups():
    """The comprehensive-evidence pool returns dimension-relevant document
    chunks while dropping preamble fragments, low-information glossary
    fragments, and text duplicates — the ladder must never see boilerplate."""
    chunks = [
        {
            "chunk_id": "a1",
            "text": LONG_SAFETY_PASSAGE,
            "metadata": {"page_number": 5, "section": "Oversight"},
            "score": 0.7,
        },
        # Text duplicate of a1 (recursive split overlap) — must dedup.
        {
            "chunk_id": "a1dup",
            "text": LONG_SAFETY_PASSAGE,
            "metadata": {"page_number": 6, "section": "Oversight"},
            "score": 0.6,
        },
        # Preamble: cover page fragment — must be dropped.
        {
            "chunk_id": "toc",
            "text": "Table of Contents 1 2 3",
            "metadata": {"page_number": 1, "section": "Front"},
            "score": 0.9,
        },
        # Low-information glossary fragment — must be dropped.
        {
            "chunk_id": "frag",
            "text": "Explainability15",
            "metadata": {"page_number": 12, "section": "Glossary"},
            "score": 0.8,
        },
        {
            "chunk_id": "a2",
            "text": (
                "Operators must report serious incidents to the regulator "
                "without delay, including near-misses and unexpected system "
                "behaviour, so that emerging risks in high-impact AI "
                "deployments are logged, investigated, and remediated as "
                "required by the incident notification obligations of this Act."
            ),
            "metadata": {"page_number": 7, "section": "Incidents"},
            "score": 0.5,
        },
    ]
    pipe = RetrievalPipeline.__new__(RetrievalPipeline)
    pipe.vectorstore = _FakePoolStore(chunks)
    pipe._reranker = None

    pool = pipe.retrieve_document_evidence_pool(
        "Safety",
        "ws-1",
        candidates=10,
        max_chunks=10,
    )
    ids = [c["chunk_id"] for c in pool]
    assert "a1" in ids
    assert "a1dup" not in ids
    assert "toc" not in ids
    assert "frag" not in ids
    assert "a2" in ids


def test_document_evidence_pool_empty_without_workspace():
    pipe = RetrievalPipeline.__new__(RetrievalPipeline)
    pipe.vectorstore = _FakePoolStore([])
    pipe._reranker = None
    assert pipe.retrieve_document_evidence_pool("Safety", None) == []
    assert pipe.retrieve_document_evidence_pool("Safety", "") == []


def test_is_preamble_chunk_uses_metadata_page_number():
    """Regression: page_number lives in metadata (vectorstore.retrieve and
    _retrieve_doc_bucket_multi_query never set it at the top level). Reading
    only the top-level key made page default to 0 for EVERY doc chunk, which
    silently dropped every chunk under 400 chars as a 'cover page' — a
    systematic doc-bucket starvation bug."""
    retrieval = RetrievalPipeline.__new__(RetrievalPipeline)

    # A short but substantive chunk on a real page (p.85) must survive.
    short_real = {
        "text": "Privacy and AI" * 20,  # ~260 chars, under the 400 threshold
        "metadata": {"page_number": "85"},
    }
    assert retrieval._is_preamble_chunk(short_real) is False

    # A genuinely boilerplate chunk is dropped by the length/marker rules.
    no_page = {"text": "This page has been intentionally left blank"}
    assert retrieval._is_preamble_chunk(no_page) is True

    # A genuinely short cover-page chunk (p.0/1) must still be dropped.
    cover = {"text": "Cover title page" * 20, "metadata": {"page_number": "1"}}
    assert retrieval._is_preamble_chunk(cover) is True

    # Top-level page_number (if ever set) still works.
    top_level = {"text": "Privacy and AI" * 20, "page_number": 99}
    assert retrieval._is_preamble_chunk(top_level) is False


def test_retrieve_doc_bucket_multi_query_shapes_entries():
    """Regression: the multi-query RRF doc bucket must return entries in the
    shape downstream _to_entry / _is_preamble_chunk expect, and must fuse the
    dimension query + definition + aspects rather than a single string query."""
    from unittest.mock import MagicMock, patch

    retrieval = RetrievalPipeline.__new__(RetrievalPipeline)
    retrieval._reranker = None
    retrieval.vectorstore = MagicMock()

    # Mock embeddings: distinct query texts -> distinct fake vectors.
    def fake_embed(text: str) -> list[float]:
        return [float(len(text) % 7), float(len(text) % 11), 0.0]

    retrieval.vectorstore.embed_query = fake_embed

    # Real dimension profiles drive the query texts (Transparency: 1
    # definition + 5 aspects). No mock needed — get_or_build_profiles is a
    # plain instance method building from static definitions. Clear the
    # module cache first so the rebuild runs; the class-bound method works
    # on the __new__ instance without any instance-attribute override.
    from src.retrieval import DIMENSION_PROFILES

    DIMENSION_PROFILES.clear()
    profiles = retrieval.get_or_build_profiles()
    assert "Transparency" in profiles

    # Simulate a workspace collection with 6 document chunks.
    chunk_ids = [f"doc-{i}" for i in range(6)]
    chunk_texts = [f"policy passage number {i} about governance" for i in range(6)]
    chunk_meta = [
        {
            "workspace_id": "ws-1",
            "framework": "",
            "page_number": str(85 + i),
            "section": "Section X",
        }
        for i in range(6)
    ]

    seen_wheres: list[dict | None] = []

    def fake_query(query_embeddings=None, n_results=10, where=None, include=None):
        # Lock in the workspace-scoping behaviour: every query must be
        # filtered to the workspace document bucket.
        seen_wheres.append(where)
        # Deterministic pseudo-ranking so different queries yield different orders.
        emb = query_embeddings[0]
        order = sorted(
            range(len(chunk_ids)),
            key=lambda i: (emb[0] * (i % 3) + emb[1] * ((i + 1) % 3)) % 7,
        )[:n_results]
        return {
            "ids": [[chunk_ids[i] for i in order]],
            "distances": [[float(i) / 10.0 for i in order]],
        }

    retrieval.vectorstore.collection.query = fake_query

    # Patch batch_fetch_chunk_metadata to read from the same fake store.
    def fake_batch_fetch(vs, ids):
        return {
            i: {
                "text": chunk_texts[chunk_ids.index(i)],
                "page_number": chunk_meta[chunk_ids.index(i)]["page_number"],
                "section_title": chunk_meta[chunk_ids.index(i)]["section"],
                "source_framework": "",
            }
            for i in ids
        }

    with patch("src.retrieval.batch_fetch_chunk_metadata", fake_batch_fetch):
        result = retrieval._retrieve_doc_bucket_multi_query(
            dimension="Transparency",
            dim_query="Transparency",
            workspace_id="ws-1",
            candidates=6,
        )

    # Every sub-query must have been scoped to the workspace.
    assert seen_wheres, "no collection.query calls were made"
    assert all(w == {"workspace_id": {"$in": ["ws-1"]}} for w in seen_wheres)
    assert len(result) > 0
    for entry in result:
        assert entry["chunk_id"].startswith("doc-")
        assert entry["text"]
        assert entry["metadata"]["page_number"]
        assert entry["metadata"]["section"] == "Section X"
        assert entry["metadata"]["framework"] == ""
        # similarity_score must be a real 0-1 value, not None/0 deflation.
        assert 0.0 <= (entry["similarity_score"] or 0.0) <= 1.0


def _incident(doc, text, cid=None):
    return {
        "chunk_id": cid or f"{doc}-{abs(hash(text)) % 10000}",
        "text": text,
        "metadata": {"document_name": doc, "roles": "module_4_incident"},
    }


# Wording that _chunk_matches_dimension accepts for Privacy, and wording it
# rejects — the tests below depend on the real gate, not a stub, so a change
# to the dimension vocabulary surfaces here instead of silently in production.
_PRIVACY = "The agency unlawfully processed personal data and breached data protection law."
_OFFTOPIC = "The turbine generated additional megawatt hours during the reporting period."


def test_incident_pool_drops_chunks_the_grounding_gate_would_reject():
    from src.deterministic import _chunk_matches_dimension

    assert _chunk_matches_dimension(_PRIVACY, "Privacy")
    assert not _chunk_matches_dimension(_OFFTOPIC, "Privacy")

    candidates = [
        _incident("Off", _OFFTOPIC),
        _incident("CaseA", _PRIVACY),
    ]
    picked = RetrievalPipeline._select_incident_pool(candidates, "Privacy", limit=1)
    assert [c["metadata"]["document_name"] for c in picked] == ["CaseA"]


def test_incident_pool_caps_slots_per_document():
    candidates = [_incident("CaseA", f"{_PRIVACY} Paragraph {i}.") for i in range(5)]
    candidates += [_incident("CaseB", f"{_PRIVACY} Separate matter.")]
    picked = RetrievalPipeline._select_incident_pool(
        candidates, "Privacy", limit=3, max_per_document=2
    )
    names = [c["metadata"]["document_name"] for c in picked]
    assert names.count("CaseA") == 2
    assert "CaseB" in names


def test_incident_pool_backfills_rather_than_returning_short():
    # Only one grounded chunk exists, but the caller asked for three. The
    # ungrounded remainder fills the gap (gap_analyzer re-checks and drops
    # them) so the prompt does not collapse to a single chunk.
    candidates = [
        _incident("CaseA", _PRIVACY),
        _incident("Off", _OFFTOPIC + " One."),
        _incident("Off", _OFFTOPIC + " Two."),
    ]
    picked = RetrievalPipeline._select_incident_pool(candidates, "Privacy", limit=3)
    assert len(picked) == 3
    assert picked[0]["metadata"]["document_name"] == "CaseA"


def test_incident_pool_overflow_outranks_ungrounded():
    candidates = [_incident("CaseA", f"{_PRIVACY} Para {i}.") for i in range(3)]
    candidates.append(_incident("Off", _OFFTOPIC))
    picked = RetrievalPipeline._select_incident_pool(
        candidates, "Privacy", limit=3, max_per_document=2
    )
    assert [c["metadata"]["document_name"] for c in picked] == ["CaseA"] * 3


def test_incident_pool_does_not_share_a_cap_bucket_across_unnamed_chunks():
    # Three chunks with no document_name are three different sources as far as
    # the cap is concerned; bucketing them together would cap them at 2.
    candidates = []
    for i in range(3):
        c = _incident("", f"{_PRIVACY} Item {i}.", cid=f"loose-{i}")
        c["metadata"]["document_name"] = ""
        candidates.append(c)
    picked = RetrievalPipeline._select_incident_pool(
        candidates, "Privacy", limit=3, max_per_document=2
    )
    assert len(picked) == 3


def test_incident_pool_handles_no_candidates():
    assert RetrievalPipeline._select_incident_pool([], "Privacy", limit=4) == []
