"""Narrative citation checking — the layer that decides what a reader is
told was fabricated.

Three separate incidents in this codebase were the CHECKER being wrong rather
than the model: a closed citation vocabulary, a literal-string requirement
that only passed when a document cross-referenced itself, and a page bound
applied to framework chunks that never belonged to the uploaded document. A
false "fabricated" label is worse than a missing one, because it tells a
policy analyst that a real provision was invented.
"""

import pytest

from src.verify import (
    _citation_present,
    _compute_keyword_overlap,
    _enumerated_ordinals,
    classify_narrative_citations,
    detect_division_vocabulary,
    find_unverifiable_citations,
    verify_citation,
)


class TestDivisionVocabulary:
    def test_a_document_organised_into_parts_reports_part(self):
        text = "Part 1 General. Part 2 Scope. Part 3 Duties. Part 4 Enforcement."

        assert "Part" in detect_division_vocabulary([text])

    def test_articles_are_detected(self):
        text = " ".join(f"Article {i} text." for i in range(1, 12))

        assert detect_division_vocabulary([text])[0] == "Article"

    def test_ocr_split_words_are_still_detected(self):
        # The EU AI Act extracts as "Ar ticle" throughout; a strict pattern
        # reports its vocabulary as Paragraph/Section and misses the Articles
        # the regulation is actually built from.
        text = " ".join(f"Ar ticle {i} requires something." for i in range(1, 8))

        assert "Article" in detect_division_vocabulary([text])

    def test_the_most_common_form_ranks_first(self):
        text = " ".join(f"Section {i}." for i in range(1, 10)) + " Article 1."

        assert detect_division_vocabulary([text])[0] == "Section"

    def test_the_limit_bounds_how_many_are_returned(self):
        text = "Article 1. Section 2. Chapter 3. Annex 4. Part 5."

        assert len(detect_division_vocabulary([text], limit=2)) <= 2

    def test_no_text_yields_no_vocabulary(self):
        assert detect_division_vocabulary([]) == []

    def test_none_entries_are_skipped(self):
        assert detect_division_vocabulary([None, "Article 1. Article 2."])


class TestEnumeratedOrdinals:
    def test_bare_numbered_headings_are_collected(self):
        text = "4. Fairness and Equity\n6. Understandable by Design\n"

        assert {"4", "6"} <= _enumerated_ordinals(text)

    def test_a_statute_numbering_its_sections_is_collected(self):
        assert "38" in _enumerated_ordinals("38. (1) The provisions of this Act")

    def test_prose_decimals_are_not_treated_as_headings(self):
        # "costs 4. 5 million" is not a division heading.
        assert _enumerated_ordinals("the figure was 4.5 million") == frozenset()


class TestCitationPresence:
    def test_an_explicit_cross_reference_passes(self):
        corpus = "As set out in Article 12, providers shall keep logs."

        assert _citation_present("Article", "12", corpus)

    def test_a_bare_ordinal_passes_when_the_kind_is_named_somewhere(self):
        # The India Guidelines number their seven sutras as bare ordinals and
        # only ever say "Principle" in running prose.
        corpus = "The seven principles are set out below.\n4. Fairness and Equity\n"

        assert _citation_present("Principle", "4", corpus)

    def test_a_bare_ordinal_alone_is_not_enough(self):
        # Both halves are required, or any numbered list would clear any
        # citation.
        corpus = "1. Apples\n2. Oranges\n4. Pears\n"

        assert not _citation_present("Principle", "4", corpus)

    def test_an_ordinal_the_document_does_not_enumerate_fails(self):
        corpus = "The seven principles are listed.\n4. Fairness\n6. Clarity\n"

        # The Guidelines enumerate exactly 1-7, so Principle 8 is still caught.
        assert not _citation_present("Principle", "8", corpus)

    def test_an_empty_corpus_never_confirms_a_citation(self):
        assert not _citation_present("Article", "1", "")


class TestClassifyNarrativeCitations:
    DOC = "Article 12 requires logging. Article 13 requires transparency."

    def test_a_real_article_is_not_fabricated(self):
        result = classify_narrative_citations(
            ["Logging is required under Article 12."], self.DOC, self.DOC
        )

        assert not result["fabricated"]

    def test_an_invented_article_is_flagged(self):
        result = classify_narrative_citations(["See Article 99 for details."], self.DOC, self.DOC)

        # The number appears nowhere in the document: a reader who looks it
        # up finds nothing.
        assert any("99" in c for c in result["fabricated"])

    def test_a_real_number_absent_from_the_retrieved_passages_is_unsupported(self):
        # Real and correct, but written from memory rather than from what the
        # model was shown. Computed, and deliberately not rendered.
        result = classify_narrative_citations(
            ["See Article 13."], "Article 12 requires logging.", self.DOC
        )

        assert not result["fabricated"]
        assert any("13" in c for c in result["unsupported"])

    def test_documents_are_scored_separately_not_concatenated(self):
        # Concatenating a 44-section statute with a 7-principle guideline
        # would lend the guideline an ordinal it does not have.
        guidelines = "The seven principles.\n4. Fairness\n6. Clarity\n"
        statute = "\n".join(f"{i}. Section text" for i in range(1, 45))

        result = classify_narrative_citations(
            ["See Principle 40."], guidelines, [guidelines, statute]
        )

        assert result["fabricated"]

    def test_narrative_with_no_citation_is_clean(self):
        result = classify_narrative_citations(
            ["The document is broadly aspirational."], "text", "text"
        )

        assert not result["fabricated"]

    def test_both_classes_are_always_returned(self):
        result = classify_narrative_citations(["Article 1 applies."], "Article 1 applies.", "")

        assert "fabricated" in result and "unsupported" in result

    def test_empty_inputs_do_not_raise(self):
        assert classify_narrative_citations([], "", "")["fabricated"] == []


class TestUnverifiableCitations:
    def test_a_number_absent_from_the_corpus_is_unverifiable(self):
        found = find_unverifiable_citations(["See Recital 71."], "Article 12 requires logging.")

        assert "Recital 71" in found

    def test_a_number_present_in_the_corpus_is_verifiable(self):
        found = find_unverifiable_citations(["See Article 12."], "Article 12 requires logging.")

        assert found == []

    def test_the_same_number_is_reported_once(self):
        found = find_unverifiable_citations(["Recital 71 and again Recital 71."], "Article 12.")

        assert found.count("Recital 71") == 1

    def test_an_empty_corpus_reports_nothing_rather_than_everything(self):
        # With no source text there is nothing to check against, and flagging
        # every citation as invented would be worse than flagging none.
        assert find_unverifiable_citations(["Article 5 applies."], "") == []


class TestKeywordOverlap:
    def test_identical_text_overlaps_fully(self):
        assert _compute_keyword_overlap("bias testing required", "bias testing required") == 1.0

    def test_unrelated_text_does_not_overlap(self):
        assert _compute_keyword_overlap("carbon emissions", "judicial appointments") < 0.3

    def test_empty_claim_is_handled(self):
        assert _compute_keyword_overlap("", "anything") == 0.0


class TestVerifyCitation:
    def test_a_missing_chunk_fails_the_identity_check_first(self):
        result = verify_citation(
            chunk_id="nope",
            claim_text="anything",
            page_number=1,
            source_framework="F",
            vector_store=_FakeStore(present=set()),
        )

        assert result.passed is False
        assert result.chunk_exists is False
        assert "does not exist" in result.failure_reason

    def test_a_page_mismatch_is_reported(self):
        store = _FakeStore(
            present={"c1"},
            chunk={
                "text": "Article 12 requires logging.",
                "metadata": {"page_number": "5", "workspace_id": "w1"},
            },
        )

        result = verify_citation(
            chunk_id="c1",
            claim_text="Article 12 requires logging.",
            page_number=9,
            source_framework="F",
            vector_store=store,
        )

        assert result.page_exists is False

    def test_a_framework_chunk_is_not_bound_by_the_uploaded_documents_page_count(self):
        # A correct citation to page 89 of a 144-page framework was rejected
        # as "exceeds document length" against an unrelated 20-page upload.
        store = _FakeStore(
            present={"c1"},
            chunk={"text": "Requirement text.", "metadata": {"page_number": "89"}},
        )

        result = verify_citation(
            chunk_id="c1",
            claim_text="Requirement text.",
            page_number=89,
            source_framework="NIST AI RMF",
            vector_store=store,
            document_total_pages=20,
        )

        assert result.page_exists is True

    def test_a_workspace_chunk_beyond_the_document_length_is_rejected(self):
        store = _FakeStore(
            present={"c1"},
            chunk={"text": "Text.", "metadata": {"page_number": "89", "workspace_id": "w1"}},
        )

        result = verify_citation(
            chunk_id="c1",
            claim_text="Text.",
            page_number=89,
            source_framework="policy.pdf",
            vector_store=store,
            document_total_pages=20,
        )

        assert result.page_exists is False


class _FakeStore:
    def __init__(self, present, chunk=None):
        self.present = present
        self._chunk = chunk or {"text": "some text", "metadata": {"page_number": ""}}

    def get_chunk(self, chunk_id):
        return self._chunk if chunk_id in self.present else None

    def chunk_exists(self, chunk_id):
        return chunk_id in self.present

    @property
    def embedding_service(self):
        return self

    def embed_query(self, text):
        # Deterministic pseudo-embedding: identical text embeds identically,
        # which is all the similarity path needs here.
        return [float(len(text) % 7), 1.0, 0.5]


@pytest.fixture(autouse=True)
def _clear_ordinal_cache():
    _enumerated_ordinals.cache_clear()
    yield
    _enumerated_ordinals.cache_clear()
