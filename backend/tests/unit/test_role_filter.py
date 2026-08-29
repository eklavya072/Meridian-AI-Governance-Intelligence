"""Tests for the four-fix audit round:

1. Role-filter equality bug (vectorstore._matches_role) — a comma-joined
   multi-role chunk must match a single-role query for EITHER role.
2. Module-bucket text dedup (retrieval.retrieve_module_chunks) — two
   text-identical overlapping chunks cannot both occupy module slots.
3. RPD counter persistence (provider_router) — survives a simulated restart.
4. Similarity convention (vectorstore.retrieve) — 1.0 - d/2 for cosine
   distance in [0, 2], never 1.0 - d (which goes negative for d > 1).
"""

import json

import pytest

from src.vectorstore import VectorStore

# ── Fix 1: role filter membership ────────────────────────────────────────


class TestRoleFilter:
    def test_single_role_matches(self):
        assert VectorStore._matches_role({"roles": "module_2_practical"}, ["module_2_practical"])
        assert not VectorStore._matches_role(
            {"roles": "module_1_normative"}, ["module_2_practical"]
        )

    def test_multi_role_comma_joined_matches_either(self):
        """Regression: a chunk tagged 'module_2_practical,module_3_implementation'
        must match a query for EITHER role — an equality where-clause could
        never express this."""
        md = {"roles": "module_2_practical,module_3_implementation"}
        assert VectorStore._matches_role(md, ["module_2_practical"])
        assert VectorStore._matches_role(md, ["module_3_implementation"])
        assert not VectorStore._matches_role(md, ["module_1_normative"])

    def test_missing_roles_matches_nothing(self):
        assert not VectorStore._matches_role({}, ["module_2_practical"])
        assert not VectorStore._matches_role({"roles": ""}, ["module_2_practical"])
        assert not VectorStore._matches_role({"roles": "?"}, ["module_2_practical"])

    def test_whitespace_tolerated(self):
        md = {"roles": " module_2_practical , module_3_implementation "}
        assert VectorStore._matches_role(md, ["module_2_practical"])


# ── Fix 2: module-bucket text dedup ──────────────────────────────────────


class TestModuleBucketDedup:
    def _make_pipeline(self, monkeypatch):
        from unittest.mock import MagicMock

        from src.retrieval import ModuleRetrievalResult, RetrievalPipeline

        retrieval = RetrievalPipeline.__new__(RetrievalPipeline)
        retrieval._reranker = None
        retrieval.vectorstore = MagicMock()

        # Two text-identical normative chunks (overlap-produced duplicates)
        # plus one distinct chunk.
        retrieval.vectorstore.retrieve.side_effect = [
            # module1 pull: [dupA, dupB, distinct]
            [
                {
                    "chunk_id": "n1",
                    "text": "identical body text for transparency regulation " * 3,
                    "metadata": {"framework": "OECD AI Principles", "roles": "module_1_normative"},
                    "similarity_score": 0.9,
                },
                {
                    "chunk_id": "n2",
                    "text": "identical body text for transparency regulation " * 3,
                    "metadata": {"framework": "OECD AI Principles", "roles": "module_1_normative"},
                    "similarity_score": 0.88,
                },
                {
                    "chunk_id": "n3",
                    "text": "a genuinely different passage about audit trails " * 3,
                    "metadata": {
                        "framework": "UNESCO Recommendation on the Ethics of AI",
                        "roles": "module_1_normative",
                    },
                    "similarity_score": 0.7,
                },
            ],
            # module2 pull
            [
                {
                    "chunk_id": "p1",
                    "text": "practical toolkit content " * 4,
                    "metadata": {
                        "framework": "CDEI Review into Bias in Algorithmic Decision-Making",
                        "roles": "module_2_practical",
                    },
                    "similarity_score": 0.8,
                }
            ],
        ]
        return retrieval

    def test_module1_bucket_deduplicates_identical_text(self, monkeypatch):
        from src.retrieval import RetrievalPipeline

        retrieval = self._make_pipeline(monkeypatch)
        result = retrieval.retrieve_module_chunks(
            dimension="Transparency",
            module1_top_k=2,
            module2_top_k=1,
            doc_top_k=2,
        )
        texts = [c["text"] for c in result.module1_chunks]
        # The two identical chunks collapse to one; the distinct one fills the
        # remaining budget slot.
        assert len(result.module1_chunks) == 2
        assert len(set(texts)) == 2

    def test_module_bucket_respects_budget_after_dedup(self, monkeypatch):
        from src.retrieval import RetrievalPipeline

        retrieval = self._make_pipeline(monkeypatch)
        result = retrieval.retrieve_module_chunks(
            dimension="Transparency",
            module1_top_k=1,
            module2_top_k=1,
            doc_top_k=2,
        )
        assert len(result.module1_chunks) <= 1


# ── Fix 3: RPD persistence ───────────────────────────────────────────────


class TestRpdPersistence:
    def test_roundtrip_survives_restart(self, tmp_path, monkeypatch):
        import src.provider_router as pr

        f = tmp_path / "rpd.json"
        monkeypatch.setattr(pr, "GEMINI_RPD_FILE", str(f))

        # Simulate a day's usage.
        pr._persist_daily_requests(42)
        # 'Restart': a fresh load must read the persisted count back.
        assert pr._load_daily_requests() == 42

    def test_stale_date_returns_zero(self, tmp_path, monkeypatch):
        import src.provider_router as pr

        f = tmp_path / "rpd.json"
        monkeypatch.setattr(pr, "GEMINI_RPD_FILE", str(f))
        f.write_text(json.dumps({"date": "2000-01-01", "count": 999}), encoding="utf-8")
        assert pr._load_daily_requests() == 0

    def test_corrupt_file_returns_zero(self, tmp_path, monkeypatch):
        import src.provider_router as pr

        f = tmp_path / "rpd.json"
        monkeypatch.setattr(pr, "GEMINI_RPD_FILE", str(f))
        f.write_text("not json {{{", encoding="utf-8")
        assert pr._load_daily_requests() == 0


# ── Fix 4: similarity convention ─────────────────────────────────────────


class TestSimilarityConvention:
    def test_cosine_distance_maps_to_01(self):
        """ChromaDB cosine space returns distances in [0, 2]; 1.0 - d/2 maps
        that to [0, 1]. 1.0 - d would go negative for any d > 1."""
        # distance 2.0 (maximally dissimilar) -> 0.0
        assert max(0.0, 1.0 - 2.0 / 2.0) == 0.0
        # distance 1.0 -> 0.5
        assert max(0.0, 1.0 - 1.0 / 2.0) == 0.5
        # distance 0.0 (identical) -> 1.0
        assert max(0.0, 1.0 - 0.0 / 2.0) == 1.0
        # the OLD formula goes negative here — exactly the bug being fixed:
        assert (1.0 - 1.5) < 0

    def test_vectorstore_uses_half_normalization(self, monkeypatch):
        # Disable the hybrid rerank (it recomputes similarity_score from the
        # dense + lexical blend); we are testing the DENSE conversion only.
        import src.vectorstore as vs_mod

        monkeypatch.setattr(vs_mod, "HYBRID_RETRIEVAL", False)

        from unittest.mock import MagicMock

        vs = VectorStore.__new__(VectorStore)
        vs.embedding_service = MagicMock()
        vs.embedding_service.embed_query.return_value = [0.1, 0.2]
        vs.collection = MagicMock()
        vs.collection.query.return_value = {
            "ids": [["c1"]],
            "documents": [["text"]],
            "metadatas": [[{"framework": "F"}]],
            "distances": [[1.5]],  # would be negative under 1.0 - d
        }
        result = vs.retrieve("q", top_k=1, role_filter=None)
        assert result[0]["similarity_score"] == pytest.approx(max(0.0, 1.0 - 1.5 / 2.0))
