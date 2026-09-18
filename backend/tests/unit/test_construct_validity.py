"""Does the instrument measure what it claims — checked without an external index.

Per-dimension validation against GIRAI covers 21 of 56 cells, because GIRAI
publishes a comparable thematic score for only three of the eight dimensions.
The other 35 cells have no published benchmark anywhere. That is a real ceiling
on external validation, and these tests exist because two kinds of evidence do
NOT need a third party:

  KNOWN GROUPS   score instruments whose relative force nobody disputes. A
                 statute with criminal penalties must outrank a strategy that
                 imposes nothing. If the scorer cannot separate those, no
                 external benchmark would rescue it.
  FALSIFICATION  inject a provision we wrote ourselves, so ground truth is
                 certain, and require the right cell to move by the right
                 amount — and the wrong cells not to.

Both run on synthetic text rather than the corpus, so they are fast, offline
and stable. The corpus-wide versions were measured once and are recorded in
docs/ENGINEERING-NOTES.md; these pin the behaviour they established.
"""

from src.evidence_strength import depth_from_profile
from src.grading import (
    build_provision_profile,
    detect_enforcement_regime,
    evidence_is_sufficient,
)

STAGE = {
    "Unaddressed": 0.0,
    "Emerging": 50.0,
    "Delegated": 65.0,
    "Operationalized": 78.0,
    "Institutionalized": 100.0,
}

# A statute: duties on regulated parties, with a penalty behind them.
BINDING = [
    "A data fiduciary shall implement appropriate technical and organisational "
    "measures to ensure effective observance of the provisions of this Act.",
    "A data fiduciary shall protect personal data in its possession by taking "
    "reasonable security safeguards to prevent a personal data breach.",
    "In the event of a personal data breach, the data fiduciary shall give the "
    "Board intimation of such breach in the form and manner prescribed.",
    "A person who contravenes section 8 commits an offence and is liable, on "
    "conviction, to a penalty not exceeding two hundred and fifty crore rupees.",
    "The Board may inspect the records of a data fiduciary and may impose a "
    "financial penalty after giving the person an opportunity to be heard.",
]

# A strategy: the same subject matter, imposing nothing on anyone.
SOFT = [
    "Personal data should be protected throughout the lifecycle of an AI system.",
    "The government will develop guidance on the handling of personal data.",
    "Organisations are encouraged to adopt privacy-protective design practices.",
    "Stakeholders including industry and civil society should collaborate on "
    "responsible handling of personal information.",
    "Privacy remains a core value guiding the national approach to artificial "
    "intelligence over the strategy period.",
]


def _depth(sentences: list[str], dimension: str = "Privacy") -> float:
    profile = build_provision_profile(sentences, dimension=dimension)
    if profile.n_scored == 0 or not evidence_is_sufficient(profile.n_scored, profile.n_binding):
        return 0.0
    regime = detect_enforcement_regime(sentences)
    return STAGE[depth_from_profile(profile, document_enforcement_regime=regime)[0]]


class TestKnownGroups:
    """Instruments whose relative force is not in dispute."""

    def test_a_statute_outranks_a_strategy_on_the_same_subject(self):
        """Measured corpus-wide: 4 binding instruments 80.2-86.0, 6 soft
        0.0-71.5, no overlap. This pins the property on synthetic text."""
        assert _depth(BINDING) > _depth(SOFT)

    def test_a_strategy_cannot_reach_the_binding_stages(self):
        """Delegated (65) is the ceiling for text that binds nobody."""
        assert _depth(SOFT) <= 65.0

    def test_a_narrow_statute_is_not_punished_for_being_narrow(self):
        """The confound this guards against: averaging a force score across
        dimensions a document never addresses scores a binding statute BELOW
        voluntary guidance that touches everything weakly. The evidence gate
        withholds those dimensions instead, and must keep doing so."""
        assert not evidence_is_sufficient(n_scored=2, n_binding=0)
        assert evidence_is_sufficient(n_scored=40, n_binding=9)


class TestFalsification:
    """Ground truth we control, because we wrote the provision."""

    def test_an_injected_enforceable_duty_raises_the_cell(self):
        before = build_provision_profile(SOFT, dimension="Safety")
        after = build_provision_profile(
            SOFT
            + [
                "Providers of high-risk artificial intelligence systems shall carry "
                "out pre-deployment testing before placing the system on the market; "
                "a provider who fails to do so commits an offence and is liable to a "
                "fine not exceeding fifty million shillings."
            ],
            dimension="Safety",
        )
        assert after.n_binding > before.n_binding
        assert after.n_enforceable > before.n_enforceable

    def test_an_injected_aspiration_moves_nothing(self):
        """A scorer that rewards "should" for saying the right words is
        measuring vocabulary, which is the failure this whole ladder exists
        to avoid."""
        before = build_provision_profile(SOFT, dimension="Environmental Sustainability")
        after = build_provision_profile(
            SOFT
            + [
                "Artificial intelligence should be environmentally sustainable and "
                "developers are encouraged to consider the carbon footprint of training."
            ],
            dimension="Environmental Sustainability",
        )
        assert after.n_binding == before.n_binding
        assert after.n_enforceable == before.n_enforceable

    def test_one_injected_duty_does_not_buy_the_top_stage(self):
        """A single binding sentence lifts every weaker counter with it, so the
        force bar deliberately needs two — or one plus enforcement."""
        profile = build_provision_profile(
            SOFT
            + [
                "Providers shall ensure that high-risk artificial intelligence systems "
                "comply with accessibility requirements for persons with disabilities."
            ],
            dimension="Inclusivity",
        )
        assert profile.n_binding == 1
        assert depth_from_profile(profile)[0] != "Institutionalized"


class TestReproducibility:
    """Deterministic scoring is a claim, so it gets a test."""

    def test_the_same_document_scores_the_same_every_time(self):
        runs = {_depth(BINDING) for _ in range(5)}
        assert len(runs) == 1
