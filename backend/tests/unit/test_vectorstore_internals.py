"""Vector store scoring and filtering, without loading a model or an index.

The similarity normalisation here is load-bearing: ChromaDB's cosine
distance ranges [0, 2], so the obvious `1 - d` goes negative and produces a
"similarity" that is not a similarity. Every downstream threshold — retrieval
ranking, citation verification — reads this number.
"""

import pytest

from src.vectorstore import VectorStore


@pytest.fixture
def store():
    """A VectorStore with no model and no collection.

    Constructed without __init__ on purpose: the real one loads
    bge-small (~130MB) and opens a Chroma collection, neither of which the
    pure scoring paths need.
    """
    return VectorStore.__new__(VectorStore)


class TestRoleMatching:
    def test_a_single_role_matches_itself(self):
        assert VectorStore._matches_role({"roles": "module_1_normative"}, ["module_1_normative"])

    def test_a_multi_role_chunk_matches_either_role(self):
        # Chroma's roles filter is equality-only, so a framework with several
        # roles is stored as per-role copies; the membership check has to
        # handle the comma-joined form either way.
        metadata = {"roles": "module_2_practical,module_3_implementation"}

        assert VectorStore._matches_role(metadata, ["module_3_implementation"])

    def test_whitespace_around_roles_is_tolerated(self):
        metadata = {"roles": "module_2_practical, module_3_implementation"}

        assert VectorStore._matches_role(metadata, ["module_3_implementation"])

    def test_an_unrelated_role_does_not_match(self):
        assert not VectorStore._matches_role({"roles": "module_1_normative"}, ["module_4_incident"])

    def test_missing_roles_metadata_matches_nothing(self):
        assert not VectorStore._matches_role({}, ["module_1_normative"])

    def test_empty_roles_metadata_matches_nothing(self):
        assert not VectorStore._matches_role({"roles": ""}, ["module_1_normative"])

    def test_an_empty_filter_matches_nothing(self):
        assert not VectorStore._matches_role({"roles": "module_1_normative"}, [])


class TestSimilarityNormalisation:
    def _rows(self, store, distances):
        results = {
            "ids": [[f"c{i}" for i in range(len(distances))]],
            "documents": [[f"text {i}" for i in range(len(distances))]],
            "metadatas": [[{} for _ in distances]],
            "distances": [distances],
        }
        return store._query_rows(results, [0.1, 0.2])

    def test_a_perfect_match_scores_one(self, store):
        assert self._rows(store, [0.0])[0]["similarity_score"] == 1.0

    def test_an_orthogonal_match_scores_a_half(self, store):
        assert self._rows(store, [1.0])[0]["similarity_score"] == 0.5

    def test_the_opposite_direction_scores_zero_not_negative(self, store):
        # `1 - d` gives -1 here, which is not a similarity at all and would
        # sort below chunks that were never retrieved.
        assert self._rows(store, [2.0])[0]["similarity_score"] == 0.0

    def test_scores_stay_within_zero_and_one(self, store):
        rows = self._rows(store, [0.0, 0.5, 1.0, 1.5, 2.0])

        assert all(0.0 <= r["similarity_score"] <= 1.0 for r in rows)

    def test_scores_decrease_as_distance_grows(self, store):
        rows = self._rows(store, [0.0, 0.8, 1.6])
        scores = [r["similarity_score"] for r in rows]

        assert scores == sorted(scores, reverse=True)

    def test_missing_distances_yield_no_score_rather_than_zero(self, store):
        results = {
            "ids": [["c1"]],
            "documents": [["text"]],
            "metadatas": [[{}]],
        }

        # A missing score is "unknown"; zero would mean "certainly irrelevant".
        assert store._query_rows(results, [0.1])[0]["similarity_score"] is None

    def test_an_empty_result_yields_no_rows(self, store):
        assert store._query_rows({"ids": [[]]}, [0.1]) == []

    def test_a_result_with_no_ids_key_yields_no_rows(self, store):
        assert store._query_rows({}, [0.1]) == []

    def test_every_row_carries_its_chunk_id_and_text(self, store):
        rows = self._rows(store, [0.2, 0.4])

        assert [r["chunk_id"] for r in rows] == ["c0", "c1"]
        assert rows[0]["text"] == "text 0"


class TestHybridRerank:
    def test_a_lexically_matching_chunk_outranks_a_purely_dense_one(self, store):
        candidates = [
            {
                "chunk_id": "dense",
                "text": "unrelated administrative wording",
                "similarity_score": 0.62,
            },
            {"chunk_id": "lexical", "text": "bias testing bias testing", "similarity_score": 0.60},
        ]

        ranked = store._hybrid_rerank("bias testing", candidates, top_k=2)

        # The dense scores are almost identical; the lexical signal is what
        # separates them, which is the point of blending at all.
        assert ranked[0]["chunk_id"] == "lexical"

    def test_the_dense_score_is_preserved_alongside_the_blend(self, store):
        candidates = [{"chunk_id": "c", "text": "bias testing", "similarity_score": 0.7}]

        ranked = store._hybrid_rerank("bias testing", candidates, top_k=1)

        # Keeping the original lets a caller tell a lexical boost apart from
        # a genuinely close embedding.
        assert ranked[0]["dense_score"] == 0.7

    def test_top_k_bounds_the_result(self, store):
        candidates = [
            {"chunk_id": str(i), "text": f"text {i}", "similarity_score": 0.5} for i in range(10)
        ]

        assert len(store._hybrid_rerank("query", candidates, top_k=3)) == 3

    def test_stopwords_do_not_drive_the_lexical_score(self, store):
        candidates = [
            {
                "chunk_id": "stopwords",
                "text": "the and for are was the and",
                "similarity_score": 0.5,
            },
            {"chunk_id": "substantive", "text": "bias testing procedures", "similarity_score": 0.5},
        ]

        ranked = store._hybrid_rerank("the bias and testing", candidates, top_k=2)

        assert ranked[0]["chunk_id"] == "substantive"

    def test_an_empty_candidate_list_is_handled(self, store):
        assert store._hybrid_rerank("query", [], top_k=5) == []

    def test_a_query_of_only_stopwords_does_not_crash(self, store):
        candidates = [{"chunk_id": "c", "text": "some text", "similarity_score": 0.4}]

        assert store._hybrid_rerank("the and for", candidates, top_k=1)

    def test_a_missing_similarity_score_is_treated_as_zero(self, store):
        candidates = [{"chunk_id": "c", "text": "bias testing"}]

        # None would raise on the arithmetic; the chunk should simply rank low.
        assert store._hybrid_rerank("bias testing", candidates, top_k=1)


class TestStopwords:
    def test_common_words_are_stopwords(self, store):
        stopwords = store._stopwords()

        assert {"the", "and", "for"} <= stopwords

    def test_governance_terms_are_not_stopwords(self, store):
        stopwords = store._stopwords()

        # Dropping these would gut the lexical half of every dimension query.
        assert not {"bias", "transparency", "accountability"} & stopwords
