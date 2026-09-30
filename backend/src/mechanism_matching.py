"""Mechanism detection: which governance mechanisms a dimension's provisions name.

Each mechanism in DIMENSION_MECHANISMS (evidence_strength.py) carries a list of
literal cues. A cue matches word-anchored and separator-tolerant, so
"post-market monitoring", "post market monitoring" and "postmarket monitoring"
are one mechanism, while a short stem such as "liab" cannot match inside
"reliable".

Matching says only what a provision is ABOUT. Its force still comes from the
tier classifier, which reads modals, actors and consequences, so a sentence
matched to "bias mitigation" is Aspirational if it says "should" and
Enforceable if it carries a penalty. Cue matches are then checked by
mechanism_adjudication before they reach a verdict.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MechanismMatch:
    """Which mechanisms a set of scored sentences evidences, and how.

    The only mechanism result type.
    """

    dimension: str = ""
    present: dict[str, int] = field(default_factory=dict)  # mechanism -> max tier
    absent: list[str] = field(default_factory=list)
    # Set by mechanism_adjudication: APPLIED, UNAVAILABLE, or empty when the
    # model was never asked. A reader of `present` needs to know which.
    adjudication: str = ""

    @property
    def met(self) -> int:
        return len(self.present)

    @property
    def total(self) -> int:
        return len(self.present) + len(self.absent)

    @property
    def binding_met(self) -> int:
        """Mechanisms provided as an actual duty, not merely mentioned."""
        from src.evidence_strength import TIER_OBLIGATORY

        return sum(1 for t in self.present.values() if t >= TIER_OBLIGATORY)

    def summary(self) -> str:
        """What is missing, named, with how many instruments expect it.

        Not "provides 3 of 5 mechanisms": a score out of a denominator reads as a
        pass mark, and the mechanisms are not equally weighted.

            A named absence with its consensus behind it says the same thing
            without the arithmetic: "missing pre-deployment testing, which 35 of
            43 indexed instruments expect" is checkable, actionable, and cannot be
            misread as a grade. Salience comes from the reference corpus only —
            see framework_salience — so it measures agreement between instruments,
            never anything about this document.
        """
        if not self.total:
            return ""
        parts: list[str] = []
        ranked: list[dict] = []
        total_instruments = 0
        try:
            from src.framework_salience import framework_count, rank_absent

            ranked = rank_absent(self.dimension, list(self.absent))
            total_instruments = framework_count()
        except Exception:  # salience unavailable — fall back to bare names
            ranked = []

        if ranked and total_instruments:
            named = [
                f"{r['mechanism']} ({r['expected_by']} of {total_instruments})" for r in ranked[:3]
            ]
            parts.append("Not established: " + ", ".join(named))
        elif self.absent:
            parts.append("Not established: " + ", ".join(sorted(self.absent)[:4]))
        else:
            parts.append(
                "Every mechanism the reference instruments expect for this "
                "dimension is established in the document"
            )

        if self.binding_met:
            parts.append(
                f"{self.binding_met} of the mechanisms present "
                f"{'is' if self.binding_met == 1 else 'are'} carried by a binding duty"
            )
        elif self.met:
            parts.append("none of the mechanisms present is carried by a binding duty")
        return "; ".join(parts) + "."


# Hyphen and spacing are drafting noise, not meaning: "resource-efficient",
def _cue_pattern(cue: str) -> str:
    """A cue as a word-anchored pattern whose own separators are optional.

    "post-market monitoring" has to match "post market monitoring" and
    "postmarket monitoring", because drafters differ and PDF extraction
    differs again — but the leading \\b must survive, or short stems match
    inside longer words.
    """
    from src.evidence_strength import ocr_flexible_fragment

    tokens = [t for t in re.split(r"[\s\-]+", cue.strip()) if t]
    if not tokens:
        return r"(?!)"  # never matches
    return r"\b" + r"[\s\-]*".join(ocr_flexible_fragment(t) for t in tokens)


def detect_mechanisms(scored_sentences: Sequence[Any], dimension: str) -> MechanismMatch:
    """Each mechanism present in the scored sentences, at the highest tier found."""
    from src.evidence_strength import DIMENSION_MECHANISMS

    table = DIMENSION_MECHANISMS.get(dimension)
    result = MechanismMatch()
    if not table:
        return result

    usable = [s for s in scored_sentences if not getattr(s, "excluded", "")]
    texts = [getattr(s, "text", "") for s in usable]
    tiers = [getattr(s, "tier", 0) for s in usable]

    # Word-anchored AND separator-tolerant: "bias test" matches "bias-test"
    # and "biastest", while "liab" stays anchored and cannot match "reliable".
    for name, cues in table.items():
        pattern = re.compile("|".join(_cue_pattern(c) for c in cues), re.IGNORECASE)
        best: int | None = None
        for text, tier in zip(texts, tiers):
            if pattern.search(text) and (best is None or tier > best):
                best = tier
        if best is not None:
            result.present[name] = best

    result.absent = [n for n in table if n not in result.present]
    return result
