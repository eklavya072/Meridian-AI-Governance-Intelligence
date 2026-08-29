"""Cite the document's own division wording, not a vocabulary we imposed.

Japan's AI Guidelines for Business is organised into Parts — the word
"Section" occurs in it zero times. The model wrote "Section 4" anyway, twice,
and the citation checker flagged both as fabricated.

The model was not hallucinating. The prompt said "Cite ONLY article, section
or recital numbers", a closed vocabulary borrowed from EU statutory drafting
that has no entry for "Part". Given a document full of Parts and a list that
excludes the word, mapping Part 4 onto the nearest permitted term is the
reasonable move. The substance was right — "Privacy protection" is real
document text and the neighbouring P-7 / P-4 / U-6 / U-7 codes all exist.
The instruction was wrong.
"""
import pytest

from src.analysis_prompts import _citation_instruction
from src.verify import (
    detect_division_vocabulary,
    classify_narrative_citations,
    _citation_present,
    DIVISION_KINDS,
)


class TestVocabularyDetection:
    def test_a_part_numbered_document_reports_part(self):
        texts = [
            "Part 1 Introduction to these Guidelines.",
            "Part 4 Matters Related to AI Providers ......... 32",
            "Part 5 Matters Related to AI Business Users.",
        ]
        assert detect_division_vocabulary(texts)[0] == "Part"

    def test_an_article_numbered_document_reports_article(self):
        texts = [
            "Article 6 classification rules for high-risk AI systems.",
            "Article 10 data and data governance.",
            "Recital 71 concerns traceability.",
        ]
        vocab = detect_division_vocabulary(texts)
        assert vocab[0] == "Article"
        assert "Recital" in vocab

    def test_ocr_split_headings_are_still_detected(self):
        """The EU AI Act extracts as "Ar ticle" on every page. A strict
        pattern reports its vocabulary as Paragraph/Section and misses the
        Articles the regulation is built from."""
        texts = ["Ar ticle 6 sets classification rules.",
                 "Ar ticle 10 covers data governance.",
                 "Ar ticle 54 concerns representatives."]
        assert detect_division_vocabulary(texts)[0] == "Article"

    def test_most_common_form_ranks_first(self):
        texts = ["Part 1.", "Part 2.", "Part 3.", "Section 9."]
        assert detect_division_vocabulary(texts)[0] == "Part"

    def test_no_numbered_divisions_yields_nothing(self):
        assert detect_division_vocabulary(["Prose with no numbered divisions."]) == []

    def test_empty_input_is_safe(self):
        assert detect_division_vocabulary([]) == []

    def test_part_and_chapter_are_recognised_kinds(self):
        """The original list stopped at Article/Recital/Annex/Section."""
        for kind in ("Part", "Chapter", "Clause", "Paragraph", "Schedule"):
            assert kind in DIVISION_KINDS


class TestCitationInstruction:
    def test_it_names_the_documents_own_form(self):
        text = _citation_instruction(["Part"])
        assert '"Part N"' in text

    def test_it_forbids_translating_into_another_scheme(self):
        text = _citation_instruction(["Part"])
        assert "do not write" in text.lower()
        assert "Section" in text

    def test_it_never_prescribes_a_closed_list_when_unknown(self):
        """With no detected vocabulary the model must mirror the document,
        not pick from article/section/recital."""
        text = _citation_instruction(None)
        assert "verbatim" in text.lower()
        assert "Part" in text and "Chapter" in text

    @pytest.mark.parametrize("vocab", [None, [], ["Part"], ["Article", "Recital"]])
    def test_the_literal_numbers_rule_always_survives(self, vocab):
        text = _citation_instruction(vocab)
        assert "literally appear" in text
        assert "without numbering it" in text


class TestBareOrdinalDivisions:
    """Legal instruments number divisions as bare ordinals — "4. Fairness and
    Equity", "38. (1) The provisions of this Act". The division word itself
    appears only in prose, so demanding the literal string "Principle 4"
    reported three real, correctly-read India citations as invented."""

    GUIDELINES = (
        "India adopts a framework anchored in seven Sutras. "
        "3. Innovation over Restraint 4. Fairness and Equity "
        "5. Accountability 6. Understandable by Design "
        "7. Safety, Resilience and Sustainability "
        "Using the seven principles or sutras as guidance, the Committee recommends."
    )
    ACT = (
        "THE DIGITAL PERSONAL DATA PROTECTION ACT, 2023 "
        "4. (1) A person may process the personal data of a Data Principal. "
        "38. (1) The provisions of this Act shall have effect. "
        "as provided under section 5 of this Act."
    )

    def test_ordinal_headings_count_as_present(self):
        assert _citation_present("Principle", "4", self.GUIDELINES)
        assert _citation_present("Principle", "6", self.GUIDELINES)
        assert _citation_present("Section", "4", self.ACT)

    def test_a_number_the_document_never_enumerates_is_still_caught(self):
        assert not _citation_present("Principle", "8", self.GUIDELINES)
        assert not _citation_present("Section", "250", self.ACT)

    def test_a_division_word_the_document_lacks_is_still_caught(self):
        """Enumerating 1-7 must not clear a citation to a kind of division the
        instrument does not contain."""
        assert not _citation_present("Recital", "4", self.GUIDELINES)
        assert not _citation_present("Annex", "4", self.GUIDELINES)

    def test_documents_are_scored_separately(self):
        """Joining a 44-section statute onto a 7-sutra note would lend the note
        ordinals it does not have."""
        split = classify_narrative_citations(
            ["Principle 8 requires it."], "unrelated retrieved text",
            [self.GUIDELINES],
        )
        assert split["fabricated"] == ["Principle 8"]

    def test_real_citations_are_not_reported_as_fabricated(self):
        split = classify_narrative_citations(
            ["Principle 4 and Principle 6 apply; see Section 4."],
            "unrelated retrieved text",
            [self.GUIDELINES, self.ACT],
        )
        assert split["fabricated"] == []
