"""The scorer: what a provision requires, and how far a regime is built out.

The language model extracts evidence and writes prose. Nothing here asks it
anything. Every verdict is computed from counted, classified sentences, so a
stored analysis can be re-scored from its recorded evidence without spending a
single model call — which is what made it affordable to backtest seven
jurisdictions against four external references.

WHAT THIS MODULE DOES, IN ORDER

  1. Sentence function      is this text OPERATIVE at all? Recitals,
                            definitions, headings, descriptions, institutional
                            lists, consultation questions and errata create no
                            duty and are excluded before scoring.
  2. Duty classification    each provision gets a tier T0-T4 from three
                            signals: who is addressed (regulated party,
                            regulated artifact, or government), what force
                            (shall / must / be-to-infinitive / should), and
                            what consequence (penalty, fine, liability).
                            Hedges demote one tier; a voluntary instrument
                            caps everything at T1.
  3. De-duplication         overlapping chunks return the same provision
                            several times, cut at different offsets.
                            Collapsed by containment before counting.
  4. Evidence sufficiency   a NEGATIVE verdict on very thin evidence is
                            withheld rather than published.
  5. Mechanism gate         a dimension cannot be "operational" while binding
                            none of the mechanisms it requires.
  6. Aggregation            geometric mean across dimensions, so a regime with
                            a hole in it does not read like a uniformly
                            middling one. This is the reform UNDP made to the
                            Human Development Index in 2010, for the same
                            reason.

EVERY RULE HERE REPLACED ONE THAT WAS MEASURABLY WRONG. The comments name the
document and the sentence that exposed each, because those are the only
evidence that the rule is worth having.
"""

from __future__ import annotations

import collections
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.evidence_strength import (
    ASPIRATION_RE,
    AUTHORITY_VERB_RE,
    COMMITMENT_RE,
    DEONTIC_REQUIRE_RE,
    GOV_BODY_RE,
    HEDGE_RE,
    IMPOSITION_RE,
    LEGAL_INSTRUMENT_RE,
    OBLIGATION_RE,
    REGULATED_PARTY_RE,
    TIER_ASPIRATIONAL,
    TIER_ASSIGNED,
    TIER_ENFORCEABLE,
    TIER_INTENTIONAL,
    TIER_OBLIGATORY,
    ScoredSentence,
    _norm,
    _words,
    is_structural_noise,
    is_third_party_attribution,
)

logger = structlog.get_logger()

# ── The split that v1 did not make ───────────────────────────────────────
#
# CONSEQUENCE: something that happens TO a party that does not comply. This
# is what makes a duty enforceable rather than merely supervised.
CONSEQUENCE_RE = _words(
    "penalty",
    "penalties",
    "fine",
    "fines",
    "sanction",
    "sanctions",
    "liable",
    "liability",
    "revocation",
    "revoke",
    "suspend",
    "suspension",
    "corrective action",
    "compensation",
    "damages",
    "prosecut*",
    "punish*",          # standard in civil-law translation; absent from
                        # Anglo drafting and therefore missed until China
    "offence",
    "offense",
    "imprisonment",
    "injunction",
    "non-compliance",
    "noncompliance",
    "enforcement",
    "enforce",
    "enforced",
    "enforceable",
    # Administrative sanctions as civil-law translation renders them. PIPL
    # Chapter VII imposes all of its remedies in these words and none of the
    # ones above, so the law with the heaviest data-protection penalties in
    # the corpus contributed exactly one enforceable provision out of 182.
    "confiscat*",
    "criminal responsibility",
    "circulate criticism",
)

# "order corrections" / "give warnings" are the two commonest PIPL remedies and
# both are phrases, not words. Kept out of CONSEQUENCE_RE's word list so the
# generic senses ("an early warning system", "in order to") cannot match.
ADMIN_SANCTION_RE = re.compile(
    r"\border\w*\s+(?:that\s+)?correction"
    r"|\border\w*\s+(?:\w+\s+){0,3}?to\s+(?:make\s+)?correct"
    r"|\b(?:give|gives|given|giving|issue|issues|issued)\s+(?:a\s+)?warnings?\b",
    re.IGNORECASE,
)

# OVERSIGHT: an activity someone performs. Real governance, and in v1 it was
# scored identically to a penalty. An organisation asked to audit itself is
# not thereby subject to enforcement — Egypt's guidelines describe their own
# audit instrument as "a comprehensive Self Assessment checklist".
OVERSIGHT_RE = _words(
    "audit",
    "audits",
    "audited",
    "auditing",
    "inspection",
    "inspections",
    "inspect",
    "investigate",
    "investigation",
    "supervis*",
    "conformity assessment",
    "certification",
    "certified",
    "accreditation",
    "redress",
    "grievance",
    "complaint",
    "complaints",
    "appeal",
    "remedy",
    "remedies",
    "monitoring",
    "breach",
)

# Oversight is only FORCE when the regulated party is its object. "Providers
# are subject to supervision by the Authority" imposes something; "Organizations
# are investing in vendor risk management and continuous monitoring" describes
# a market. Both reached Obligatory, because the ladder asked whether the word
# appeared rather than who was on the receiving end. Across the corpus 46
# provisions — 8% of all binding evidence — reached that tier on oversight with
# no duty of any kind in the sentence, and 45 of the 46 were mentions.
SUBJECTION_RE = re.compile(
    r"\b(?:is|are|shall\s+be|must\s+be|will\s+be|being|been)\s+subject(?:ed)?\s+to\b"
    r"|\b(?:supervis|monitor|audit|inspect|investigat|overse|certifi|accredit)\w*\s+by\s+"
    r"(?:the\s+|a\s+|an\s+)?[A-Za-z]"
    r"|\bunder\s+the\s+(?:supervision|oversight|inspection|control|authority)\s+of\b"
    r"|\bsubject\s+to\s+(?:the\s+)?(?:supervision|oversight|inspection|audit|investigation|"
    r"certification|accreditation|approval|review|sanction|penalt)\w*",
    re.IGNORECASE,
)

# "law enforcement" is policing. It is not enforcement OF THIS INSTRUMENT, and
# treating it as such is what lifted Kenya's Transparency verdict in v1 on the
# strength of a sentence about strengthening the police.
POLICING_RE = re.compile(r"\blaw[\s\-]+enforcement\b", re.IGNORECASE)


def strip_policing(sentence: str) -> str:
    """Mask the policing sense before any enforcement test runs."""
    return POLICING_RE.sub(" ", sentence or "")


def _classify_base(
    sentence: str,
    dimension: str = "",
    own_jurisdiction: str = "",
    document_is_nonbinding: bool = False,
    document_is_unenforced: bool = False,
) -> ScoredSentence:
    """v1's ladder with the enforcement split applied.

    Deliberately a copy of v1's branch structure rather than a refactor of it.
    v1 must keep behaving exactly as it did while the two are being compared,
    and a shared helper that both call would make every future edit a change
    to both models at once.
    """
    s = " ".join((sentence or "").split())
    if not s:
        return ScoredSentence(s, TIER_ASPIRATIONAL, "none", False, excluded="empty")
    if is_structural_noise(s):
        return ScoredSentence(s, TIER_ASPIRATIONAL, "none", False, excluded="structural")
    if is_third_party_attribution(s, own_jurisdiction):
        return ScoredSentence(s, TIER_ASPIRATIONAL, "none", False, excluded="third_party")

    probe = strip_policing(s)

    has_regulated = bool(REGULATED_PARTY_RE.search(probe))
    has_gov = bool(GOV_BODY_RE.search(probe))
    bearer = "regulated" if has_regulated else ("government" if has_gov else "none")

    has_consequence = bool(CONSEQUENCE_RE.search(probe)) or bool(
        ADMIN_SANCTION_RE.search(probe)
    )
    has_oversight = bool(OVERSIGHT_RE.search(probe))
    has_subjection = bool(SUBJECTION_RE.search(probe))
    has_obligation = (
        bool(OBLIGATION_RE.search(probe))
        or bool(IMPOSITION_RE.search(probe))
        or bool(DEONTIC_REQUIRE_RE.search(probe))
    )
    has_commitment = bool(COMMITMENT_RE.search(probe))
    # "order corrections" and "give warnings" are exercises of administrative
    # power, not just their outcomes — a bare "order" stays excluded.
    has_authority = bool(AUTHORITY_VERB_RE.search(probe)) or bool(
        ADMIN_SANCTION_RE.search(probe)
    )
    hedged = bool(HEDGE_RE.search(probe))

    tier = TIER_ASPIRATIONAL
    enforcement_credit = False

    if has_gov and has_authority and has_consequence:
        # A body vested with a real power AND a consequence behind it.
        tier = TIER_ENFORCEABLE
        enforcement_credit = True
    elif has_regulated and has_obligation:
        # A duty on an external actor. Enforceable only with a consequence;
        # oversight alone leaves it Obligatory, which is what it is.
        tier = TIER_ENFORCEABLE if has_consequence else TIER_OBLIGATORY
        enforcement_credit = has_consequence
    elif has_gov and has_authority:
        tier = TIER_OBLIGATORY
    elif has_gov and (has_commitment or has_obligation):
        tier = TIER_ASSIGNED
    elif has_regulated and (has_consequence or has_subjection):
        tier = TIER_OBLIGATORY
        enforcement_credit = has_consequence
    elif LEGAL_INSTRUMENT_RE.search(probe) and (
        has_obligation or has_consequence or has_oversight
    ):
        tier = TIER_ASSIGNED
    elif has_commitment:
        tier = TIER_INTENTIONAL
    elif has_regulated and ASPIRATION_RE.search(probe):
        tier = TIER_INTENTIONAL

    if hedged and tier > TIER_INTENTIONAL:
        tier -= 1
        if tier < TIER_ENFORCEABLE:
            enforcement_credit = False

    if document_is_nonbinding and tier > TIER_INTENTIONAL:
        tier = TIER_INTENTIONAL
        enforcement_credit = False

    # A document that establishes no consequence for non-compliance ANYWHERE
    # in its text cannot make anything obligatory, whatever its individual
    # sentences say. It can still delegate — "the Ministry shall establish a
    # working group" is real assignment — so the ceiling is Assigned, not
    # Intentional. This is the only handle on an instrument that is voluntary
    # in substance while never saying so: Egypt's National Guidelines contain
    # no self-description at all, and were scoring Operationalized on six of
    # eight dimensions on the strength of the word "must".
    if document_is_unenforced and tier > TIER_ASSIGNED:
        tier = TIER_ASSIGNED
        enforcement_credit = False

    return ScoredSentence(s, tier, bearer, enforcement_credit)


# How many enforcement signals establish a regime. v1 used a flat 3, which is
# LENGTH-BIASED: it was calibrated on the EU AI Act (2,664 sentences) and the
# APPI (604), and a short statute cannot reach it however clearly it binds.
# China's Interim Measures are 63 sentences with one penalties article; its
# Deep Synthesis Provisions 70. Under a flat 3, no short instrument anywhere
# can establish a regime — a defect invisible across five jurisdictions whose
# binding instruments all happened to be long.
#
# The guard's purpose is to reject a passing preamble mention, and that scales
# with how much document there is to pass through. One signal in 63 sentences
# is not incidental; one in 7,704 might be.
ENFORCEMENT_SIGNALS_PER_SENTENCES = 200


def required_enforcement_signals(n_sentences: int) -> int:
    """Signals needed to call it a regime, scaled to document length."""
    return max(1, min(3, round(n_sentences / ENFORCEMENT_SIGNALS_PER_SENTENCES)))


def detect_enforcement_regime(sample_texts: Iterable[str], min_signals: int | None = None) -> bool:
    """Does this DOCUMENT establish machinery with a consequence attached?

    Same shape as v1, but the sentences that qualify must now reach the top
    tier under the consequence rule. Measured on the corpus: Egypt's
    guidelines return True in v1 on ten sentences carrying no penalty word at
    all, and False here.
    """
    from src.evidence_strength import _split_sentences_for_scoring

    texts = [t for t in sample_texts if t]
    sentences = [sent for t in texts for sent in _split_sentences_for_scoring(t)]
    needed = min_signals if min_signals is not None else required_enforcement_signals(len(sentences))
    signals = 0
    for t in texts:
        for sent in _split_sentences_for_scoring(t):
            # v5's classifier, deliberately. The regime detector and the
            # profile must agree on what enforcement IS, or a document can
            # carry agentless penalty articles ("criminal liability shall be
            # pursued") that the profile recognises and the regime does not.
            # Found on China, where all four instruments carry real penalties
            # and none registered a regime.
            if classify_provision(sent).tier >= TIER_ENFORCEABLE:
                signals += 1
                if signals >= needed:
                    return True
    return False


# ── Aggregation across the eight dimensions ──────────────────────────────
#
# The stage scores are v1's and are deliberately unchanged: the ladder was
# validated, and changing the scale and the aggregation in the same step would
# make the comparison uninterpretable.
DEPTH_STAGE_SCORE_V2 = {
    "Unaddressed": 0.0,
    "Emerging": 50.0,
    "Delegated": 65.0,
    "Operationalized": 78.0,
    "Institutionalized": 100.0,
}

# A geometric mean containing a zero is zero, which would collapse any
# jurisdiction with one Unaddressed dimension to an index of 0 and destroy all
# information about the other seven. HDI has the same problem and solves it
# with goalposts — a minimum above zero. GEOMETRIC_FLOOR is that goalpost: a
# document that was assessed and found silent on a dimension still sits on the
# scale, it just sits at the bottom of it. The value is small enough that an
# Unaddressed dimension dominates the index, which is the intended behaviour.
GEOMETRIC_FLOOR = 5.0


def arithmetic_index(stage_scores: Sequence[float]) -> float:
    """v1's aggregation. Fully compensatory: a 100 offsets a 0 exactly."""
    if not stage_scores:
        return 0.0
    return round(sum(stage_scores) / len(stage_scores), 1)


def geometric_index(stage_scores: Sequence[float], floor: float = GEOMETRIC_FLOOR) -> float:
    """Imperfectly compensatory (OECD/JRC Handbook; UNDP HDI since 2010).

    Rewards a regime that governs every dimension somewhat over one that
    governs most dimensions superbly and one not at all.
    """
    if not stage_scores:
        return 0.0
    vals = [max(float(s), floor) for s in stage_scores]
    return round(math.exp(sum(math.log(v) for v in vals) / len(vals)), 1)


def penalised_index(stage_scores: Sequence[float]) -> float:
    """Adjusted Mazziotta-Pareto: the mean, minus a penalty for imbalance.

        M - (S^2 / M)   where M is the mean and S the standard deviation

    Included as the third aggregation because it handles a genuine zero
    without a floor — unlike the geometric mean it needs no goalpost, so it
    acts as a check that the geometric result is not an artefact of the floor
    we chose.
    """
    if not stage_scores:
        return 0.0
    n = len(stage_scores)
    mean = sum(stage_scores) / n
    if mean <= 0:
        return 0.0
    var = sum((s - mean) ** 2 for s in stage_scores) / n
    return round(max(0.0, mean - var / mean), 1)


@dataclass
class DepthAggregation:
    """All three aggregations plus the spread that separates them.

    Reported together on purpose. The OECD/JRC Handbook asks that a composite
    indicator be shown robust to its own aggregation choice; publishing one
    number and calling it the answer is what the Handbook warns against.
    """

    arithmetic: float
    geometric: float
    penalised: float
    imbalance: float
    stages: dict[str, str] = field(default_factory=dict)

    @property
    def headline(self) -> float:
        return self.geometric

    def as_dict(self) -> dict[str, Any]:
        return {
            "implementation_depth_index": self.headline,
            "depth_arithmetic": self.arithmetic,
            "depth_geometric": self.geometric,
            "depth_penalised": self.penalised,
            "depth_imbalance": self.imbalance,
        }


def aggregate_depth(stages: dict[str, str]) -> DepthAggregation:
    """Aggregate per-dimension stage labels into the depth index.

    `stages` maps dimension name → stage label, for ASSESSED dimensions only.
    A dimension that was never assessed is absent rather than zero: scoring a
    dimension the pipeline could not evaluate as "absent governance" would
    report a retrieval failure as a policy finding.
    """
    scores = [DEPTH_STAGE_SCORE_V2.get(v, 0.0) for v in stages.values()]
    if not scores:
        return DepthAggregation(0.0, 0.0, 0.0, 0.0, dict(stages))
    mean = sum(scores) / len(scores)
    sd = (sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5
    return DepthAggregation(
        arithmetic=arithmetic_index(scores),
        geometric=geometric_index(scores),
        penalised=penalised_index(scores),
        imbalance=round(sd, 1),
        stages=dict(stages),
    )


# ── Corpus completeness ──────────────────────────────────────────────────
#
# The failure that v1 cannot see. India governs AI through sectoral regulators
# by stated policy, so the two documents supplied are a deliberately small
# slice of the regime — and v1 reports a number for it with no caveat and an
# undiminished confidence score. A score computed from an incomplete corpus is
# not wrong, but presenting it as a jurisdiction's depth is.
#
# This does NOT adjust the score. It cannot: we have no way to grade an
# instrument we were not given. It qualifies the score, which is the honest
# thing available.
_INSTRUMENT_REF_RE = re.compile(
    r"\b("
    r"(?:the\s+)?[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,5}\s+"
    r"(?:Act|Bill|Law|Regulation|Code|Ordinance|Decree|Directive)"
    r"(?:\s*,?\s*(?:No\.\s*\d+\s*(?:of\s*)?)?\d{4})?"
    r")\b"
)
_REGULATOR_REF_RE = re.compile(
    r"\b("
    r"sectoral\s+regulators?|"
    r"Reserve\s+Bank[A-Za-z\s]{0,20}|"
    r"Securities\s+and\s+Exchange\s+Board[A-Za-z\s]{0,20}|"
    r"[A-Z][A-Za-z]*\s+Regulatory\s+Authority|"
    r"Data\s+Protection\s+(?:Authority|Board|Commission(?:er)?)"
    r")\b"
)
_SELF_REF_STOP = re.compile(r"\b(this|the present)\s+(act|bill|law|regulation)\b", re.IGNORECASE)


def referenced_instruments(text: str) -> set[str]:
    """Named legal instruments and regulators a document points at."""
    if not text:
        return set()
    found: set[str] = set()
    for m in _INSTRUMENT_REF_RE.finditer(text):
        name = " ".join(m.group(1).split())
        if _SELF_REF_STOP.search(name) or len(name) < 8:
            continue
        found.add(name)
    for m in _REGULATOR_REF_RE.finditer(text):
        found.add(" ".join(m.group(1).split()))
    return found


def corpus_completeness(
    document_texts: dict[str, str],
) -> dict[str, Any]:
    """Which instruments the corpus points at but does not contain.

    `document_texts` maps supplied document name → its full text.
    """
    supplied = " ".join(document_texts.keys()).lower()
    referenced: set[str] = set()
    for text in document_texts.values():
        referenced |= referenced_instruments(text)

    missing = sorted(
        r for r in referenced
        if not any(tok in supplied for tok in _norm(r).split() if len(tok) > 4)
    )
    return {
        "documents_supplied": len(document_texts),
        "instruments_referenced_not_supplied": missing[:12],
        "referenced_not_supplied_count": len(missing),
        # A single guidance document that points at many instruments it does
        # not contain is the distributed-regime signature.
        "corpus_likely_incomplete": len(missing) >= 3,
    }


# ── Profile building, v2 ─────────────────────────────────────────────────


def _build_profile_base(
    sentences: Iterable[str],
    dimension: str = "",
    own_jurisdiction: str = "",
    document_is_nonbinding: bool = False,
):
    """v1's profile, built with v2's classifier.

    The counters, their cumulative semantics and the verdict functions that
    read them are v1's and unchanged — only what puts a sentence at the top
    tier is different.
    """
    from src.evidence_strength import EvidenceProfile

    profile = EvidenceProfile(dimension=dimension)
    # Overlapping chunk windows deliver the same provision several times; see
    # dedupe_sentences. Counting it once is the difference between "twelve
    # binding provisions" and the four that actually exist.
    for raw in dedupe_sentences(sentences):
        scored = _classify_base(
            raw,
            dimension=dimension,
            own_jurisdiction=own_jurisdiction,
            document_is_nonbinding=document_is_nonbinding,
        )
        profile.sentences.append(scored)
        if scored.excluded == "foreign":
            profile.n_excluded_foreign += 1
            continue
        if scored.excluded == "structural":
            profile.n_excluded_structural += 1
            continue
        profile.n_scored += 1
        profile.tier_counts[scored.tier] = profile.tier_counts.get(scored.tier, 0) + 1
        profile.max_tier = max(profile.max_tier, scored.tier)
        if scored.tier >= TIER_ENFORCEABLE:
            profile.n_enforceable += 1
        if scored.tier >= TIER_OBLIGATORY:
            profile.n_binding += 1
        if scored.tier >= TIER_ASSIGNED:
            profile.n_institutional += 1
        if scored.tier >= TIER_INTENTIONAL:
            profile.n_commitment += 1
    return profile


def dimension_enforcement_backing(
    sentences_by_document: dict[str, list[str]],
    documents_with_regime: set[str],
    dimension: str = "",
    own_jurisdiction: str = "",
) -> bool:
    """Can this dimension claim the document's own enforcement machinery?

    Only if a document that BOTH has an enforcement regime AND supplies at
    least one binding sentence to this dimension. v1 asked only the first
    question, and asked it of the whole workspace, so in Japan's three-document
    run the 2003 privacy statute's penalties backed Transparency and Fairness —
    dimensions the APPI does not govern.
    """
    for doc, sents in sentences_by_document.items():
        if doc not in documents_with_regime:
            continue
        for s in sents:
            if _classify_base(
                s, dimension=dimension, own_jurisdiction=own_jurisdiction
            ).tier >= TIER_OBLIGATORY:
                return True
    return False


# ── v3: evidence sufficiency, and why geometric aggregation needs it ─────
#
# v2 fixed WHAT counts as enforcement. It did not fix a deeper problem: the
# scorer could not tell "we read this dimension carefully and found no duty"
# from "we barely found anything to read".
#
# Measured across the 40 dimension-by-jurisdiction cells in the study set:
#
#     EU   Environmental Sustainability   17 scored sentences, 0 binding
#     India Environmental Sustainability   2 scored sentences, 0 binding
#
# Both produced the verdict Unaddressed. Only one of them is a finding about
# the document. India's whole corpus is 48 chunks against the EU's 337, so its
# thinnest dimensions are verdicts issued on almost nothing, and they dragged
# India to last place.
#
# THE THRESHOLD IS DERIVED, NOT CHOSEN. Over the cells that do carry a duty,
# binding sentences are 18.2% of scored sentences. If a dimension is governed
# at that rate, the chance of reading k sentences and seeing no duty at all is
# 0.818^k. Requiring that to fall below 20% gives k >= 8:
#
#     0.818^8 = 0.19
#
# Requiring that to fall at or below 20% gives k = 9, the smallest integer
# that qualifies:
#
#     0.818^8 = 0.201   (just misses)
#     0.818^9 = 0.164
#
# So below nine scored sentences, "no duty found" carries less than 80%
# confidence and should not be published as a governance verdict. Above it,
# silence is evidence.
#
# CAUTION, and it is a real one. That insensitivity held before de-duplication
# removed 16% of scored sentences. With the counts corrected, k=9 withholds
# FOUR cells rather than three, and the margin to the next cell is thin. The
# threshold is no longer comfortably categorical on this corpus, which is an
# argument for re-deriving it against documents outside the study set before
# anyone relies on it.
EVIDENCE_BASE_RATE = 0.182
EVIDENCE_CONFIDENCE = 0.80
MIN_SCORED_FOR_ABSENCE = 9

# A dimension that DOES show a duty needs no such protection — the finding is
# positive, and a positive finding on thin evidence is still a finding.


def evidence_is_sufficient(n_scored: int, n_binding: int) -> bool:
    """Can a negative verdict on this dimension be published?

    Positive findings always can. Negative ones need enough sentences to have
    had a fair chance of revealing a duty.
    """
    if n_binding > 0:
        return True
    return n_scored >= MIN_SCORED_FOR_ABSENCE


def aggregate_depth_gated(
    stages: dict[str, str],
    sufficiency: dict[str, bool] | None = None,
) -> DepthAggregation:
    """Aggregate, excluding dimensions whose verdict the evidence cannot carry.

    This is what makes geometric aggregation safe to use. The geometric mean's
    virtue is that a weak dimension pulls the whole index down; its danger is
    that it does the same for a MEASUREMENT ERROR, and ours cluster in exactly
    the low tail — a vocabulary gap produces a false Unaddressed, never a false
    Institutionalized. Excluding the cells we cannot stand behind removes the
    error before it is amplified, rather than damping the amplifier.

    An excluded dimension is NOT scored zero and NOT silently dropped: the
    count is reported so a reader can see the index rests on six dimensions
    rather than eight.
    """
    if sufficiency is None:
        return aggregate_depth(stages)
    kept = {d: s for d, s in stages.items() if sufficiency.get(d, True)}
    agg = aggregate_depth(kept)
    agg.stages = dict(stages)
    return agg


def depth_report(
    stages: dict[str, str],
    sufficiency: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """The full v3 depth block, including what it could not assess."""
    agg = aggregate_depth_gated(stages, sufficiency)
    insufficient = sorted(d for d, ok in (sufficiency or {}).items() if not ok)
    out = agg.as_dict()
    out.update(
        {
            "dimensions_assessed": len(stages) - len(insufficient),
            "dimensions_insufficient_evidence": insufficient,
            # More than two dimensions unassessable means the corpus, not the
            # country, is what the index is really measuring.
            "assessment_evidence_limited": len(insufficient) > 2,
        }
    )
    return out


# ── Duplicate provisions ─────────────────────────────────────────────────
#
# Found by reading the sentences behind a verdict rather than the verdict.
# Egypt's Transparency reported twelve binding provisions; four of them were
# ONE sentence — "Ensure that transparency and Explainability requirements are
# jointly validated by Provider/Developer and Business Units (BU) during
# design" — recurring with different internal whitespace.
#
# The cause is chunking, not scoring. Chunk windows overlap by design so a
# provision is never split across a boundary, and the scoring pool therefore
# contains the same sentence once per window that covers it. Nothing
# downstream removed it, so every counter it feeds was inflated.
#
# Measured over the whole study set: 590 of 3,636 scored sentences are
# duplicates — 16%. The effect on VERDICTS is small, because the force bar is
# a low threshold and a dimension with a duty usually has several; exactly one
# of forty cells flips. The effect on the NUMBERS is not small, and those
# numbers are quoted in the generated narrative ("imposes 73 binding
# requirements here"), so they were wrong by about a fifth wherever they
# appeared.
#
# Normalising on alphanumerics only is deliberate. The duplicates differ by
# whitespace and occasionally by a stray hyphen from PDF extraction, never by
# wording — two genuinely different provisions do not collide under this key.
_DEDUPE_KEY_RE = re.compile(r"[^a-z0-9]+")


def dedupe_sentences(sentences: Iterable[str]) -> list[str]:
    """First occurrence of each distinct provision, in order.

    Collapses by CONTAINMENT, not equality. Overlapping chunks return the same
    provision cut at different offsets — "...fostering sustainable growth. The
    development of..." and "...sustainable growth. The development of..." are
    one sentence — so an exact key treats them as distinct and counts the
    provision once per overlapping chunk. That inflated a single Kenyan
    sentence into "5 binding provisions". Containment catches truncation at
    either end.

    Quadratic in the number of sentences, which is fine: the largest dimension
    pool in the corpus is a few hundred, and correctness here feeds every
    counter downstream.
    """
    accepted: list[str] = []
    out: list[str] = []
    for s in sentences:
        key = _DEDUPE_KEY_RE.sub("", (s or "").lower())
        if not key or any(key in k or k in key for k in accepted):
            continue
        accepted.append(key)
        out.append(s)
    return out


# ══ v4 ═══════════════════════════════════════════════════════════════════
#
# Three changes, each found by reading the sentences behind a verdict rather
# than the verdict. See docs/ENGINEERING-NOTES.md for the 40-cell validation that produced
# them.
#
# ── (A) Sentence function: is this text OPERATIVE at all? ────────────────
#
# The ladder correctly tiers whatever it is handed. It was being handed the
# wrong sentences. Six kinds of non-operative text scored as duties, and the
# largest by far is recitals: 110 of the European Union's 184 binding
# sentences (60%) come from the AI Act's preamble, which under EU law has no
# binding force and exists to aid interpretation. EU Inclusivity's entire
# Covered/Operationalized verdict rested on two sentences, both recitals.
#
# This gate runs BEFORE tier classification, in the same spirit as the
# existing structural-noise and third-party-attribution exclusions.

# "X means Y", "X refers to Y" — defines a term, requires nothing of anyone.
_DEFINITION_RE = re.compile(
    r"\b(means|shall mean|refers to|is defined as|are defined as|"
    r"for the purposes of this|is understood as)\b",
    re.IGNORECASE,
)

# A body's own composition, tenure and procedure. These carry real "shall"s —
# "In appointing members, the Cabinet Secretary shall ensure gender balance" —
# but they govern the regulator, not AI. Kenya's Inclusivity verdict rested on
# exactly this.
_HOUSEKEEPING_RE = re.compile(
    r"\b(appoint\w*|re-?appoint\w*|tenure|term of office|vacat\w+|resign\w*|"
    r"quorum|remunerat\w+|allowance[sd]?|chairperson|vice-chairperson|"
    r"deputy chairperson|secretariat|annual accounts|financial year|"
    r"convene|convened|meetings? of the (?:board|committee|council|authority))\b",
    re.IGNORECASE,
)

# Present-tense description of the world rather than an instruction to it:
# "Organizations are investing in vendor risk management", "These solutions
# deliver transparency across enterprise LLM deployments".
_DESCRIPTIVE_RE = re.compile(
    r"^(?:[A-Z][\w\s,'’\-()]{0,70}?)\b("
    r"are (?:investing|adopting|increasingly|currently|now|already|using|"
    r"exploring|developing|building|working)|"
    r"is (?:increasingly|currently|now|already|expected to grow|projected)|"
    r"deliver|delivers|provides organisations|offers|enables organisations|"
    r"has (?:grown|increased|emerged)|have (?:grown|increased|emerged)"
    r")\b",
    re.IGNORECASE,
)

# Headings: short, often parenthesised or numbered, with no finite verb.
_HEADING_RE = re.compile(r"^\(?[A-Z][A-Za-z ,/&\-]{3,70}\)?$")
_MODAL_ANY_RE = re.compile(
    r"\b(shall|must|should|will|may|is|are|was|were|has|have|can|could|would)\b",
    re.IGNORECASE,
)


# A consultation document asks what the law SHOULD be. Found on the UK white
# paper, a genre none of the first five jurisdictions contained: its
# "binding duties" included "Are there other measures we could require of
# organisations to improve transparency for AI?" (a consultation question),
# "Text should read: 1: Do you agree that requiring organisations..." (an
# erratum correcting a consultation question), and "We recognise the need to
# consider which actors should be responsible and liable" (deliberation).
#
# Measured: 10% of the UK's binding provisions were of this kind, against
# 0-2% for the statute-based jurisdictions. The vocabulary of obligation —
# require, liable, responsible — is dense in these sentences and none of them
# imposes anything.
# An enumeration of which bodies exist is not a duty. India's Safety verdict
# was Institutionalized on two sentences, both this one fragment:
#
#   "Enabled by coordinated institutional leadership - including the Ministry
#    of Electronics and Information Technology as the nodal ministry, the AI
#    Governance Group, the Technology & Policy Expert Committee for expert
#    advisory, the AI Safety Institute for technical validation..."
#
# India has no AI safety law. The sentence lists org charts; it creates
# nothing. The signature is a run of named bodies joined by apposition with no
# modal governing them.
# Counting the bodies is more robust than looking for a lead-in phrase. The
# lead-in ("including...") frequently sits in a different chunk from the list
# it introduces — India's fragment literally begins mid-word, "ology & Policy
# Expert Committee for expert advisory, the AI Safety Institute for technical
# validation... and sectoral regulators for domain-specific enforcement" —
# because chunk boundaries cut sentences. A run of named bodies with nothing
# commanding them is an org chart however it was cut.
_INSTITUTION_NOUN_RE = re.compile(
    r"\b(?:Ministry|Ministries|Department|Authority|Authorities|Commission|"
    r"Committee|Council|Institute|Agency|Agencies|Board|Bureau|Directorate|"
    r"Secretariat|regulators?)\b",
    re.IGNORECASE,
)
_INSTITUTIONS_FOR_LIST = 2
_GOVERNING_MODAL_RE = re.compile(r"\b(shall|must|is required to|are required to)\b", re.IGNORECASE)


_INTERROGATIVE_RE = re.compile(
    r"\?\s*$|^\s*(?:Q\s*)?\d{1,2}\s*[:.]\s*(?:Do|Are|Is|What|Which|How|Should|Would)\b",
    re.IGNORECASE,
)
_ERRATUM_RE = re.compile(
    r"^\s*(?:text should read|correction|erratum|amended to read|"
    r"this (?:page|text) (?:has been|was) (?:updated|corrected))\b",
    re.IGNORECASE,
)
# First-person deliberation by the document's own author about what to do.
_DELIBERATIVE_RE = re.compile(
    r"\b(?:we (?:recognise|acknowledge|are considering|will consider|"
    r"propose to consider|welcome views|invite views|are seeking views)|"
    r"respondents (?:said|noted|suggested)|this consultation (?:seeks|asks))\b",
    re.IGNORECASE,
)


def sentence_function(sentence: str, is_recital: bool = False) -> str:
    """Why this sentence exists. "operative" means it can create a duty.

    Returns one of: recital | definition | heading | descriptive |
    housekeeping | consultative | institutional_list | operative.
    """
    s = " ".join((sentence or "").split())
    if not s:
        return "heading"
    if is_recital:
        return "recital"
    if _INTERROGATIVE_RE.search(s) or _ERRATUM_RE.match(s) or _DELIBERATIVE_RE.search(s):
        return "consultative"
    if (
        len(_INSTITUTION_NOUN_RE.findall(s)) >= _INSTITUTIONS_FOR_LIST
        and not _GOVERNING_MODAL_RE.search(s)
    ):
        # Names bodies, commands nobody.
        return "institutional_list"
    if _HEADING_RE.match(s) and not _MODAL_ANY_RE.search(s):
        return "heading"
    if _DEFINITION_RE.search(s):
        return "definition"
    if _HOUSEKEEPING_RE.search(s):
        return "housekeeping"
    if _DESCRIPTIVE_RE.search(s) and not re.search(r"\b(shall|must)\b", s, re.IGNORECASE):
        return "descriptive"
    return "operative"


def recital_boundary(chunks: Sequence[dict[str, Any]]) -> int | None:
    """Page on which a regulation's operative articles begin, or None.

    Recitals in an EU-style instrument sit before "Article 1". Everything on an
    earlier page is preamble. Documents with no such marker return None and are
    left entirely alone, so this cannot misfire on a strategy or a guideline.
    """
    first = None
    for c in chunks:
        text = (c.get("text") or "")
        if re.search(
            r"\bArticle\s+1\b.{0,80}?\b(Subject matter|Scope|Purpose)\b", text, re.I | re.S
        ):
            md = c.get("metadata") or {}
            pg = md.get("page_number") or c.get("page_number")
            if pg and (first is None or pg < first):
                first = pg
    return first


def is_operative(sentence: str, is_recital: bool = False) -> bool:
    return sentence_function(sentence, is_recital) == "operative"


# ── (B) Structural relevance: admit duties the vocabulary gate cannot see ─
#
# The core-term gate admits 3,046 sentences and rejects 57,066. Among the
# rejects are real duties it has no word for — the EU AI Act's Article 12
# logging obligation is missed because "logging" is not a Transparency core
# term, and Kenya's "shall submit annual compliance reports to the
# Commissioner" because "compliance report" is not one either.
#
# Admitting everything with a modal is catastrophic: Japan's APPI has ~200
# "must" clauses and they flood all eight dimensions equally (measured: 120 to
# 140 would-bind sentences per dimension, including dimensions APPI does not
# govern). So admission is conditioned on STRUCTURE — the sentence must sit in
# a chunk retrieval ranked highly FOR THIS DIMENSION, name a regulated party,
# and carry a hard modal.
#
# That still leaks generic provisions. Kenya's "programmes under subsection
# (1) shall be conducted at national and county levels" qualifies for six
# dimensions at once. The specificity guard below is the filter: a provision
# admitted to more than MAX_DIMENSIONS dimensions is by construction not
# specific to any of them.
#
# THE VALUE IS 3, AND IT WAS NOT CHOSEN TO MAXIMISE A SCORE. Swept over the
# study set against both benchmark families (capacity indices A, binding-force
# references B):
#
#     MAX_DIMS   1      2      3      4      8
#     A       +0.90  +1.00  +0.80  +0.80  +0.30
#     B       +0.65  +0.45  +0.80  +0.80  +0.75
#     mean    +0.77  +0.72  +0.80  +0.80  +0.53
#
# 2 scores a perfect +1.00 against GIRAI and Oxford and we are NOT using it:
# it buys that by pushing Kenya to last, which contradicts the legal sources
# on a statute carrying criminal penalties. A perfect rank match on five items
# after tuning is overfitting, not accuracy. 3 and 4 give identical results,
# which is the only stability any value here shows, and 3 is the more
# conservative of the two.
STRUCTURAL_TOP_CHUNKS = 12
STRUCTURAL_MAX_DIMENSIONS = 3
_HARD_MODAL_RE = re.compile(r"\b(shall|must|is required to|are required to)\b", re.IGNORECASE)


def structurally_relevant(sentence: str, chunk_rank: int) -> bool:
    """Would structure alone justify scoring this sentence for this dimension?"""
    from src.evidence_strength import REGULATED_PARTY_RE

    return (
        chunk_rank < STRUCTURAL_TOP_CHUNKS
        and bool(REGULATED_PARTY_RE.search(sentence or ""))
        and bool(_HARD_MODAL_RE.search(sentence or ""))
    )


def apply_specificity_guard(
    candidates_by_dimension: dict[str, list[str]],
    max_dimensions: int = STRUCTURAL_MAX_DIMENSIONS,
) -> dict[str, list[str]]:
    """Drop structurally-admitted provisions that qualify for too many dimensions."""
    spread: collections.Counter = collections.Counter()
    for sents in candidates_by_dimension.values():
        for s in set(sents):
            spread[s] += 1
    return {
        dim: [s for s in sents if spread[s] <= max_dimensions]
        for dim, sents in candidates_by_dimension.items()
    }


# ── (C) The mechanism gate: make the two halves of the system agree ──────
#
# Verdicts come from SENTENCE counts. `binding_share` comes from MECHANISM
# tiers. Nothing made them agree, and on the study set three cells claimed a
# dimension was governed while not one of the mechanisms it needs was carried
# by a duty:
#
#     Japan  Safety     Operationalized    0 of 4 mechanisms bound
#     Kenya  Privacy    Operationalized    0 of 3
#     Kenya  Fairness   Operationalized    0 of 3
#
# and four more claimed the top stage on a single bound mechanism. A dimension
# cannot be "operational" while binding nothing it is supposed to bind, so the
# mechanism evidence now gates the stage the sentences propose. It can only
# hold a verdict DOWN, exactly like the coverage mechanism floor.
MECHANISMS_FOR_OPERATIONAL = 1
MECHANISMS_FOR_INSTITUTIONAL = 2


def apply_mechanism_gate(stage: str, mechanisms_bound: int) -> tuple[str, str | None]:
    """Hold a stage down to what the dimension's own mechanisms support.

    The demotions CASCADE. An earlier version returned after the first one, so
    a dimension sitting at Institutionalized with zero bound mechanisms landed
    on Operationalized and stopped — it never reached the rule that would have
    taken it to Delegated. Found on Brazil, where a data-protection statute
    read "Operationalized" for Human Autonomy, Inclusivity and Environmental
    Sustainability on 0 of 0 mechanisms.
    """
    note: str | None = None
    if stage == "Institutionalized" and mechanisms_bound < MECHANISMS_FOR_INSTITUTIONAL:
        stage = "Operationalized"
        note = (
            f"binding provisions exist, but only {mechanisms_bound} of the dimension's "
            "mechanisms is carried by a duty — not enough to call the regime institutionalised"
        )
    if stage == "Operationalized" and mechanisms_bound < MECHANISMS_FOR_OPERATIONAL:
        stage = "Delegated"
        note = (
            "binding provisions exist, but none of them carries a mechanism this "
            "dimension requires, so the governance is begun rather than operating"
        )
    return stage, note


# ══ v5 ═══════════════════════════════════════════════════════════════════
#
# ── List-item severance ──────────────────────────────────────────────────
#
# Statutes enumerate. Article 10(2) of the EU AI Act reads, in substance:
#
#     "Training, validation and testing data sets shall be subject to data
#      governance practices concerning in particular: ... (f) examination in
#      view of possible biases ...; (g) appropriate measures to detect,
#      prevent and mitigate possible biases ...;"
#
# The splitter breaks on ';' and ':' — precisely the punctuation enumeration
# uses — so each item arrives without the stem that carries its subject and
# its modal. Measured: the same duty scores T3 written whole and T0 severed.
#
# This under-scores exactly the strongest instruments, because statutes are
# the list-heavy ones. EU Fairness reported 0 of 4 mechanisms bound while the
# operative Article 10 duties were sitting in the pool, severed.
#
# The repair is to re-attach each item to its stem before classification. A
# stem is a fragment that carries a hard modal and announces a list; an item
# is a fragment opening with an enumeration marker. Items are re-emitted as
# "stem + item", so the classifier sees the duty the drafter wrote.

# (a) (iv) (1) a) 1. • — all the ways an instrument opens a list item.
_LIST_ITEM_RE = re.compile(
    r"^\s*(?:\(\s*(?:[a-z]{1,3}|[ivxlc]{1,5}|\d{1,3})\s*\)|"
    r"(?:[a-z]|\d{1,3})[.)]\s|[•▪–—]\s)",
    re.IGNORECASE,
)
# A stem announces what follows and carries the obligation.
_STEM_RE = re.compile(
    r"\b(shall|must|is required to|are required to)\b.{0,400}?"
    r"(?::|\bthe following\b|\bin particular\b|\bincluding\b)\s*$",
    re.IGNORECASE | re.DOTALL,
)
# Guard: never build something the length filters would reject anyway.
_MAX_REJOINED = 600


def _is_list_item(fragment: str) -> bool:
    return bool(_LIST_ITEM_RE.match(fragment or ""))


def _is_list_stem(fragment: str) -> bool:
    return bool(_STEM_RE.search(fragment or ""))


def rejoin_list_items(fragments: Sequence[str]) -> list[str]:
    """Re-attach enumerated items to the stem that governs them.

    The stem is kept as well: it is a real provision in its own right, and
    dropping it would trade one loss for another. A stem is forgotten once a
    fragment appears that is neither an item nor a continuation, so a list in
    one article cannot reach across into the next.
    """
    out: list[str] = []
    stem: str | None = None
    for frag in fragments:
        f = " ".join((frag or "").split())
        if not f:
            continue
        if _is_list_item(f):
            if stem:
                joined = f"{stem} {f}"
                out.append(joined[:_MAX_REJOINED] if len(joined) > _MAX_REJOINED else joined)
            else:
                out.append(f)
            continue
        out.append(f)
        # A new stem replaces the old one; anything else ends the list.
        stem = f if _is_list_stem(f) else None
    return out


# ── Duties imposed through the regulated artifact ────────────────────────
#
# Product-safety drafting does not always name the duty-bearer. It regulates
# the thing, and the duty falls on whoever places that thing on the market:
#
#     "High-risk AI systems shall be accompanied by instructions for use."
#     "Training, validation and testing data sets shall be subject to data
#      governance practices."
#     "The logging capabilities shall provide, at a minimum, recording of..."
#
# All three are duties on the provider. None names one, so REGULATED_PARTY_RE
# misses all three and the ladder drops them to the aspirational tier.
#
# Measured across the corpus: 112 hard-modal provisions (8%) have a regulated
# ARTIFACT as their grammatical subject and no person anywhere in the
# sentence. 105 of those are in the EU AI Act — the instrument this most
# under-scores is the strongest one in the study.
#
# An artifact-borne duty is scored as Obligatory, never Enforceable on its own:
# the provision binds, but the consequence still has to be found elsewhere.
REGULATED_ARTIFACT_RE = _words(
    "ai system",
    "ai systems",
    "artificial intelligence system",
    "artificial intelligence systems",
    "high-risk ai system",
    "high-risk ai systems",
    "general-purpose ai model",
    "general-purpose ai models",
    "foundation model",
    "data set",
    "data sets",
    "dataset",
    "datasets",
    "training data",
    "logging capabilit*",
    "technical documentation",
)


# ── Agentless enforcement ────────────────────────────────────────────────
#
# Chinese legal drafting in translation states the consequence and leaves the
# actor implicit:
#
#     "Where a crime is constituted, criminal liability shall be pursued in
#      accordance with the law."
#     "Public security administrative sanctions shall be imposed in
#      accordance with the law."
#
# Both are enforcement. Neither names a duty-bearer, so the ladder found no
# actor and scored them Aspirational — the same shape of failure as the
# artifact-borne duties above, with the consequence rather than the regulated
# thing as the grammatical subject. This is a civil-law drafting convention,
# not a China-specific quirk, and it would mis-read any translated statute.
_ENFORCEMENT_PASSIVE_RE = re.compile(
    r"\b(?:shall|must|is to|are to|will)\s+be\s+"
    r"(?:imposed|pursued|applied|borne|assumed|investigated|enforced|"
    r"punished|sanctioned|fined|prosecuted|revoked|suspended)\b",
    re.IGNORECASE,
)


def is_agentless_enforcement(sentence: str) -> bool:
    """A consequence stated in the passive with no actor named."""
    probe = strip_policing(sentence or "")
    return bool(CONSEQUENCE_RE.search(probe) and _ENFORCEMENT_PASSIVE_RE.search(probe))


def classify_provision(
    sentence: str,
    dimension: str = "",
    own_jurisdiction: str = "",
    document_is_nonbinding: bool = False,
    document_is_unenforced: bool = False,
) -> ScoredSentence:
    """v2's ladder, plus duties borne by the regulated artifact.

    Everything else is v2 exactly: the enforcement split, the hedge demotion
    and the voluntary cap are unchanged. Only the duty-bearer test is wider.
    """
    # Normalise "be + to-infinitive" to an explicit modal BEFORE the ladder
    # runs, so every downstream branch — regulated party, artifact, consequence
    # — sees the obligation the construction carries. Doing it afterwards only
    # rescued one branch and missed the others.
    probe_src = sentence or ""
    if BE_TO_OBLIGATION_RE.search(probe_src):
        normalised = BE_TO_OBLIGATION_RE.sub(
            lambda m: "shall be " + m.group(0).split()[-1], probe_src
        )
    else:
        normalised = probe_src

    scored = _classify_base(
        normalised,
        dimension=dimension,
        own_jurisdiction=own_jurisdiction,
        document_is_nonbinding=document_is_nonbinding,
        document_is_unenforced=document_is_unenforced,
    )
    # The result must always quote the document, never our normalisation.
    if normalised is not probe_src:
        scored = ScoredSentence(
            " ".join(probe_src.split()), scored.tier, scored.duty_bearer,
            scored.has_enforcement, excluded=scored.excluded,
        )
    if scored.excluded or scored.tier >= TIER_OBLIGATORY:
        return scored

    s = " ".join((sentence or "").split())
    probe = strip_policing(normalised)
    # Only rescue provisions that are genuinely obligatory in form and whose
    # subject is a regulated artifact. A hedge still demotes, and a voluntary
    # instrument still caps — both are re-applied below.
    if is_agentless_enforcement(s):
        # The consequence IS the subject. Enforceable, and the bearer is
        # whoever the instrument regulates.
        tier = TIER_ENFORCEABLE
        if document_is_nonbinding:
            tier = TIER_INTENTIONAL
        return ScoredSentence(s, tier, "agentless", tier >= TIER_ENFORCEABLE)
    if not (_HARD_MODAL_RE.search(probe) and REGULATED_ARTIFACT_RE.search(probe)):
        return scored
    if GOV_BODY_RE.search(probe):
        # "The Authority shall ensure the AI system..." is the government
        # directing itself; v2 already placed it correctly.
        return scored

    tier = TIER_OBLIGATORY
    if CONSEQUENCE_RE.search(probe):
        tier = TIER_ENFORCEABLE
    if HEDGE_RE.search(probe) and tier > TIER_INTENTIONAL:
        tier -= 1
    if document_is_nonbinding and tier > TIER_INTENTIONAL:
        tier = TIER_INTENTIONAL
    return ScoredSentence(s, tier, "artifact", tier >= TIER_ENFORCEABLE)


#: What a sentence's source document does to the force it can carry.
#: "voluntary"  — the document says so itself, so nothing exceeds Intentional.
#: "unenforced" — the document provides no consequence anywhere, so nothing
#:                exceeds Assigned.
#: ""           — the document carries its own machinery; no cap.
SOURCE_VOLUNTARY = "voluntary"
SOURCE_UNENFORCED = "unenforced"


def _source_lookup(source_force: dict[str, str] | None):
    """Resolve a sentence back to the cap its source document imposes.

    `rejoin_list_items` may have welded a stem and its list items into one
    string that is not a key, so an exact miss falls back to the longest key
    the sentence starts with. An unresolvable sentence gets no cap — the same
    answer the scorer gave before provenance existed.
    """
    if not source_force:
        return lambda _sentence: ""
    prefixes = sorted(source_force, key=len, reverse=True)

    def lookup(sentence: str) -> str:
        hit = source_force.get(sentence)
        if hit is not None:
            return hit
        for key in prefixes:
            if sentence.startswith(key[:60]):
                return source_force[key]
        return ""

    return lookup


def build_provision_profile(
    sentences: Iterable[str],
    dimension: str = "",
    own_jurisdiction: str = "",
    document_is_nonbinding: bool = False,
    source_force: dict[str, str] | None = None,
):
    """v2's profile with v5 classification and list-item repair applied.

    `source_force` maps a sentence to the ceiling its source document imposes
    (see SOURCE_VOLUNTARY / SOURCE_UNENFORCED). A dimension's pool is drawn
    from every document in the workspace, so one flag for the whole pool asks
    the wrong question: Japan's Safety pool holds provisions from the binding
    APPI and from guidelines that describe themselves as "soft laws without
    any legally binding force", and the flag had to be wrong about one of
    them. Scoping it per sentence lets one pool carry duties and advice at
    their own weights.
    """
    from src.evidence_strength import EvidenceProfile

    lookup = _source_lookup(source_force)
    profile = EvidenceProfile(dimension=dimension)
    for raw in dedupe_sentences(rejoin_list_items(list(sentences))):
        cap = lookup(raw)
        scored = classify_provision(
            raw,
            dimension=dimension,
            own_jurisdiction=own_jurisdiction,
            document_is_nonbinding=document_is_nonbinding or cap == SOURCE_VOLUNTARY,
            document_is_unenforced=cap == SOURCE_UNENFORCED,
        )
        profile.sentences.append(scored)
        if scored.excluded in ("foreign", "structural"):
            if scored.excluded == "foreign":
                profile.n_excluded_foreign += 1
            else:
                profile.n_excluded_structural += 1
            continue
        profile.n_scored += 1
        profile.tier_counts[scored.tier] = profile.tier_counts.get(scored.tier, 0) + 1
        profile.max_tier = max(profile.max_tier, scored.tier)
        if scored.tier >= TIER_ENFORCEABLE:
            profile.n_enforceable += 1
        if scored.tier >= TIER_OBLIGATORY:
            profile.n_binding += 1
        if scored.tier >= TIER_ASSIGNED:
            profile.n_institutional += 1
        if scored.tier >= TIER_INTENTIONAL:
            profile.n_commitment += 1
    return profile


# ══ v6 ═══════════════════════════════════════════════════════════════════
#
# ── The duty-bearer holds for the whole division ─────────────────────────
#
# Article 10(2) of the AI Act opens by naming what is regulated — "Training,
# validation and testing data sets shall be subject to data governance and
# management practices..." — and then enumerates:
#
#     "Those practices shall concern in particular: ... (g) appropriate
#      measures to detect, prevent and mitigate possible biases ..."
#
# "Those practices" is anaphora. The bearer was established two sentences
# earlier and governs every point in the paragraph. Classified sentence by
# sentence, point (g) has no bearer at all and scores Aspirational, so the
# AI Act's bias-mitigation duty reads as an aspiration.
#
# This is only safe to fix now. Resolving a bearer across sentences requires
# knowing where the provision ENDS, and until src/legal_structure.py gave us
# real divisions there was no boundary — a bearer would have leaked from one
# article into the next. A numbered paragraph is exactly the right scope: it
# is the unit a drafter writes one duty in.
def classify_division(
    fragments: Sequence[str],
    dimension: str = "",
    own_jurisdiction: str = "",
    document_is_nonbinding: bool = False,
) -> list[ScoredSentence]:
    """Classify the fragments of ONE division, sharing its duty-bearer.

    A fragment that carries a hard modal but names nobody is re-read with the
    bearer the division established. Nothing is promoted without a modal of
    its own, so a bare aspiration inside a binding paragraph stays aspirational.
    """
    from src.evidence_strength import REGULATED_PARTY_RE

    joined = rejoin_list_items(list(fragments))
    scored = [
        classify_provision(
            f,
            dimension=dimension,
            own_jurisdiction=own_jurisdiction,
            document_is_nonbinding=document_is_nonbinding,
        )
        for f in joined
    ]

    # The bearer this division establishes, if any.
    bearer = ""
    for f in joined:
        probe = strip_policing(f)
        if GOV_BODY_RE.search(probe):
            bearer = ""  # a government-directed division must not be lifted
            break
        m = REGULATED_PARTY_RE.search(probe) or REGULATED_ARTIFACT_RE.search(probe)
        if m:
            bearer = m.group(0)
            break
    if not bearer:
        return scored

    out: list[ScoredSentence] = []
    for frag, sc in zip(joined, scored):
        probe = strip_policing(frag)
        needs_bearer = (
            not sc.excluded
            and sc.tier < TIER_OBLIGATORY
            and _HARD_MODAL_RE.search(probe)
            and not REGULATED_PARTY_RE.search(probe)
            and not REGULATED_ARTIFACT_RE.search(probe)
            and not GOV_BODY_RE.search(probe)
        )
        if not needs_bearer:
            out.append(sc)
            continue
        # Re-read the fragment with the bearer restored, exactly as the
        # drafter's cross-reference intends it to be read.
        out.append(
            classify_provision(
                f"{bearer} {frag}",
                dimension=dimension,
                own_jurisdiction=own_jurisdiction,
                document_is_nonbinding=document_is_nonbinding,
            )
        )
    # Keep the ORIGINAL text on each result: evidence must still quote the
    # document, not our reconstruction of it.
    return [
        ScoredSentence(orig, s.tier, s.duty_bearer, s.has_enforcement, excluded=s.excluded)
        for orig, s in zip(joined, out)
    ]


# ── The "be + to-infinitive" obligation ──────────────────────────────────
#
# English expresses obligation with more than shall/must. "Be + to-infinitive"
# is a standard deontic construction in descriptive grammar (Quirk et al.,
# A Comprehensive Grammar of the English Language, on "be to" for obligation
# and arrangement): "payments are to be made monthly" is an obligation, not a
# prediction. v1's OBLIGATION_RE has shall, must and is/are required to, and
# does not have it.
#
# THIS IS ADDED ON GRAMMATICAL GROUNDS, NOT FROM DATA. That matters, because
# the construction was noticed on China — where China Law Translate renders
# 应当 as "are to be" throughout — and China is a held-out jurisdiction.
# Adding a rule because a held-out case needs it is leakage. Adding a rule
# because English grammar says it belongs, and THEN measuring what it does to
# the held-out case, is a test. This is the second.
#
# Deliberately narrow. "is to" also has a future-arrangement reading ("the
# report is to be published next year"), so the construction only counts when
# it governs a passive participle, which is where the deontic reading lives.
BE_TO_OBLIGATION_RE = re.compile(
    r"\b(?:is|are|was|were)\s+to\s+be\s+[a-z]+(?:ed|en|t)\b",
    re.IGNORECASE,
)


def has_obligation(sentence: str) -> bool:
    """v1's obligation test, plus the be + to-infinitive construction."""
    from src.evidence_strength import IMPOSITION_RE, OBLIGATION_RE

    probe = strip_policing(sentence or "")
    return bool(
        OBLIGATION_RE.search(probe)
        or IMPOSITION_RE.search(probe)
        or BE_TO_OBLIGATION_RE.search(probe)
    )
