"""Semantic mechanism detection: what a provision is ABOUT, not how hard it binds.

The 45-mechanism inventory was matched by literal cue strings, and that broke
on every drafting tradition that does not use our words:

    PIPL says "individual" (99x) and "personal information handler" (75x)
    where the cues expect "data subject" and "processing". Result: 1 of 7
    Privacy mechanisms detected from a statute carrying 28 binding provisions.

    Japan's Guidelines say "adopt universal design, ensure accessibility"
    where the cues expect "persons with disabilities". Result: 0 of 5.

    India writes "resource-efficient"; the cue is "resource efficien" with a
    space. Result: the study's only Missing verdict.

This is whack-a-mole with a term list, and the list can never cover every
jurisdiction's drafting. Embeddings are the right tool for exactly this
question — "are these two texts about the same thing?" — and are robust
in-domain and out (Fraunhofer, Zero-Shot Text Matching for Automated Auditing,
IEEE 2023). Zero-shot, so no labelled corpus is needed.

WHY THIS DOES NOT REPEAT THE REJECTED ALIGNMENT EXPERIMENT. That experiment
(see evidence_strength.py) used prose-to-prose cosine to judge how STRONG a
document's governance was, and it inverted: Japan's principles-voice guidance
embedded closer to framework prose than the EU AI Act's statutory phrasing,
so soft law outscored hard law. The lesson was that similarity measures how a
document is WRITTEN, not what it REQUIRES.

Here similarity is asked only what a provision is ABOUT. Force still comes
from the tier classifier, which reads modals, actors and consequences. A
sentence matched to "bias mitigation" by embedding is still scored
Aspirational if it says "should" and Enforceable if it carries a penalty.
Topic by embedding, force by rule — each tool doing what it is good at.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import structlog

logger = structlog.get_logger()

# Calibrated below, not guessed: see calibrate_threshold() and the tests.
# Deliberately high. A mechanism claimed on weak similarity is a false
# positive that inflates coverage, and coverage is already the more generous
# of the two axes.
# Floor for the per-sentence argmax. Calibrated against real provisions our
# cues miss: the weakest true match in that set is 0.580 (Japan's "information
# poverty and digital poverty" -> digital divide), so 0.55 admits every one of
# them while still rejecting text that is about nothing in the inventory.
SEMANTIC_MECHANISM_THRESHOLD = float(os.getenv("MECHANISM_SIM_THRESHOLD", "0.55"))
# OFF BY DEFAULT, on measured evidence against my own expectation.
#
# The semantic pass adds 64 mechanism matches across the seven jurisdictions.
# Auditing every one of them against the sentence that produced it, only 7
# (11%) have any topical support. The other 57 are matches like:
#
#   Kenya  -> "incident reporting" from a sentence about conformity assessment
#   China  -> "public registry"    from a sentence about disclosing user groups
#   EU     -> "e-waste lifecycle"  from a Commission evaluation timetable
#
# The per-sentence argmax forces every sentence to vote for SOMETHING, and a
# 0.55 floor is far too low to stop it.
#
# THE TRAP, AND WHY THE NUMBERS ARE NOT THE ANSWER: turning this ON IMPROVES
# the benchmark correlations (GIRAI +0.75 vs +0.68, Oxford +0.68 vs +0.50).
# It does that because spurious matches scale with document length, and
# document length correlates with state capacity, which is what GIRAI
# measures. The composite score improves while the per-dimension verdicts get
# worse — and the per-dimension verdict is the product. A policymaker asking
# "which mechanism is my policy missing?" cannot be handed a in 9-of-10
# wrong answer because it flattered a rank correlation.
#
# The idea is still right: embeddings for topic, rules for force. What is
# wrong is the decision rule. It needs a much higher floor, agreement between
# two independent signals, or a trained relevance head — not a lower bar.
SEMANTIC_MECHANISMS_ENABLED = os.getenv("SEMANTIC_MECHANISMS", "false").lower() == "true"

# One sentence per mechanism describing the governance act it names. These are
# written from the reference frameworks' own descriptions of what each
# mechanism is, NOT from any assessed document.
MECHANISM_GLOSS: dict[str, str] = {
    # Transparency
    "user disclosure": "users are told when they are interacting with an AI system, and AI-generated content is labelled",
    "decision explanation": "an explanation of an automated decision is given to the person it affects",
    "model documentation": "technical documentation of the system, its data and its design is created and kept",
    "audit trail / logging": "the system automatically records and retains logs of its operation and events",
    "public registry": "systems are entered in a public register or database that anyone can inspect",
    "capability & limitation disclosure": "the system's capabilities, limitations and intended purpose are disclosed",
    # Accountability
    "liability allocation": "responsibility and legal liability for harm caused by the system are assigned to a party",
    "grievance / redress": "affected people can complain, seek review and obtain a remedy",
    "named responsible body": "a specific authority, regulator or officer is named as responsible for oversight",
    "incident reporting": "serious incidents and malfunctions must be reported to an authority",
    "audit requirement": "the system or organisation is subject to audit, inspection or conformity assessment",
    "sanctions / penalties": "penalties, fines or sanctions apply to those who breach the obligations",
    # Privacy
    "consent": "the individual's consent is obtained before their personal information is handled",
    "data minimisation": "only the personal information necessary for the purpose is collected and kept",
    "purpose limitation": "personal information is used only for the specified purpose it was collected for",
    "anonymisation / PETs": "personal information is anonymised, de-identified, encrypted or otherwise protected",
    "data subject rights": "the individual may access, correct, delete or port their personal information",
    "privacy by design": "privacy protection is built into the system's design and default settings",
    "impact assessment": "a data protection or privacy impact assessment is carried out before processing",
    # Safety
    "risk assessment": "risks of the system are identified, analysed and evaluated before and during use",
    "pre-deployment testing": "the system is tested, validated and evaluated before it is released",
    "robustness requirement": "the system must be accurate, resilient and secure against errors and attacks",
    "incident monitoring": "the system is monitored in operation for faults, failures and harmful outcomes",
    "post-market monitoring": "the provider monitors the system after it is placed on the market",
    "human failsafe / shutdown": "a human can stop, interrupt or shut the system down safely",
    # Human Autonomy
    "human-in-the-loop": "a human takes part in or supervises the system's decision-making",
    "right to human review": "a person may demand that a human reviews an automated decision about them",
    "override capability": "a qualified person can intervene in or override the system's output",
    "prohibition of manipulation": "systems must not manipulate, deceive or exploit people's behaviour",
    "meaningful control": "people keep meaningful control and self-determination over decisions affecting them",
    # Inclusivity
    "disability accessibility": "the system is accessible to people with disabilities, using universal or accessible design",
    "demographic representation": "diverse and representative groups are included in data and in design",
    "stakeholder participation": "stakeholders, civil society and the public are consulted and take part",
    "digital divide": "underserved, rural, marginalised and digitally excluded groups are reached",
    "language / localisation": "services are provided in local languages and adapted to local context",
    # Fairness
    "bias testing": "the system is tested and examined for bias and discriminatory outcomes",
    "protected characteristics": "race, gender, ethnicity, age, religion, disability and similar attributes are protected",
    "fairness metrics": "quantitative fairness measures such as parity or disparate impact are applied",
    "non-discrimination duty": "the system must not discriminate against people or groups",
    "bias mitigation": "measures are taken to detect, prevent, correct and mitigate bias",
    # Environmental Sustainability
    "energy reporting": "energy and power consumption of the system is measured and reported",
    "carbon disclosure": "carbon emissions, greenhouse gases or the carbon footprint are disclosed",
    "compute efficiency": "computational resources are used efficiently, favouring smaller resource-efficient models",
    "e-waste / hardware lifecycle": "hardware lifecycle, electronic waste, disposal and recycling are managed",
    "green procurement / energy": "renewable, clean or green energy is used, or procurement favours it",
}


@dataclass
class MechanismMatch:
    """Which mechanisms a set of scored sentences evidences, and how.

    The only mechanism result type. There used to be two detectors returning
    two different types; production used the weaker one, and `binding_met`
    existed on only one of them.
    """

    dimension: str = ""
    present: dict[str, int] = field(default_factory=dict)  # mechanism -> max tier
    absent: list[str] = field(default_factory=list)
    matched_by: dict[str, str] = field(default_factory=dict)  # mechanism -> "cue" | "semantic"
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

        This used to open "Provides 3 of 5 governance mechanisms the reference
        frameworks expect" — a score out of a denominator, which reads as a
        pass mark and invites the reader to treat 3/5 as 60% of good
        governance. It is not a percentage of anything; the five are not
        equally weighted and nobody claims a document needs all of them.

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


@lru_cache(maxsize=1)
def _embedder():
    """The embedding service, constructed ONCE for the process.

    This was `return VectorStore().embedding_service` with no cache, so every
    call built a new store — reloading the 384-dim model and re-opening the
    persistent Chroma directory. Called per dimension per jurisdiction, it
    reloaded the model 200+ times and then deadlocked on the Chroma files at
    0% CPU. The embedder is stateless for our purposes; one is enough.
    """
    from src.vectorstore import VectorStore

    return VectorStore().embedding_service


@lru_cache(maxsize=1)
def _gloss_matrix(dimension: str):
    """Embedded mechanism glosses for one dimension. Cached for the process."""
    import numpy as np

    from src.evidence_strength import DIMENSION_MECHANISMS

    table = DIMENSION_MECHANISMS.get(dimension) or {}
    names = list(table.keys())
    if not names:
        return [], None
    texts = [MECHANISM_GLOSS.get(n, n) for n in names]
    vecs = np.array(list(_embedder().embed(texts)), dtype=float)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    return names, vecs


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


def detect_mechanisms(
    scored_sentences: Sequence[Any],
    dimension: str,
    threshold: float | None = None,
) -> MechanismMatch:
    """Cue matching first, embeddings for what the cues cannot see.

    Cues stay because they are exact and cheap, and because a literal match is
    the strongest evidence available. Embeddings only ever ADD a mechanism the
    cues missed; they never remove one and never change a tier.
    """
    import numpy as np

    from src.evidence_strength import DIMENSION_MECHANISMS

    table = DIMENSION_MECHANISMS.get(dimension)
    result = MechanismMatch()
    if not table:
        return result

    usable = [s for s in scored_sentences if not getattr(s, "excluded", "")]
    texts = [getattr(s, "text", "") for s in usable]
    tiers = [getattr(s, "tier", 0) for s in usable]

    # ── literal cues: word-anchored AND separator-tolerant ──
    # One pattern does both jobs. The previous version tried the anchored
    # pattern and then fell back to substring matching on text with spaces and
    # hyphens stripped, which bought "bias-test" at the cost of every word
    # boundary: "reliable data" matched the "liab" cue and scored a liability
    # mechanism. Generalising the separators INSIDE the cue keeps \b where it
    # belongs — "bias test" matches "bias-test" and "biastest", while "liab"
    # stays anchored and cannot match inside "reliable".
    for name, cues in table.items():
        pattern = re.compile("|".join(_cue_pattern(c) for c in cues), re.IGNORECASE)
        best: int | None = None
        for text, tier in zip(texts, tiers):
            if pattern.search(text) and (best is None or tier > best):
                best = tier
        if best is not None:
            result.present[name] = best
            result.matched_by[name] = "cue"

    if not SEMANTIC_MECHANISMS_ENABLED or not texts:
        result.absent = [n for n in table if n not in result.present]
        return result

    # ── semantic pass for the rest ──
    names, gloss = _gloss_matrix(dimension)
    missing = [n for n in names if n not in result.present]
    if missing and gloss is not None:
        try:
            sent_vecs = np.array(list(_embedder().embed(texts)), dtype=float)
            sent_vecs /= np.linalg.norm(sent_vecs, axis=1, keepdims=True) + 1e-9
            sims = sent_vecs @ gloss.T  # (sentences x mechanisms)
            thr = SEMANTIC_MECHANISM_THRESHOLD if threshold is None else threshold
            # ARGMAX PER SENTENCE, not per mechanism. Calibration showed the
            # absolute scores overlap badly across mechanisms — a consent
            # provision scores 0.870 for "consent" and 0.824 for "data subject
            # rights", so a flat cut credits both. What is reliable is that
            # the correct mechanism WINS within its own sentence (margins
            # 0.010-0.171 across the calibration set). So each sentence votes
            # once, for its single best mechanism, and only above a floor.
            missing_idx = {names.index(n) for n in missing}
            for i in range(sims.shape[0]):
                j = int(np.argmax(sims[i]))
                if j not in missing_idx:
                    continue
                score = float(sims[i][j])
                if score < thr:
                    continue
                name = names[j]
                prior = result.present.get(name)
                if prior is None or tiers[i] > prior:
                    result.present[name] = tiers[i]
                    result.matched_by[name] = "semantic"
        except Exception as exc:
            logger.warning("semantic_mechanism_match_failed", dimension=dimension, error=str(exc))

    result.absent = [n for n in table if n not in result.present]
    return result
