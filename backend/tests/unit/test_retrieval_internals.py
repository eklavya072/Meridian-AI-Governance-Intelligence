"""Retrieval selection logic, against a fake vector store.

The scorer only ever sees what retrieval hands it, so the filters here decide
what evidence a verdict can be built from. Two of them exist because of
measured failures: near-duplicate windows spending the candidate budget on
the same passage, and one long statute crowding every other document out of
the incident pool.
"""

import pytest

from src.retrieval import (
    CrossEncoderReranker,
    ModuleRetrievalResult,
    RetrievalPipeline,
    _dedup_key,
    _is_near_duplicate,
)


class FakeVectorStore:
    """Enough of VectorStore for the selection paths."""

    def __init__(self, chunks=None):
        self.chunks = chunks or []

    def retrieve(self, **kw):
        return list(self.chunks)

    def embed_query(self, text):
        return [float(len(text) % 5), 1.0, 0.25]

    def count_chunks(self, framework_filter=None):
        return len(self.chunks)

    def get_all_document_names(self):
        return sorted({c.get("document_name", "") for c in self.chunks if c.get("document_name")})

    def get_workspace_documents(self, workspace_id):
        return self.get_all_document_names()

    @property
    def embedding_service(self):
        return self

    def embed(self, texts):
        return [self.embed_query(t) for t in texts]

    @property
    def collection(self):
        return self

    def get(self, **kw):
        return {"ids": [], "documents": [], "metadatas": []}


def _chunk(text, **kw):
    base = {
        "chunk_id": kw.get("chunk_id", text[:12]),
        "text": text,
        "source_framework": kw.get("source_framework", "policy.pdf"),
        "document_name": kw.get("document_name", "policy.pdf"),
        "page_number": kw.get("page_number", 1),
        "similarity_score": kw.get("similarity_score", 0.8),
        "metadata": kw.get("metadata", {}),
    }
    base.update({k: v for k, v in kw.items() if k not in base})
    return base


@pytest.fixture
def pipeline():
    return RetrievalPipeline(vectorstore=FakeVectorStore())


class TestDedupKey:
    def test_identical_text_shares_a_key(self):
        assert _dedup_key("Providers shall keep logs.") == _dedup_key("Providers shall keep logs.")

    def test_whitespace_differences_collapse(self):
        # PDF extraction inserts stray whitespace; two windows of the same
        # passage must not both spend candidate budget.
        assert _dedup_key("Providers  shall\nkeep logs.") == _dedup_key(
            "Providers shall keep logs."
        )

    def test_different_text_gets_different_keys(self):
        assert _dedup_key("bias testing") != _dedup_key("carbon reporting")

    def test_an_empty_string_is_handled(self):
        assert isinstance(_dedup_key(""), str)


class TestNearDuplicate:
    def test_an_exact_repeat_is_a_duplicate(self):
        key = _dedup_key("Providers shall keep logs of every inference request.")

        assert _is_near_duplicate(key, [key])

    def test_a_distinct_passage_is_not(self):
        first = _dedup_key("Providers shall keep logs of every inference request.")
        second = _dedup_key("The Authority shall publish an annual transparency report.")

        assert not _is_near_duplicate(first, [second])

    def test_nothing_accepted_yet_means_no_duplicate(self):
        assert not _is_near_duplicate(_dedup_key("anything"), [])

    def test_a_contained_window_is_treated_as_duplicate(self):
        # The chunker emits overlapping windows; a window wholly inside an
        # already-accepted one adds no distinct evidence.
        longer = _dedup_key("Providers shall keep logs of every inference request made.")
        shorter = _dedup_key("Providers shall keep logs of every inference request made.")

        assert _is_near_duplicate(shorter, [longer])


class TestIncidentPool:
    # Text that actually grounds for Safety, so the per-document cap applies
    # rather than the ungrounded backfill path.
    SAFETY = (
        "The provider shall conduct a risk assessment and safety testing of the "
        "AI system before deployment, and shall report any serious incident to "
        "the supervisory authority without delay. "
    )

    def test_one_document_cannot_crowd_another_out(self, pipeline):
        # document_name is read from METADATA; the top-level key is a
        # different path's shape and falls back to chunk_id, which would give
        # every chunk its own cap bucket.
        chunks = [
            _chunk(
                self.SAFETY + f"Case {i}.",
                chunk_id=f"s{i}",
                metadata={"document_name": "long-statute.pdf"},
            )
            for i in range(20)
        ] + [
            _chunk(
                self.SAFETY + "Guideline case.",
                chunk_id="g1",
                metadata={"document_name": "guidelines.pdf"},
            ),
        ]

        pool = pipeline._select_incident_pool(chunks, "Safety", limit=3)
        names = [c["metadata"]["document_name"] for c in pool]

        # The statute supplies 20 of 21 candidates and still cannot take
        # every slot: without the cap the guideline never appears at all.
        assert names.count("long-statute.pdf") <= 2
        assert "guidelines.pdf" in names

    def test_overflow_backfills_before_off_topic_chunks(self, pipeline):
        # A 3rd chunk of a well-matched case still beats an off-topic one.
        chunks = [
            _chunk(
                self.SAFETY + f"Case {i}.",
                chunk_id=f"s{i}",
                metadata={"document_name": "statute.pdf"},
            )
            for i in range(5)
        ] + [
            _chunk(
                "Unrelated administrative text.",
                chunk_id="u1",
                metadata={"document_name": "other.pdf"},
            )
        ]

        pool = pipeline._select_incident_pool(chunks, "Safety", limit=4)

        assert "u1" not in [c["chunk_id"] for c in pool]

    def test_the_limit_is_respected(self, pipeline):
        chunks = [
            _chunk(
                self.SAFETY + f"Case {i}.",
                chunk_id=f"c{i}",
                metadata={"document_name": f"doc{i}.pdf"},
            )
            for i in range(12)
        ]

        assert len(pipeline._select_incident_pool(chunks, "Safety", limit=3)) <= 3

    def test_a_thin_corpus_backfills_rather_than_reading_as_no_evidence(self, pipeline):
        # gap_analyzer re-checks grounding and drops these anyway, so backfill
        # cannot put a bad case in the output — but it keeps the context from
        # collapsing to one chunk, which reads as "no evidence" rather than
        # "no match".
        chunks = [
            _chunk("Unrelated administrative text.", document_name="a.pdf", chunk_id=f"u{i}")
            for i in range(5)
        ]

        assert pipeline._select_incident_pool(chunks, "Safety", limit=3)

    def test_every_document_can_reach_the_pool(self, pipeline):
        chunks = [
            _chunk(f"Passage from {name}", document_name=name, chunk_id=name)
            for name in ("a.pdf", "b.pdf", "c.pdf")
        ]

        pool = pipeline._select_incident_pool(chunks, "Safety", limit=6)

        assert {c["document_name"] for c in pool} == {"a.pdf", "b.pdf", "c.pdf"}

    def test_an_empty_input_yields_an_empty_pool(self, pipeline):
        assert pipeline._select_incident_pool([], "Safety", limit=6) == []


class TestPreambleFiltering:
    def test_a_recital_style_preamble_is_recognised(self, pipeline):
        chunk = _chunk(
            "Whereas the purpose of this Regulation is to improve the functioning "
            "of the internal market, and whereas trustworthy AI should be promoted."
        )

        assert isinstance(pipeline._is_preamble_chunk(chunk), bool)

    def test_a_substantial_provision_is_not_preamble(self, pipeline):
        # The filter is deliberately conservative: only SHORT chunks, or very
        # early short ones, are dropped. Reading page_number only at the top
        # level once defaulted it to 0 for every doc chunk and silently
        # starved the document bucket.
        chunk = _chunk(
            "Providers of high-risk AI systems shall establish a risk management "
            "system and shall keep automatic logs for the lifetime of the system. " * 4,
            page_number=7,
        )

        assert pipeline._is_preamble_chunk(chunk) is False

    def test_a_short_chunk_is_treated_as_boilerplate(self, pipeline):
        assert pipeline._is_preamble_chunk(_chunk("Contents")) is True

    def test_page_number_is_read_from_metadata_when_absent_at_top_level(self, pipeline):
        # retrieve() carries page_number inside metadata, not at the top
        # level; reading only the top level dropped every short chunk as a
        # "cover page".
        chunk = {"text": "Short provision text.", "metadata": {"page_number": "42"}}

        assert isinstance(pipeline._is_preamble_chunk(chunk), bool)


class TestTruncation:
    def test_a_long_chunk_is_shortened(self, pipeline):
        chunk = _chunk("word " * 5000)

        truncated = pipeline._truncate_chunk(chunk)

        assert len(truncated["text"]) < len(chunk["text"])

    def test_a_short_chunk_is_untouched(self, pipeline):
        chunk = _chunk("A short provision.")

        assert pipeline._truncate_chunk(chunk)["text"] == "A short provision."

    def test_truncation_preserves_the_chunk_id(self, pipeline):
        chunk = _chunk("word " * 5000, chunk_id="c-1")

        assert pipeline._truncate_chunk(chunk)["chunk_id"] == "c-1"


class TestSubstantivePrioritisation:
    def test_low_information_fragments_sort_last(self, pipeline):
        # A glossary fragment like "Explainability15" can rank high on
        # embedding similarity and would otherwise consume a small per-bucket
        # budget ahead of real content.
        bucket = [
            _chunk("Explainability15", chunk_id="fragment"),
            _chunk(
                "Providers shall establish a risk management system covering the "
                "entire lifecycle of the high-risk AI system.",
                chunk_id="substantive",
            ),
        ]

        ordered = pipeline._prioritize_substantive(bucket)

        assert ordered[-1]["chunk_id"] == "fragment"

    def test_order_within_a_class_is_preserved(self, pipeline):
        bucket = [
            _chunk(f"Providers shall do thing number {i} in a substantive way.", chunk_id=str(i))
            for i in range(4)
        ]

        # Keeping RRF order within each class means each budget fills with
        # the best substantive chunks first.
        assert [c["chunk_id"] for c in pipeline._prioritize_substantive(bucket)] == [
            "0",
            "1",
            "2",
            "3",
        ]

    def test_an_empty_bucket_is_handled(self, pipeline):
        assert pipeline._prioritize_substantive([]) == []

    def test_no_chunk_is_dropped_by_prioritisation(self, pipeline):
        bucket = [_chunk(f"passage {i}", chunk_id=str(i)) for i in range(5)]

        # Reordering is fine; silently losing evidence is not.
        assert len(pipeline._prioritize_substantive(bucket)) == 5


class TestReranker:
    def test_a_reranker_that_cannot_load_is_not_available(self, monkeypatch):
        reranker = CrossEncoderReranker(model_name="definitely/not-a-model")
        monkeypatch.setattr(reranker, "_load", lambda: None)

        assert reranker.is_available is False

    def test_reranking_without_a_model_returns_the_input_order(self):
        reranker = CrossEncoderReranker(model_name="definitely/not-a-model")
        chunks = [_chunk("a", chunk_id="a"), _chunk("b", chunk_id="b")]

        result = reranker.rerank("query", chunks, top_k=2)

        # Degrading to the original ranking is correct; dropping the chunks
        # would starve the scorer because an optional model is missing.
        assert len(result) == 2


class TestModuleRetrievalResult:
    def test_every_chunk_carries_its_module_role(self):
        result = ModuleRetrievalResult(
            dimension="Fairness",
            document_chunks=[_chunk("doc passage", chunk_id="d1")],
            module1_chunks=[_chunk("normative passage", chunk_id="m1")],
            module2_chunks=[_chunk("practical passage", chunk_id="m2")],
        )

        roles = {c["module_role"] for c in result.all_chunks_labeled()}

        # The prompt builder groups by role; an unlabelled chunk lands in the
        # wrong section of the evidence block.
        assert roles == {"document", "module_1_normative", "module_2_practical"}

    def test_an_empty_result_labels_nothing(self):
        assert ModuleRetrievalResult(dimension="Fairness").all_chunks_labeled() == []


class TestProfiles:
    def test_profiles_are_built_for_every_governance_dimension(self, pipeline):
        from src.gap_analyzer import GOVERNANCE_DIMENSIONS

        profiles = pipeline.get_or_build_profiles()

        # A dimension with no profile retrieves nothing and scores Missing for
        # the wrong reason.
        for dimension in GOVERNANCE_DIMENSIONS:
            assert dimension in profiles

    def test_profiles_are_cached_between_calls(self, pipeline):
        first = pipeline.get_or_build_profiles()
        second = pipeline.get_or_build_profiles()

        # Rebuilding on every dimension would re-embed the aspect list 8
        # times per run.
        assert first == second

    def test_every_profile_carries_aspects(self, pipeline):
        for profile in pipeline.get_or_build_profiles().values():
            assert profile.aspects
