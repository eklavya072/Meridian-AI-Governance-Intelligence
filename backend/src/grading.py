"""The scorer: what a provision requires, and how far a regime is built out.

The language model extracts evidence and writes prose. Nothing here asks it
anything. Every verdict is computed from counted, classified sentences, so a
stored analysis can be re-scored from its recorded evidence without spending a
single model call.

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
"""

from __future__ import annotations

import collections
import re
from collections.abc import Iterable, Sequence
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
    _words,
    is_structural_noise,
    is_third_party_attribution,
)

logger = structlog.get_logger()

# ── Enforcement: consequence versus oversight ────────────────────────────
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
    "punish*",  # standard in civil-law translation, rare in Anglo drafting
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
    # Administrative sanctions as civil-law translation renders them; PIPL
    # Chapter VII states all of its remedies in these words.
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

# PENAL PROVISION: the consequence stated as the operative act.
#
# T4 otherwise needs a duty modal — "providers shall ... or face a fine". But
# the most binding sentence in a statute often contains no modal at all,
# because it states the consequence instead of restating the duty:
# "A person who contravenes subsection (1) is guilty of an offence." Without
# this rule a criminal penalty would score below an ordinary "shall".
#
# Deliberately narrow: an offence, a conviction, or a stated liability to a
# penalty. "May face reputational consequences" is not this pattern, and a
# duty-free consequence on a non-regulated subject still does not qualify.
PENAL_PROVISION_RE = re.compile(
    r"\b(?:commits?|committed|is|are|shall\s+be)\s+(?:guilty\s+of|an?\s+)?"
    r"(?:an\s+)?offen[cs]e\b"
    r"|\bguilty\s+of\s+an\s+offen[cs]e\b"
    r"|\bon\s+conviction\b"
    r"|\bliable\s+(?:on\s+conviction\s+)?to\s+(?:a\s+)?"
    r"(?:fine|penalty|imprisonment|administrative\s+fine)",
    re.IGNORECASE,
)

# OVERSIGHT: an activity someone performs. Real governance, but not a
# penalty: an organisation asked to audit itself (a "Self Assessment
# checklist") is not thereby subject to enforcement.
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
# a market.
SUBJECTION_RE = re.compile(
    r"\b(?:is|are|shall\s+be|must\s+be|will\s+be|being|been)\s+subject(?:ed)?\s+to\b"
    r"|\b(?:supervis|monitor|audit|inspect|investigat|overse|certifi|accredit)\w*\s+by\s+"
    r"(?:the\s+|a\s+|an\s+)?[A-Za-z]"
    # "control" and "authority" are NOT here: "logs under the control of the
    # provider" says what that party CONTROLS, the opposite of being subject
    # to something.
    r"|\bunder\s+the\s+(?:supervision|oversight|inspection)\s+of\b"
    r"|\bsubject\s+to\s+(?:the\s+)?(?:supervision|oversight|inspection|audit|investigation|"
    r"certification|accreditation|approval|review|sanction|penalt)\w*",
    re.IGNORECASE,
)

# "law enforcement" is policing, not enforcement OF THIS INSTRUMENT: a
# sentence about strengthening the police imposes nothing.
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
    """The base tier ladder, with enforcement split into consequence and oversight.

    classify_provision widens the duty-bearer test on top of this.
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

    has_consequence = bool(CONSEQUENCE_RE.search(probe)) or bool(ADMIN_SANCTION_RE.search(probe))
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
    has_authority = bool(AUTHORITY_VERB_RE.search(probe)) or bool(ADMIN_SANCTION_RE.search(probe))
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
    elif has_regulated and PENAL_PROVISION_RE.search(probe):
        # The consequence IS the provision. See PENAL_PROVISION_RE.
        tier = TIER_ENFORCEABLE
        enforcement_credit = True
    elif has_regulated and (has_consequence or has_subjection):
        tier = TIER_OBLIGATORY
        enforcement_credit = has_consequence
    elif LEGAL_INSTRUMENT_RE.search(probe) and (has_obligation or has_consequence or has_oversight):
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
    # Intentional. This catches an instrument that is voluntary in substance
    # without ever saying so.
    if document_is_unenforced and tier > TIER_ASSIGNED:
        tier = TIER_ASSIGNED
        enforcement_credit = False

    return ScoredSentence(s, tier, bearer, enforcement_credit)


# How many enforcement signals establish a regime, scaled to document length.
# A flat count is length-biased: a 63-sentence statute with one penalties
# article could never reach a threshold calibrated on a 2,600-sentence
# regulation. The guard exists to reject a passing preamble mention, and that
# scales with how much document there is: one signal in 63 sentences is not
# incidental; one in 7,704 might be.
ENFORCEMENT_SIGNALS_PER_SENTENCES = 200


def required_enforcement_signals(n_sentences: int) -> int:
    """Signals needed to call it a regime, scaled to document length."""
    return max(1, min(3, round(n_sentences / ENFORCEMENT_SIGNALS_PER_SENTENCES)))


def detect_enforcement_regime(sample_texts: Iterable[str], min_signals: int | None = None) -> bool:
    """Does this DOCUMENT establish machinery with a consequence attached?

    Only sentences that reach the top tier under the consequence rule count:
    a supervisory word with no penalty behind it is not a regime.
    """
    from src.evidence_strength import _split_sentences_for_scoring

    texts = [t for t in sample_texts if t]
    sentences = [sent for t in texts for sent in _split_sentences_for_scoring(t)]
    needed = (
        min_signals if min_signals is not None else required_enforcement_signals(len(sentences))
    )
    signals = 0
    for t in texts:
        for sent in _split_sentences_for_scoring(t):
            # classify_provision, deliberately: the regime detector and the
            # profile must agree on what enforcement IS, agentless penalty
            # articles ("criminal liability shall be pursued") included.
            if classify_provision(sent).tier >= TIER_ENFORCEABLE:
                signals += 1
                if signals >= needed:
                    return True
    return False


# ── Enforcement backing per dimension ───────────────────────────────────


def dimension_enforcement_backing(
    sentences_by_document: dict[str, list[str]],
    documents_with_regime: set[str],
    dimension: str = "",
    own_jurisdiction: str = "",
) -> bool:
    """Can this dimension claim the document's own enforcement machinery?

    Only if a document that BOTH has an enforcement regime AND supplies at
    least one binding sentence to this dimension. A privacy statute's
    penalties do not back Transparency or Fairness.
    """
    for doc, sents in sentences_by_document.items():
        if doc not in documents_with_regime:
            continue
        for s in sents:
            # classify_provision, the classifier that scores the profile, so
            # artifact-borne and be-to duties count here too.
            if (
                classify_provision(s, dimension=dimension, own_jurisdiction=own_jurisdiction).tier
                >= TIER_OBLIGATORY
            ):
                return True
    return False


# ── Evidence sufficiency ─────────────────────────────────────────────────
#
# The scorer must tell "we read this dimension carefully and found no duty"
# from "there was almost nothing to read".
#
# THE THRESHOLD IS DERIVED, NOT CHOSEN. Over the cells that do carry a duty,
# binding sentences are 18.2% of scored sentences. If a dimension is governed
# at that rate, the chance of reading k sentences and seeing no duty at all is
# 0.818^k, which first falls at or below 20% at k = 9:
#
#     0.818^8 = 0.201   (just misses)
#     0.818^9 = 0.164
#
# The profile sweeps every sentence of every supplied document, so k is a
# census rather than a sample: a low count is itself the finding. The
# threshold therefore grades how much text a verdict describes
# (verdict_confidence) and withholds nothing. It was derived on the study
# corpus and should be re-derived before relying on it elsewhere.
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


def verdict_confidence(
    n_scored: int,
    n_binding: int,
    n_enforceable: int,
    mechanisms_bound: int = 0,
) -> tuple[str, str]:
    """How much evidence stands behind one cell, and why.

    A verdict resting on 274 provisions and one resting on 2 would otherwise
    render identically, so the band tells a reader which to check before
    quoting.

    Deliberately three coarse bands and not a 0-100 number. A precise-looking
    confidence score invented from counts would be exactly the kind of
    unearned precision the rest of this module exists to avoid.
    """
    if n_scored == 0:
        return "none", "no provisions were scored for this dimension"
    # Thin, not insufficient: every sentence of every supplied document is
    # swept, so a low count means the document itself barely touches the
    # dimension. The verdict stands; the band says how little text it describes.
    if not evidence_is_sufficient(n_scored, n_binding):
        return "thin", (
            f"every provision was read and only {n_scored} touch this dimension, "
            f"none of them binding — the document barely addresses it"
        )
    if n_binding == 0:
        return "moderate", (
            f"{n_scored} provisions were read and none imposes a duty — enough "
            f"to stand behind the absence, but the finding is what is MISSING"
        )
    if n_binding >= 5 and (n_enforceable >= 1 or mechanisms_bound >= 2):
        return "strong", (
            f"{n_binding} binding provisions"
            + (f", {n_enforceable} backed by a consequence" if n_enforceable else "")
            + (f", carrying {mechanisms_bound} expected mechanisms" if mechanisms_bound else "")
        )
    return "moderate", (
        f"{n_binding} binding provision(s) out of {n_scored} scored"
        + (f", {n_enforceable} enforceable" if n_enforceable else ", none enforceable")
        + " — read the provisions before quoting this cell"
    )


# ── Duplicate provisions ─────────────────────────────────────────────────
#
# Chunk windows overlap by design so a provision is never split across a
# boundary, and the scoring pool therefore contains the same sentence once per
# window that covers it. Without de-duplication every counter it feeds — and
# the counts quoted in the narrative ("imposes 73 binding requirements") — is
# inflated.
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
    one sentence — so an exact key would count the provision once per
    overlapping chunk. Containment catches truncation at either end.

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


# ── Sentence function: is this text OPERATIVE at all? ────────────────────
#
# The ladder tiers whatever it is handed, so non-operative text must be
# removed first: recitals (a regulation's preamble has no binding force under
# EU law), definitions, headings, descriptions, a body's own housekeeping,
# consultation questions and lists of institutions. This gate runs BEFORE tier
# classification, like the structural-noise and third-party exclusions.

# "X means Y", "X refers to Y" — defines a term, requires nothing of anyone.
_DEFINITION_RE = re.compile(
    r"\b(means|shall mean|refers to|is defined as|are defined as|"
    r"for the purposes of this|is understood as)\b",
    re.IGNORECASE,
)

# A body's own composition, tenure and procedure. These carry real "shall"s —
# "In appointing members, the Cabinet Secretary shall ensure gender balance" —
# but they govern the regulator, not AI.
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


# A consultation document asks what the law SHOULD be: "Are there other
# measures we could require of organisations to improve transparency for AI?"
# The vocabulary of obligation — require, liable, responsible — is dense in
# these sentences and none of them imposes anything.
#
# An enumeration of which bodies exist is not a duty either: "Enabled by
# coordinated institutional leadership - including the Ministry of ... as the
# nodal ministry, the AI Governance Group, the AI Safety Institute..." lists
# an org chart and creates nothing. The signature is a run of named bodies
# joined by apposition with no modal governing them. Counting the bodies is
# more robust than looking for a lead-in phrase, which chunk boundaries often
# cut away.
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
    if len(
        _INSTITUTION_NOUN_RE.findall(s)
    ) >= _INSTITUTIONS_FOR_LIST and not _GOVERNING_MODAL_RE.search(s):
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
        text = c.get("text") or ""
        if re.search(
            r"\bArticle\s+1\b.{0,80}?\b(Subject matter|Scope|Purpose)\b", text, re.I | re.S
        ):
            md = c.get("metadata") or {}
            pg = md.get("page_number") or c.get("page_number")
            if pg and (first is None or pg < first):
                first = pg
    return first


# ── Structural relevance: admit duties the vocabulary gate cannot see ────
#
# The core-term gate rejects real duties it has no word for — a logging
# obligation is missed because "logging" is not a Transparency core term.
# Admitting everything with a modal instead would flood every dimension with
# a statute's generic "must" clauses. So admission is conditioned on
# STRUCTURE: the sentence must sit in a chunk retrieval ranked highly FOR THIS
# DIMENSION, name a regulated party, and carry a hard modal.
#
# That still leaks generic provisions ("programmes ... shall be conducted at
# national and county levels" qualifies for six dimensions). The specificity
# guard is the filter: a provision admitted to more than MAX_DIMENSIONS
# dimensions is by construction not specific to any of them. 3 and 4 give
# identical results on the study set; 3 is the more conservative.
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


# ── The mechanism gate: make the two halves of the system agree ─────────
#
# Verdicts come from SENTENCE counts; `binding_share` comes from MECHANISM
# tiers. A dimension cannot be "operational" while not one of the mechanisms
# it needs is carried by a duty, so the mechanism evidence gates the stage the
# sentences propose. It can only hold a verdict DOWN, like the coverage
# mechanism floor.
MECHANISMS_FOR_OPERATIONAL = 1
MECHANISMS_FOR_INSTITUTIONAL = 2


def apply_mechanism_gate(stage: str, mechanisms_bound: int) -> tuple[str, str | None]:
    """Hold a stage down to what the dimension's own mechanisms support.

    The demotions CASCADE: a dimension at Institutionalized with zero bound
    mechanisms falls through every rule that applies, not just the first.
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
# its modal, and the same duty would score T3 whole and T0 severed.
#
# The repair re-attaches each item to its stem before classification. A stem
# is a fragment that carries a hard modal and announces a list; an item is a
# fragment opening with an enumeration marker. Items are re-emitted as
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
# All three are duties on the provider, and none names one.
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
# Both are enforcement, though neither names a duty-bearer. This is a
# civil-law drafting convention, not a China-specific quirk.
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
    """The full tier classifier: the base ladder plus artifact-borne duties.

    The enforcement split, the hedge demotion and the voluntary cap are the
    base ladder's; only the duty-bearer test is wider.
    """
    # Normalise "be + to-infinitive" to an explicit modal BEFORE the ladder
    # runs, so every branch — regulated party, artifact, consequence — sees
    # the obligation the construction carries.
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
            " ".join(probe_src.split()),
            scored.tier,
            scored.duty_bearer,
            scored.has_enforcement,
            excluded=scored.excluded,
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
        # directing itself; the base ladder already places it.
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
    the sentence starts with. An unresolvable sentence gets no cap.
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
    """Score every sentence for one dimension into an EvidenceProfile.

    Sentences are de-duplicated and their list items re-attached first.
    `source_force` maps a sentence to the ceiling its source document imposes
    (see SOURCE_VOLUNTARY / SOURCE_UNENFORCED). A dimension's pool is drawn
    from every document in the workspace, so the cap is scoped per sentence:
    one pool can carry a statute's duties and a guideline's advice at their
    own weights.
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
        # Every exclusion the classifier reports is left out of the counts.
        if scored.excluded:
            if scored.excluded == "third_party":
                profile.n_excluded_foreign += 1
            elif scored.excluded == "structural":
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


# ── The "be + to-infinitive" obligation ──────────────────────────────────
#
# English expresses obligation with more than shall/must. "Be + to-infinitive"
# is a standard deontic construction (Quirk et al., A Comprehensive Grammar of
# the English Language): "payments are to be made monthly" is an obligation,
# not a prediction. It is added on grammatical grounds, not fitted to data.
#
# Deliberately narrow. "is to" also has a future-arrangement reading ("the
# report is to be published next year"), so the construction only counts when
# it governs a passive participle, which is where the deontic reading lives.
BE_TO_OBLIGATION_RE = re.compile(
    r"\b(?:is|are|was|were)\s+to\s+be\s+[a-z]+(?:ed|en|t)\b",
    re.IGNORECASE,
)


def has_obligation(sentence: str) -> bool:
    """OBLIGATION_RE, plus the be + to-infinitive construction."""
    from src.evidence_strength import IMPOSITION_RE, OBLIGATION_RE

    probe = strip_policing(sentence or "")
    return bool(
        OBLIGATION_RE.search(probe)
        or IMPOSITION_RE.search(probe)
        or BE_TO_OBLIGATION_RE.search(probe)
    )
