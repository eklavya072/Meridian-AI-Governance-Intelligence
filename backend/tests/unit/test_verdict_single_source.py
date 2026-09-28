"""The verdict is computed once per dimension, and read back everywhere else.

Every contradiction found in QA so far has the same shape: two pieces of code
answering the same question about the same document, drifting apart because a
fix landed on one of them.

    coverage      computed pre-LLM WITH the mechanism gate, and again
                  post-LLM WITHOUT it -> a soft-law guideline shipped
                  "Covered" for Privacy above "Provides 1 of 7 governance
                  mechanisms ... Not addressed: consent, data minimisation".
                  The prompt said Partial. The stored verdict said Covered.

    depth      coverage's force bar was corrected; depth kept its own
                  copy of the old degenerate threshold -> "Partial ... stands
                  alone rather than forming a developed regime" reported
                  alongside "Operationalized".

    reason_flagged  the reconciliation that stops a Covered verdict shipping
                  under "lacks..." prose sat behind a flag the winning code
                  path clears, so it only ever ran on the fallback path.

These are not three bugs. They are one bug three times, and it recurs for as
long as duplicate computations are allowed to exist. This module fails the
build when a second call site appears.
"""

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "gap_analyzer.py"

# Each of these decides part of the verdict. _compute_deterministic_verdict
# calls them once, before the LLM call, and stores the result in `determined`.
# Anything downstream must read `determined`, never recompute.
SINGLE_CALL_ONLY = {
    "coverage_from_profile": 1,
    "depth_from_profile": 1,
    "detect_mechanisms": 1,
    "build_provision_profile": 1,
    "retrieve_scoring_pool": 1,
}


def _call_sites(tree):
    counts: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else None
        )
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts


@pytest.mark.parametrize("func,expected", sorted(SINGLE_CALL_ONLY.items()))
def test_verdict_inputs_have_exactly_one_call_site(func, expected):
    counts = _call_sites(ast.parse(SRC.read_text()))
    actual = counts.get(func, 0)
    assert actual == expected, (
        f"{func}() has {actual} call sites in gap_analyzer.py, expected "
        f"{expected}.\n\n"
        "The verdict is computed once, in _compute_deterministic_verdict, and "
        "handed to the model as an input. If you need this value later, read "
        "it from the `determined` dict — do not call it again. A second call "
        "site is a second answer to the same question, and the two WILL drift: "
        "that is exactly how Covered/1-of-7-mechanisms and "
        "Partial/Operationalized both shipped."
    )


def test_determined_dict_exposes_everything_downstream_needs():
    """The read-back path only works if the verdict actually carries these."""
    from src.gap_analyzer import GapAnalyzer  # noqa: F401

    source = SRC.read_text()
    start = source.index("def _compute_deterministic_verdict")
    end = source.index("def _analyze_dimension_combined")
    returned = source[start:end]
    for key in (
        "profile",
        "scoring_pool",
        "coverage_label",
        "coverage_note",
        "depth_label",
        "depth_note",
        "mechanisms",
    ):
        assert f'"{key}"' in returned, (
            f"_compute_deterministic_verdict must return '{key}' — downstream "
            "code reads it instead of recomputing."
        )


class TestCoveredNeverShipsUnderGapProse:
    """A Covered verdict and "the document lacks X" cannot both be true.

    Live output, Nigeria and Kenya, Inclusivity, both marked Covered:
      "...but lacks technical mechanisms for algorithmic bias testing,
       accessibility standards, or demographic fairness monitoring."
    """

    def test_real_shipped_contradictions_are_detected(self):
        from src.consistency import (
            GAP_ASSERTION_THRESHOLD,
            detect_gap_assertions,
        )

        for text in (
            "The strategy highlights principles of inclusion, diversity, and "
            "non-discrimination and commits to a foresight study on vulnerable "
            "groups, but lacks technical mechanisms for algorithmic bias "
            "testing, accessibility standards, or demographic fairness monitoring.",
            "The strategy acknowledges inclusivity and social inclusion in "
            "principle but lacks concrete operational mechanisms such as "
            "mandatory bias testing, accessibility requirements, or formal "
            "participatory channels for underrepresented groups.",
        ):
            score, phrases = detect_gap_assertions(text)
            assert score >= GAP_ASSERTION_THRESHOLD, phrases

    def test_clean_covered_prose_is_left_alone(self):
        """The reconciliation must not rewrite text that says nothing wrong."""
        from src.consistency import (
            GAP_ASSERTION_THRESHOLD,
            detect_gap_assertions,
        )

        score, _ = detect_gap_assertions(
            "The regulation establishes comprehensive obligations across the "
            "AI lifecycle, backed by market surveillance authorities."
        )
        assert score < GAP_ASSERTION_THRESHOLD

    def test_reconciliation_is_not_gated_on_coverage_rules(self):
        """It used to sit inside `if coverage_rules:`, which the winning path
        clears — so the guard existed but never ran on a real verdict."""
        source = SRC.read_text()
        block = source[source.index("Covered verdicts never ship under gap prose") :]
        block = block[: block.index("gap_detected = coverage")]
        # Comments in this block explain the old gating on purpose, so strip
        # them: the assertion is about what executes, not what is documented.
        code = "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))
        assert "coverage_rules" not in code, (
            "The Covered/reason_flagged reconciliation must not depend on "
            "coverage_rules — the evidence-profile path clears it before "
            "reaching here, which is how the contradiction shipped."
        )


class TestTheModelNeverSetsTheVerdict:
    """The model's own coverage label is telemetry, never the verdict.

    A fallback used to run when no evidence profile existed: it took the
    model's label and passed it through a keyword ladder that could RAISE it,
    to Covered on mechanisms the model itself reported. Both halves are gone —
    a profile that scored nothing is a computed Missing, and a profile that
    could not be computed leaves the dimension unassessed.
    """

    def _finish_source(self):
        source = SRC.read_text()
        start = source.index("def _finish_dimension_combined")
        return source[start : source.index("\n    def ", start + 10)]

    def test_the_models_label_is_only_ever_compared_not_assigned(self):
        body = self._finish_source()
        assert "coverage = model_coverage" not in body
        assert 'determined["coverage_label"]' in body
        assert "validate_coverage_deterministic" not in SRC.read_text()

    def test_a_missing_profile_refuses_before_the_model_is_called(self):
        source = SRC.read_text()
        start = source.index("def _prepare_dimension_combined")
        prepare = source[start : source.index("build_module1_2_combined_prompt", start)]
        assert "if determined is None:" in prepare and "raise RuntimeError" in prepare

    def test_zero_scored_sentences_is_a_computed_missing(self):
        from src.evidence_strength import EvidenceProfile, coverage_from_profile, depth_from_profile

        empty = EvidenceProfile(dimension="Environmental Sustainability")
        assert coverage_from_profile(empty)[0] == "Missing"
        assert depth_from_profile(empty)[0] == "Unaddressed"
