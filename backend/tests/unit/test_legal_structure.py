"""Reading legislation as structure instead of guessing at it from a PDF."""

import pytest

from src.legal_structure import (
    LegalUnit,
    article_paragraphs,
    operative_text,
    parse_oj_html,
)

OJ = """
<div class="eli-subdivision" id="rct_1"><table><tr><td><p>(1)</p></td>
<td><p>The purpose of this Regulation is to improve the internal market.</p></td></tr></table></div>
<div class="eli-subdivision" id="rct_178"><table><tr><td><p>(178)</p></td>
<td><p>Providers are encouraged to comply, on a voluntary basis, during the transition.</p></td></tr></table></div>
<div class="eli-subdivision" id="art_3"><p class="oj-ti-art">Article 3</p>
<p class="oj-sti-art">Definitions</p><p>For the purposes of this Regulation, 'AI system' means a machine-based system.</p></div>
<div class="eli-subdivision" id="art_10"><p class="oj-ti-art">Article 10</p>
<p class="oj-sti-art">Data and data governance</p>
<p>1.   High-risk AI systems shall be developed on the basis of training data sets.</p>
<p>2.   Training data sets shall be subject to data governance practices.
Those practices shall concern in particular:</p>
<table><tr><td><p>(g)</p></td><td><p>appropriate measures to detect, prevent and mitigate possible biases;</p></td></tr></table></div>
</body>
"""


class TestStructuralParsing:
    def test_recitals_and_articles_are_separated_by_id_not_by_guessing(self):
        units = parse_oj_html(OJ)
        kinds = {u.kind for u in units}
        assert kinds == {"recital", "article"}
        assert {u.number for u in units if u.kind == "recital"} == {"1", "178"}
        assert {u.number for u in units if u.kind == "article"} == {"3", "10"}

    def test_recitals_are_marked_non_operative(self):
        """Under EU law a recital aids interpretation and binds nobody. 60% of
        the AI Act's 'binding' sentences were coming from here."""
        units = parse_oj_html(OJ)
        assert all(not u.operative for u in units if u.kind == "recital")
        assert all(u.operative for u in units if u.kind == "article")

    def test_recital_178_can_no_longer_be_read_as_an_obligation(self):
        """The exact text that once capped every EU provision at Intentional."""
        r178 = next(u for u in parse_oj_html(OJ) if u.number == "178")
        assert not r178.operative

    def test_article_titles_are_read_from_their_own_element(self):
        a10 = next(u for u in parse_oj_html(OJ) if u.kind == "article" and u.number == "10")
        assert a10.title == "Data and data governance"

    def test_the_definitions_article_is_identified_and_excluded(self):
        units = parse_oj_html(OJ)
        a3 = next(u for u in units if u.number == "3")
        assert a3.is_definitions
        assert not any(p.startswith("Article 3") for p, _ in operative_text(units))

    def test_paragraphs_keep_their_lists_attached(self):
        a10 = next(u for u in parse_oj_html(OJ) if u.kind == "article" and u.number == "10")
        paras = dict(article_paragraphs(a10))
        assert "Article 10(1)" in paras and "Article 10(2)" in paras
        assert "(g)" in paras["Article 10(2)"], "the list must stay inside its paragraph"

    def test_operative_text_carries_real_citation_paths(self):
        paths = [p for p, _ in operative_text(parse_oj_html(OJ))]
        assert "Article 10(2)" in paths
        assert not any(p.startswith("Recital") for p in paths)

    def test_a_pdf_derived_document_is_left_alone(self):
        """Anything that is not OJ HTML must fall through to the PDF path."""
        assert parse_oj_html("Kenya National AI Strategy 2025-2030. Pillar 1.") == []
        assert parse_oj_html("") == []


class TestDivisionScopedDutyBearer:
    """The bearer named at the top of a paragraph governs all of its points."""

    FRAGS = [
        "Training data sets shall be subject to data governance practices.",
        "Those practices shall concern in particular: (g) appropriate measures "
        "to detect, prevent and mitigate possible biases;",
    ]

    def test_a_point_inherits_the_bearer_its_paragraph_established(self):
        from src.evidence_strength import TIER_OBLIGATORY, detect_mechanisms
        from src.grading import classify_division

        scored = classify_division(self.FRAGS, dimension="Fairness")
        assert any(s.tier >= TIER_OBLIGATORY and "bias" in s.text.lower() for s in scored)
        assert detect_mechanisms(scored, "Fairness").present.get("bias mitigation", 0) >= TIER_OBLIGATORY

    def test_evidence_still_quotes_the_document_not_our_reconstruction(self):
        from src.grading import classify_division

        scored = classify_division(self.FRAGS, dimension="Fairness")
        for s in scored:
            assert "Training data sets shall be subject" not in s.text or s.text == self.FRAGS[0]

    def test_a_government_division_is_never_lifted(self):
        from src.evidence_strength import TIER_ASSIGNED
        from src.grading import classify_division

        scored = classify_division(
            ["The Authority shall maintain the register.",
             "It shall in particular: (a) publish annual reports;"],
            dimension="Transparency",
        )
        assert all(s.tier <= TIER_ASSIGNED for s in scored)

    def test_aspiration_inside_a_binding_paragraph_stays_aspiration(self):
        from src.grading import classify_division

        scored = classify_division(
            ["Providers shall maintain logs.", "Systems should ideally be explainable."],
            dimension="Transparency",
        )
        assert scored[-1].tier == 0
