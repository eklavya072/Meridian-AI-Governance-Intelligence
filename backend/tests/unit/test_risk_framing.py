"""Risk framing states the evidence, not the label, and never internal jargon.

Every stored gap carried one of a handful of templated sentences:

    "Core dimension 'Accountability' is only partially addressed.
     Risk compounded by related dimension gaps."
    "Supporting dimension 'Environmental Sustainability' is partially addressed."
    "Policy adequately addresses this dimension."

"Core"/"Supporting" is this tool's own taxonomy, not a property of the policy,
and the rest restates the coverage label the reader has already seen. Meanwhile
GovernanceGap.potential_consequence was declared, consumed by the executive
brief, and never populated — so the brief silently dropped its "what follows if
this is not fixed" line on all 64 stored gaps.
"""

import pytest

from src.evidence_strength import (
    EvidenceProfile,
    MechanismCoverage,
    describe_risk_basis,
)
from src.gap_analyzer import compute_risk
from src.models import CoverageLevel

DIM = "Environmental Sustainability"
MECH = MechanismCoverage(
    dimension=DIM,
    present={"energy reporting": 3},
    absent=["carbon disclosure", "e-waste / hardware lifecycle"],
)


def _profile(scored, commitment, institutional, binding, enforceable):
    return EvidenceProfile(
        dimension=DIM,
        n_scored=scored,
        n_commitment=commitment,
        n_institutional=institutional,
        n_binding=binding,
        n_enforceable=enforceable,
    )


# The shapes that actually occur in the live corpora.
SHAPES = {
    "eu_env": ("Partial", _profile(4, 3, 2, 1, 0)),
    "eu_privacy": ("Covered", _profile(30, 30, 28, 26, 16)),
    "japan_privacy": ("Covered", _profile(5, 4, 3, 2, 0)),
    "commitment_only": ("Partial", _profile(4, 3, 0, 0, 0)),
    "named_body_no_duty": ("Partial", _profile(4, 3, 2, 0, 0)),
    "missing": ("Missing", _profile(1, 0, 0, 0, 0)),
}


class TestNoInternalVocabularyReachesTheReader:
    @pytest.mark.parametrize("name", sorted(SHAPES))
    def test_taxonomy_words_never_appear(self, name):
        coverage, profile = SHAPES[name]
        basis, consequence = describe_risk_basis(coverage, profile, MECH)
        for banned in ("core dimension", "supporting dimension", "tier", "R1", "R2"):
            assert banned.lower() not in basis.lower()
            assert banned.lower() not in consequence.lower()

    @pytest.mark.parametrize("name", sorted(SHAPES))
    def test_basis_and_consequence_are_both_substantive(self, name):
        coverage, profile = SHAPES[name]
        basis, consequence = describe_risk_basis(coverage, profile, MECH)
        assert len(basis) > 40
        assert len(consequence) > 40


class TestFramingDistinguishesRealShapes:
    def test_unenforced_duty_reads_differently_from_enforced_duty(self):
        weak, _ = describe_risk_basis("Covered", SHAPES["japan_privacy"][1], MECH)
        strong, _ = describe_risk_basis("Covered", SHAPES["eu_privacy"][1], MECH)
        assert weak != strong
        assert "enforcement" in weak.lower() or "oversight" in weak.lower()
        assert "16" in strong

    def test_named_body_without_duty_is_its_own_case(self):
        basis, _ = describe_risk_basis("Partial", SHAPES["named_body_no_duty"][1], MECH)
        assert "named body" in basis.lower()
        assert "no binding requirement" in basis.lower()

    def test_absent_mechanisms_are_named(self):
        basis, _ = describe_risk_basis("Partial", SHAPES["eu_env"][1], MECH)
        assert "carbon disclosure" in basis

    def test_no_mechanism_data_still_produces_usable_text(self):
        basis, consequence = describe_risk_basis("Partial", SHAPES["eu_env"][1], None)
        assert basis and consequence
        assert "Not addressed" not in basis


class TestRiskLevelLogicIsUnchanged:
    """The basis explains the level; it must never move it."""

    @pytest.mark.parametrize("coverage", ["Covered", "Partial", "Missing"])
    def test_level_is_identical_with_and_without_a_basis(self, coverage):
        level_plain, _ = compute_risk(CoverageLevel(coverage), DIM)
        level_basis, _ = compute_risk(CoverageLevel(coverage), DIM, basis="Some basis text.")
        assert level_plain == level_basis

    def test_basis_replaces_the_generic_sentence(self):
        _, reason = compute_risk(CoverageLevel("Partial"), DIM, basis="Evidence-derived sentence.")
        assert reason.startswith("Evidence-derived sentence.")
        assert "Supporting dimension" not in reason

    def test_without_a_basis_the_original_wording_survives(self):
        """Degenerate paths (no profile) must still read sensibly."""
        _, reason = compute_risk(CoverageLevel("Partial"), DIM)
        assert DIM in reason
