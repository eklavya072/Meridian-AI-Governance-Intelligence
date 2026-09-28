"""A PDF that encodes no word boundaries costs the corpus its best instrument.

Measured: the EU AI Act loses 71.6 words per 1,000 to split-word damage —
"P osition of the European Parl iament" — against 0.0 for the UK AI Playbook.
Both pypdf and PyMuPDF return identical damage, so it is the file's encoding,
not the parser.
"""

from src.text_repair import _vocabulary, repair_split_words

HAS_DICT = bool(_vocabulary())


class TestRepair:
    def test_a_split_word_is_rejoined(self):
        out = repair_split_words("P osition of the European Parl iament")
        if not HAS_DICT:
            return
        assert "Position" in out and "Parliament" in out

    def test_digits_and_punctuation_survive(self):
        """An earlier version rebuilt the string from letter-tokens only and
        turned "of 13 March 2024 (not yet published)." into "of March" —
        silently deleting dates from legal text."""
        src = "Parl iament of 13 March 2024 (not yet published), p. 56."
        out = repair_split_words(src)
        for fragment in ("13", "2024", "(not yet published)", "p. 56."):
            assert fragment in out

    def test_ordinary_prose_is_untouched(self):
        for clean in (
            "The provider shall inform users of the system.",
            "A fine of EUR 35 000 000 or 7 % of turnover.",
        ):
            assert repair_split_words(clean) == clean

    def test_a_join_is_never_guessed(self):
        """ "form" is a real word, so "in form ation" -> "in formation" is a
        plausible-looking join with a different meaning. Both halves must be
        non-words before anything is merged."""
        src = "to day we review in form ation"
        assert repair_split_words(src) == src

    def test_a_line_break_is_not_a_split_word(self):
        src = "the provider\nshall comply"
        assert repair_split_words(src) == src

    def test_no_word_list_means_no_repair(self, monkeypatch):
        """A join it cannot verify is a join it must not make."""
        monkeypatch.setattr("src.text_repair._vocabulary", lambda: frozenset())
        src = "P osition of the Parl iament"
        assert repair_split_words(src) == src


class TestTheWordListTravelsWithTheCode:
    """Repair must not depend on which machine indexed the document."""

    def test_the_bundled_list_is_the_one_read_first(self):
        from src import text_repair

        assert text_repair._WORD_LISTS[0] == str(text_repair._BUNDLED_WORD_LIST)
        assert text_repair._BUNDLED_WORD_LIST.is_file()

    def test_the_bundled_list_loads_a_full_vocabulary(self):
        from src import text_repair

        text_repair._vocabulary.cache_clear()
        try:
            vocabulary = text_repair._vocabulary()
        finally:
            text_repair._vocabulary.cache_clear()

        assert len(vocabulary) > 200_000
        assert {"surveillance", "accountability", "office"} <= vocabulary
