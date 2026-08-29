"""Module 3's responsible-agency gate: name the real body, invent nothing.

Two independent defects made this field read "Not specified by policy —
implementation responsibility should be assigned by the adopting government"
for the EU AI Act, a regulation that creates the AI Office and names it 56
times:

  1. "ai" sat in the first-token skip list, so ANY body whose name starts
     with "AI" was discarded before the designator gate ever saw it. In an
     AI-governance tool that skipped exactly the institutions AI laws create.
  2. Verification compared raw strings against PDF-extracted text. On the
     live EU corpus "market surveillance authorit" occurs 0 times literally
     and 233 times once OCR word-splitting is allowed.
"""

import pytest

from src.gap_analyzer import (
    GapAnalyzer,
    _extract_document_grounded_institutions,
    _has_named_body_keyword_ocr,
    _ocr_tolerant_phrase,
)

DIM = "Environmental Sustainability"
# Verbatim from the uploaded EU AI Act: "Office" is split by extraction.
OCR_CHUNK = [
    {
        "text": "The European Ar tif icial Intellig ence Off ice (AI Offi ce) shall "
        "monitor energy consumption and carbon emission reporting for AI syste ms."
    }
]
CLEAN_CHUNK = [
    {
        "text": "The AI Office shall monitor energy consumption and carbon "
        "emission reporting for AI systems."
    }
]


class TestAIPrefixedBodiesAreIdentifiable:
    DOC = (
        "The European Artificial Intelligence Office (AI Office) shall act. "
        "The AI Board advises Member States. "
        "Digital Public Infrastructure continues to expand."
    )

    def test_ai_office_and_ai_board_are_found(self):
        found = _extract_document_grounded_institutions(
            [
                "Task the AI Office with periodic reviews.",
                "Coordinate with the AI Board on guidance.",
            ],
            self.DOC,
        )
        assert found == ["AI Office", "AI Board"]

    def test_generic_capitalised_noun_phrases_are_still_rejected(self):
        """The designator gate, not the skip list, is what excludes these."""
        assert (
            _extract_document_grounded_institutions(
                ["Expand Digital Public Infrastructure and Generative AI adoption."],
                self.DOC,
            )
            == []
        )

    def test_bare_ai_is_never_named_as_an_institution(self):
        """ "AI" appears in every sentence of every document this tool reads."""
        found = _extract_document_grounded_institutions(
            ["Improve AI adoption across AI programmes using AI."], self.DOC
        )
        assert "AI" not in found

    def test_a_body_absent_from_the_document_is_not_returned(self):
        assert (
            _extract_document_grounded_institutions(
                ["Task the Ministry of Truth with oversight."], self.DOC
            )
            == []
        )

    def test_acronyms_of_three_or_more_letters_still_work(self):
        doc = "BIS and MeitY jointly publish standards."
        found = _extract_document_grounded_institutions(
            ["Direct BIS and MeitY to publish standards."], doc
        )
        assert found == ["BIS", "MeitY"]


class TestVerificationSurvivesOcr:
    def test_split_words_still_match_the_agency_name(self):
        pattern = _ocr_tolerant_phrase("AI Office")
        assert pattern.search("The AI Off ice shall act")
        assert pattern.search("A I Offi ce reviews")

    def test_word_boundaries_are_preserved(self):
        """Tolerating splits must not reopen substring holes."""
        assert not _ocr_tolerant_phrase("board").search("keyboard")

    def test_named_body_keywords_tolerate_splitting(self):
        assert _has_named_body_keyword_ocr("the Off ice shall act")
        assert _has_named_body_keyword_ocr("the authority may require")
        assert not _has_named_body_keyword_ocr("the keyboard was replaced")

    def test_minister_stem_still_matches_only_its_family(self):
        assert _has_named_body_keyword_ocr("the Minister of Science and ICT")
        assert not _has_named_body_keyword_ocr("the administration decided")

    @pytest.mark.parametrize("chunks", [OCR_CHUNK, CLEAN_CHUNK])
    def test_real_agency_is_confirmed_on_both_clean_and_ocr_text(self, chunks):
        name, grounding = GapAnalyzer._verify_responsible_agency(
            "AI Office", "document_named", chunks, DIM
        )
        assert name == "AI Office"
        assert grounding == "document_named"


class TestAntiFabricationStillHolds:
    def test_agency_absent_from_the_document_is_rejected(self):
        _, grounding = GapAnalyzer._verify_responsible_agency(
            "Ministry of Truth", "document_named", CLEAN_CHUNK, DIM
        )
        assert grounding == "none_identified"

    def test_no_dimension_topical_chunk_means_no_agency(self):
        _, grounding = GapAnalyzer._verify_responsible_agency(
            "AI Office", "document_named", [{"text": "unrelated boilerplate"}], DIM
        )
        assert grounding == "none_identified"

    def test_none_identified_keeps_the_honest_phrasing(self):
        name, grounding = GapAnalyzer._verify_responsible_agency(
            "Some Plausible Agency", "none_identified", CLEAN_CHUNK, DIM
        )
        assert grounding == "none_identified"
        assert "not specified by policy" in name.lower()
