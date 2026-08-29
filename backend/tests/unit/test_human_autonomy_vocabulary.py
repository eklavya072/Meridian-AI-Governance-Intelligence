"""Human oversight is a duty in many drafting traditions, not one phrase.

Korea's AI Framework Act, Article 34(1)(4), requires "Human management and
supervision of high-impact AI" under an obligation reading "must implement the
following measures". Meridian scored Human Autonomy as Missing / Unaddressed /
High risk for a law that mandates human oversight of its highest-risk tier.

The cause was vocabulary, not logic: DIMENSION_CORE_TERMS carried the EU AI
Act's "human oversight" and nothing else close to it, so an identical duty
written in Korean legislative English was invisible. GDPR Article 22's "human
intervention" was missing for the same reason. This is the same failure mode as
prescribing article/section/recital to a document organised into Parts —
assuming one tradition's wording is the concept.
"""
import pytest

from src.deterministic import DIMENSION_CORE_TERMS, _sentence_has_core_term

DIM = "Human Autonomy"

# Verbatim (or near) from the real instruments.
REAL_PROVISIONS = {
    "korea_art34": "AI business operators providing high-impact AI must implement "
                   "the following measures: Human management and supervision of "
                   "high-impact AI.",
    "gdpr_art22": "The data subject has the right to obtain human intervention on "
                  "the part of the controller.",
    "eu_ai_act": "High-risk AI systems shall be designed to enable effective human "
                 "oversight by natural persons.",
    "japan_guidelines": "Human intervention allows human dignity and autonomy to be "
                        "conserved, helping to prevent unexpected incidents.",
    "human_review": "Affected persons may request human review of an automated decision.",
}

# Phrases that use the same words for entirely different concepts. These run
# through every one of these documents and must never register as human
# oversight.
COLLISIONS = {
    "market_surveillance": "The market surveillance authority shall exercise "
                           "supervision over providers.",
    "corporate_management": "Senior management shall approve the risk management plan.",
    "supervisory_authority": "The supervisory authority may conduct investigations.",
    "data_management": "The provider shall establish data management procedures.",
}


class TestOversightDutiesAreRecognisedAcrossTraditions:
    @pytest.mark.parametrize("name", sorted(REAL_PROVISIONS))
    def test_provision_matches_human_autonomy(self, name):
        assert _sentence_has_core_term(REAL_PROVISIONS[name], DIM), (
            f"{name} states a human-oversight duty and must be visible to the "
            "Human Autonomy dimension."
        )

    def test_the_korean_phrasing_specifically(self):
        """The exact miss this test file exists for."""
        assert _sentence_has_core_term(
            "4. Human management and supervision of high-impact AI", DIM
        )


class TestNoCollisionWithRegulatorySupervision:
    @pytest.mark.parametrize("name", sorted(COLLISIONS))
    def test_phrase_does_not_register_as_human_oversight(self, name):
        assert not _sentence_has_core_term(COLLISIONS[name], DIM), (
            f"{name} is regulatory or corporate supervision, not human "
            "oversight of an AI system."
        )

    def test_bare_supervision_and_management_are_not_terms(self):
        """Only 'human X' bigrams were added, deliberately."""
        terms = DIMENSION_CORE_TERMS[DIM]
        assert "supervision" not in terms
        assert "management" not in terms
        for added in ("human management", "human supervision", "human intervention"):
            assert added in terms
