"""Module 3 can only name a body it was shown.

Every gapped dimension reported "Not specified by policy — implementation
responsibility should be assigned by the adopting government" on a corpus that
names the Personal Information Protection Commission 53 times and an AI
Strategic Headquarters 10 times.

The verification gate was not the blocker — it would have accepted those names.
The model simply never proposed one: Module 3 is shown two document chunks,
told to name the responsible body, and warned three times not to invent one, so
"none_identified" was the only safe answer available to it. Candidates are now
extracted deterministically from the dimension's own passages and offered.
"""
import pytest

from src.gap_analyzer import document_named_bodies, _is_institution_phrase

PRIVACY_TEXT = (
    "The Personal Information Protection Commission shall supervise the handling "
    "of personal information and may issue guidance to a business operator "
    "concerning the protection of personal data."
)


def _chunks(*texts):
    return [{"text": t} for t in texts]


class TestBodiesAreFound:
    def test_a_named_commission_is_extracted(self):
        found = document_named_bodies(_chunks(PRIVACY_TEXT), "Privacy")
        assert "Personal Information Protection Commission" in found

    def test_ordering_is_by_frequency(self):
        other = (
            "The Board of Audit reviews personal data handling once. "
        )
        found = document_named_bodies(
            _chunks(PRIVACY_TEXT, PRIVACY_TEXT, other), "Privacy"
        )
        assert found[0] == "Personal Information Protection Commission"

    def test_only_dimension_topical_passages_are_read(self):
        """A body named in an unrelated passage is not a candidate here."""
        env = "The Ministry of Economy shall promote energy efficiency and carbon reporting."
        assert document_named_bodies(_chunks(env), "Privacy") == []
        assert document_named_bodies(_chunks(env), "Environmental Sustainability")


class TestNoiseIsRejected:
    """All six of these appeared as candidates on the live Japan corpus."""

    @pytest.mark.parametrize("phrase", [
        "Cabinet Order",                                   # an instrument
        "Local Incorporated Administrative Agency Act",    # an Act
        "General Rules for Incorporated Administrative Agency",
        "Term of Office",                                  # ordinary noun
        "Delegation of Authority",
        "Exercising Authority",
    ])
    def test_designator_bearing_non_institutions_are_dropped(self, phrase):
        assert not _is_institution_phrase(phrase)

    @pytest.mark.parametrize("phrase", [
        "Personal Information Protection Commission",
        "Ministry of Internal Affairs and Communications",
        "Board of Audit",
        "Administrative Complaint Review Board",
    ])
    def test_real_institutions_survive(self, phrase):
        assert _is_institution_phrase(phrase)

    def test_a_truncated_duplicate_is_dropped(self):
        """The regex also matches "Protection Commission" inside the full name;
        offering both invites the model to cite the truncated form."""
        found = document_named_bodies(_chunks(PRIVACY_TEXT), "Privacy")
        assert "Protection Commission" not in found

    def test_a_following_sentence_is_not_swept_into_the_name(self):
        text = (
            "Personal data is supervised by the Personal Information Protection "
            "Commission. The operator shall comply."
        )
        found = document_named_bodies(_chunks(text), "Privacy")
        assert all(not f.endswith("The") for f in found)

    def test_no_topical_passages_yields_nothing(self):
        assert document_named_bodies(_chunks("Unrelated boilerplate."), "Privacy") == []
