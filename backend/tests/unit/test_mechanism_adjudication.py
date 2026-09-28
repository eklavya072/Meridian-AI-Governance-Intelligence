"""Cue matches are generous; adjudication is what makes them mean something.

The failure this guards against is not a wrong score — it is a gap that
DISAPPEARS. A mechanism wrongly marked present is never listed as missing, so
Kenya reported nothing absent on Transparency while its cue matches were a
complaints provision and "the Office shall have all powers necessary".
"""

from dataclasses import dataclass, field

import pytest

from src.mechanism_adjudication import (
    APPLIED,
    UNAVAILABLE,
    _rank_candidates,
    _repair_split_words,
    adjudicate_batch,
)


@dataclass
class _Sent:
    text: str
    tier: int = 0
    excluded: str = ""


@dataclass
class _Match:
    dimension: str = "Transparency"
    present: dict = field(default_factory=dict)
    absent: list = field(default_factory=list)

    def __init__(self, dimension="Transparency", present=None, absent=None):
        self.dimension = dimension
        self.present = dict(present or {})
        self.absent = list(absent or [])


class _Provider:
    """Answers with fixed picks, or raises.

    Not tier "primary", so generate_with_retry hands it the call directly —
    the same structured-output path production uses, without the network.
    """

    tier = "stub"
    model_name = "stub"

    def __init__(self, picks=None, boom=False):
        self.picks = picks
        self.boom = boom
        self.prompts = []

    def generate_structured(self, prompt, schema, system_prompt=None):
        self.prompts.append(prompt)
        if self.boom:
            raise RuntimeError("provider down")
        return schema(picks=[{"m": m, "pick": k} for m, k in self.picks or []])


REAL = "The Commissioner shall maintain a public register of high-risk artificial intelligence systems."
INCIDENTAL = (
    "The Office shall have all powers necessary for the proper performance of its functions."
)


class TestAdjudication:
    @staticmethod
    def _one(match, sentences, provider):
        return adjudicate_batch({"Transparency": (match, sentences)}, provider)["Transparency"]

    def test_an_incidental_match_becomes_a_reported_gap(self):
        m = _Match(present={"public registry": 3}, absent=[])
        out = self._one(m, [_Sent(INCIDENTAL, 3), _Sent(REAL, 3)], _Provider([(1, 0)]))

        assert "public registry" not in out.present
        assert "public registry" in out.absent, "a rejected mechanism must show up as MISSING"
        assert out.adjudication == APPLIED

    def test_a_real_match_is_kept_and_retiered_from_the_chosen_sentence(self):
        m = _Match(present={"public registry": 0}, absent=[])
        # The cue pass had tier 0; the sentence the model picks carries 3.
        out = self._one(m, [_Sent(REAL, 3), _Sent(INCIDENTAL, 1)], _Provider([(1, 1)]))

        assert out.present.get("public registry") == 3

    def test_a_failure_keeps_the_cue_result_and_says_so(self):
        """The run must not fail — but the fallback over-reports presence, and
        the gate reads presence downward-only, so it must never pass silently
        for an adjudicated answer."""
        m = _Match(present={"public registry": 3}, absent=["decision explanation"])
        out = self._one(m, [_Sent(REAL, 3)], _Provider(boom=True))

        assert out.present == {"public registry": 3}
        assert out.absent == ["decision explanation"]
        assert out.adjudication == UNAVAILABLE

    def test_no_provider_means_never_attempted_not_failed(self):
        m = _Match(present={"public registry": 3}, absent=[])
        out = self._one(m, [_Sent(REAL, 3)], None)

        assert out.present == {"public registry": 3}
        assert getattr(out, "adjudication", "") == ""

    def test_a_mechanism_with_no_candidates_is_not_silently_dropped(self):
        """It was never the model's to judge, so the cue verdict stands."""
        m = _Match(present={"public registry": 2}, absent=[])
        # No sentence matches the registry cues at all.
        out = self._one(m, [_Sent("Unrelated text about budgets.", 1)], _Provider([]))

        assert out.present.get("public registry") == 2


class TestCandidateRanking:
    def test_candidates_are_not_ranked_by_force(self):
        """Ranking by tier is the bias that caused this: it puts the penalty
        clause at the top of every list. Density favours a provision ABOUT the
        mechanism over a long clause that mentions it once."""
        import re

        pattern = re.compile(r"regist\w*", re.IGNORECASE)
        long_forceful = _Sent(
            "Where a person fails to comply with any requirement imposed under this Part, "
            "including any duty to register, the Commissioner may impose a penalty not "
            "exceeding seventeen million pounds or four per cent of turnover.",
            tier=4,
        )
        short_on_point = _Sent("High-risk systems shall be registered.", tier=3)

        ranked = _rank_candidates([long_forceful, short_on_point], pattern)

        assert ranked[0] is short_on_point, "the on-point provision must outrank the penalty clause"


class TestSplitWordRepair:
    """The model reads raw text; the cue matcher does not.

    A PDF line break turns "shall" into "shal l". The cue pass tolerates it
    through ocr_flexible_fragment and so still FINDS the provision, but the
    adjudicator hands the text to a model that reads two tokens and sees no
    duty. Two of the five broken instances in this corpus are Kenya's
    public-register provision, which is exactly what it wrongly rejected.
    """

    @pytest.mark.parametrize(
        "broken",
        [
            "The Commissioner shal l maintain a public register of high-risk systems.",
            "A user of an artificial intelligence system s hall, where decisions produce",
        ],
    )
    def test_a_break_anywhere_in_the_word_is_rejoined(self, broken):
        assert "shall" in _repair_split_words(broken).lower()

    def test_clean_text_is_left_exactly_as_it_was(self):
        clean = "He shall maintain the register."
        assert _repair_split_words(clean) == clean

    def test_an_unrelated_letter_is_not_swallowed(self):
        """ "small l shaped" must not become "smalll" — the rejoin only fires
        when the result is a word we are actually repairing."""
        text = "The small l shaped room stayed the same."
        assert _repair_split_words(text) == text


class TestBatching:
    """Eight calls per country became one.

    The free-tier quota counts REQUESTS, not tokens, so asking per dimension
    took the daily ceiling from roughly five countries to three and killed a
    run mid-batch. Prompt size is not the lever; call count is.
    """

    def _requests(self):
        return {
            "Transparency": (
                _Match("Transparency", {"public registry": 3}, []),
                [_Sent(REAL, 3), _Sent(INCIDENTAL, 3)],
            ),
            "Safety": (
                _Match("Safety", {"risk assessment": 3}, []),
                [_Sent("A provider shall conduct a risk assessment before deployment.", 3)],
            ),
        }

    def test_two_dimensions_cost_one_call(self):
        provider = _Provider([(1, 0), (2, 1)])

        adjudicate_batch(self._requests(), provider)

        assert len(provider.prompts) == 1, "one call for the whole workspace"

    def test_each_dimension_gets_its_own_answer(self):
        out = adjudicate_batch(self._requests(), _Provider([(1, 0), (2, 1)]))

        assert "public registry" in out["Transparency"].absent
        assert "risk assessment" in out["Safety"].present

    def test_the_prompt_names_each_dimension(self):
        """Mechanisms share names across dimensions; without the grouping the
        model cannot tell which dimension it is judging against."""
        provider = _Provider([])

        adjudicate_batch(self._requests(), provider)

        assert "DIMENSION: Transparency" in provider.prompts[0]
        assert "DIMENSION: Safety" in provider.prompts[0]

    @pytest.mark.parametrize("provider", [_Provider(boom=True), None])
    def test_a_failure_leaves_every_dimension_on_its_cue_result(self, provider):
        out = adjudicate_batch(self._requests(), provider)

        assert out["Transparency"].present == {"public registry": 3}
        assert out["Safety"].present == {"risk assessment": 3}
