"""Dimension vocabulary and the text tests built on it.

What lives here is shared by retrieval, the scorer and the citation gates:
which words make a sentence ABOUT a dimension (DIMENSION_CORE_TERMS, with the
off-sense phrases masked out first), which make a passage name a body, a
reporting duty or an enforcement route, how a chunk is split into sentences,
and how glossary fragments are recognised.

It decides nothing on its own: every verdict is computed from graded
provisions (evidence_strength.py) in gap_analyzer._compute_deterministic_verdict.
"""

from __future__ import annotations

import re
from functools import lru_cache

from src.utils import ocr_flexible_fragment

# Keywords that signal an operational mechanism in the document text.
# Includes the IRREGULAR plurals the whole-word matcher's "(?:s)?" cannot
# produce (agencies/ministries/authorities/ombudsmen) so plural body names
# still earn the named-body co-occurrence credit.
NAMED_BODY_KEYWORDS = (
    "commission",
    "board",
    "authority",
    "ministry",
    "agency",
    "council",
    "task force",
    "committee",
    "directorate",
    "office",
    "institute",
    "centre",
    "center",
    "department",
    "ombudsman",
    "inspectorate",
    "agencies",
    "ministries",
    "authorities",
    "ombudsmen",
    # Stem form: Korean-style body names assign duties to "the Minister of
    # Science and ICT" (not "the ministry"), which the literal "ministry"
    # entry cannot match. "minister*" → \bminister\w*\b covers minister,
    # ministers, ministerial — and never "administration" (no word boundary
    # before "minist").
    "minister*",
)
REPORTING_KEYWORDS = (
    "report",
    "reporting",
    "reported",
    "register",
    "registered",
    "registry",
    "registries",
    "publication",
    "annual report",
    "disclosure",
    "transparency report",
    "publish",
    "published",
    "publishing",
    "notify",
    "records",
    "documentation requirement",
    "audit trail",
    # Noun stems: the Korea Act's duties are phrased as "advance notification
    # duty" and "labeling/indication requirement", which the verb keyword
    # "notify" misses under word-boundary matching. "notif*" → \bnotif\w*\b
    # covers the whole notification family; "label*" covers labeling/labelling;
    # "indicatio*" covers indication(s) only — never "indicator" or
    # "indicative" (stems diverge after "indicat"), so a performance-
    # indicator mention is not credited as a reporting duty.
    "notif*",
    "label*",
    "indicatio*",
)
ENFORCEMENT_KEYWORDS = (
    "enforce",
    "enforcement",
    "enforcing",
    "redress",
    "grievance",
    "complaint",
    "appeal",
    "sanction",
    "penalty",
    "penalties",
    "fine",
    "remedy",
    "remedies",
    "liability",
    "liabilities",
    "audit",
    "auditing",
    "inspect",
    "inspecting",
    "inspection",
    "inspections",
    "monitor",
    "monitoring",
    "oversight",
    "supervision",
    "compliance check",
    "corrective action",
    "revocation",
    "order to stop",
)


# ── Low-information glossary/index fragment detection ────────────────────
# PDF extractors frequently concatenate footnote or page numbers onto
# glossary terms, producing chunks that are a term + number with no actual
# sentence content (e.g. "Explainability15", "Transparency 27",
# "Accountability 6"). These are real chunks but useless as evidence — they
# rank on embedding similarity alone and crowd out substantive passages from
# the small per-dimension budgets. A chunk is a low-information fragment when
# it has no real sentence structure: a capitalized term followed by digits
# (the glossary artifact), or a short term/heading-only line.
GLOSSARY_ENTRY_RE = re.compile(r"^[A-Z][A-Za-z&'\- ]{1,80}?\s*\d{1,3}(\s*,\s*\d{1,3})*\s*\.?\s*$")


def is_low_information_fragment(text: str | None) -> bool:
    """True when a chunk is a low-information glossary/index fragment.

    A chunk is ineligible to be preferred as cited evidence when it carries no
    real sentence content: a capitalized term followed by footnote/page digits
    ("Explainability15", "Transparency 27"), or a short term/heading-only
    line with no lowercase common word and no sentence punctuation. The test
    the user gave is: does the chunk contain a full sentence with a subject
    and verb, not just a capitalized term followed by digits.

    Conservative on purpose: a real short sentence ("The policy establishes
    an ethics board.") contains lowercase words and passes; only genuine
    fragments are flagged.
    """
    if not text:
        return True
    norm = " ".join(text.split()).strip()
    if not norm:
        return True
    # Term + footnote/page number artifact: "Explainability15",
    # "Transparency 27", "Accountability 6, 12". Anchored so a real sentence
    # that merely ends in a number ("...published in 2024") never matches.
    if GLOSSARY_ENTRY_RE.match(norm):
        return True
    # Bare heading / glossary line: short, no sentence punctuation, and no
    # lowercase common word (a real sentence always contains one).
    if len(norm) <= 50:
        if not any(ch in norm for ch in ".!?;:"):
            words = norm.split()
            if words and all(
                w.isupper() or not w[:1].islower() or len(w) <= 3 or w.isdigit() for w in words
            ):
                return True
    return False


_KEYWORD_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _word_pattern(phrase: str) -> re.Pattern:
    r"""Compile a whole-word regex for a phrase/keyword.

    Word boundaries on both sides: "program" matches only the standalone
    word (and its plural "programs"), never inside "programming" or
    "programme"; "roadmap" never matches inside "roadmapping"; "board"
    never matches inside "keyboard". An optional trailing "s" keeps simple
    plurals ("programs", "roadmaps", "initiatives") matching without
    reopening the substring holes.

    A trailing "*" marks a STEM-PREFIX keyword: the stem matches followed by
    any word characters, so one entry covers a word family the "(?:s)?"
    plural cannot — "notif*" compiles to \bnotif\w*\b and matches notify,
    notification, notifications, notified, notifying; "minister*" matches
    minister, ministers, ministerial. Word boundaries still apply on both
    sides, so a stem never reaches inside a longer word: "minister*" never
    matches "administration" (no boundary before "minist"), and
    "indicatio*" never matches "indicator" or "indicative" (their stems
    diverge after "indicat").
    """
    stem_key = phrase.endswith("*")
    cached = _KEYWORD_PATTERN_CACHE.get(phrase)
    if cached is not None:
        return cached
    if stem_key:
        pattern = re.compile(r"\b" + re.escape(phrase[:-1]) + r"\w*\b", re.IGNORECASE)
    else:
        pattern = re.compile(r"\b" + re.escape(phrase) + r"(?:s)?\b", re.IGNORECASE)
    _KEYWORD_PATTERN_CACHE[phrase] = pattern
    return pattern


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """True when any keyword occurs in `text` as a whole word (word boundaries)."""
    return any(_word_pattern(kw).search(text or "") for kw in keywords)


# Obligation language. A dimension-relevant passage that IMPOSES a requirement ("shall notify", "must ensure", "is
# required to", "prohibits") is an actual governance mechanism expressed in
# the policy's own terminology, distinct from a bare principle mention
# ("recognizes the importance of X" carries no obligation). This is what
# distinguishes "principle mentioned" from "governance mechanism exists"
# deterministically, and it is deliberately mechanism-agnostic — the same
# obligation vocabulary applies to every dimension, so a policy that says
# "financial institutions shall maintain strict confidentiality of personal
# information" is recognised as containing a privacy mechanism without any
# privacy-specific keyword table. Negated occurrences ("shall not",
# "does not require") are handled by the shared negation guard; a
# prohibition ("shall not discriminate") still counts — it is a mechanism.
OBLIGATION_VERBS = (
    "shall",
    "must",
    "requires",
    "is required to",
    "are required to",
    "obligated",
    "obliges",
    "mandates",
    "establishes",
    "sets out",
    "provides for",
    "lays down",
    "prohibits",
    "ensures that",
    "guarantees",
    "directs",
    "instructs",
    "imposes",
)

# Negation words that make a phrase a DENIAL rather than a commitment. When
# a matched phrase is preceded (within a short window) by one of these, it
# does not count — e.g. "will not support" must not floor Missing->Partial,
# and "not committed to" must not. Checking the last TWO tokens catches both
# "will not support" (negator adjacent to the phrase) and "no dedicated
# programme" (negator one token back, adjective in between). (Known,
# documented residual limitation: a negation embedded further back — e.g.
# "lacks a dedicated programme" — is not caught; the detector stays
# conservative rather than over-clever.)
NEGATION_WORDS = frozenset(
    {
        "not",
        "no",
        "never",
        "unable",
        "fails",
        "failed",
        "won't",
        "doesn't",
        "cannot",
        "can't",
        "isn't",
        "aren't",
        "without",
        "lacks",
        "refuses",
        "declines",
        "against",
    }
)


def _is_negated_occurrence(text: str, idx: int) -> bool:
    """True when the match at `idx` in `text` is preceded by a negation word."""
    window = text[max(0, idx - 16) : idx].split()
    if not window:
        return False
    return any(tok in NEGATION_WORDS for tok in window[-2:])


def _contains_commitment_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    """True when any phrase occurs in `text` on a non-negated, whole-word occurrence.

    Word-boundary matching: "program" does not match inside "programming",
    "roadmap" not inside "roadmapping". Negated occurrences ("will not
    support", "not committed to") never count.
    """
    for phrase in phrases:
        pattern = _word_pattern(phrase)
        for match in pattern.finditer(text):
            if not _is_negated_occurrence(text, match.start()):
                return True
    return False


def text_contains_mechanism(text: str) -> bool:
    """True when a passage imposes a governance mechanism.

    Mechanism-agnostic: a named body, a reporting/disclosure duty, an
    enforcement/redress duty, or obligation language ("shall", "must",
    "requires"...) in the passage. The same categories apply to every
    dimension, recognised in the policy's own terminology rather than a
    per-dimension keyword checklist. Used to keep definitions and bare
    principles out of auto-attached citations.
    """
    if not text:
        return False
    if _has_keyword(
        text,
        NAMED_BODY_KEYWORDS + REPORTING_KEYWORDS + ENFORCEMENT_KEYWORDS,
    ):
        return True
    return _contains_commitment_phrase(text.lower(), OBLIGATION_VERBS)


# ── Dimension grounding (topical relevance) ─────────────────────────────
#
# A chunk must be topically related to a dimension before it can serve as
# that dimension's incident match, roadmap citation or fallback citation. This
# list is the broad RECALL gate; the core terms below are the precision gate.
DIMENSION_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Transparency": (
        "transparen",
        "disclos",
        "explainab",
        "documentation",
        "audit trail",
        "logging",
        "open",
        "public report",
        "inform",
        "opacity",
        "opaque",
        "black box",
        "decision-making",
        "interpretab",
    ),
    "Accountability": (
        "accountab",
        "liabilit",
        "redress",
        "grievance",
        "complaint",
        "oversight",
        "audit",
        "enforce",
        "enforcement",
        "responsib",
        "sanction",
        "penalty",
        "remedy",
        "remedies",
        "answerable",
        "blame",
        "consequence",
        "governance structure",
        "ownership",
        "obligation",
        "duty",
    ),
    "Privacy": (
        "privacy",
        "personal data",
        "consent",
        "anonymiz",
        "pseudonymiz",
        "data protection",
        "data minimiz",
        "purpose limitation",
        "data subject",
        "breach",
        "confidential",
        "data security",
    ),
    "Safety": (
        "safety",
        "safe",
        "robust",
        "fail-safe",
        "failsafe",
        "adversarial",
        "monitor",
        "monitoring",
        "incident",
        "emergency",
        "shut-off",
        "certification",
        "harm",
        "reliability",
        "test",
        "testing",
        "validation",
        "red team",
    ),
    "Human Autonomy": (
        "autonomy",
        "human control",
        "human oversight",
        "opt-out",
        "human-in-the-loop",
        "human in the loop",
        "self-determination",
        "non-automated",
        "manipulation",
        "nudge",
        "nudging",
        "human agency",
        "override",
        "meaningful control",
    ),
    "Inclusivity": (
        "inclusiv",
        "inclusion",
        "accessib",
        "digital divide",
        "multi-stakeholder",
        "multistakeholder",
        "public participation",
        "diversity",
        "diverse",
        "disabilit",
        "linguistic",
        "cultural",
        "represent",
        "underserved",
        "marginalis",
        "equitab",
        "equity",
        "non-discriminat",
        "gender",
        "persons with disabilities",
    ),
    "Fairness": (
        "fair",
        "fairness",
        "bias",
        "discrimina",
        "equitab",
        "demographic parity",
        "protected characteristics",
        "prejudice",
        "stereotype",
        "parity",
    ),
    "Environmental Sustainability": (
        "environment",
        "environmental",
        "sustainab",
        "energy efficiency",
        "carbon",
        "footprint",
        "climate",
        "lifecycle",
        "e-waste",
        "emissions",
        "green",
        "computational resource",
        "resource consumption",
        "energy consumption",
    ),
}


# ── Core-term precision gate (anti false-positive, collision fix) ───────
#
# DIMENSION_TOPIC_KEYWORDS (above) is deliberately broad — it is a RECALL
# gate. That breadth lets topically adjacent vocabulary match: a sentence
# listing "healthcare, energy, public services" as high-impact AI sectors
# matches Environmental Sustainability on the bare word "energy".
#
# CORE_TERMS is a tighter, higher-precision anchor per dimension: unlike
# the topic list, every phrase here is nearly unambiguous evidence the
# sentence is actually ABOUT the dimension's substance (not merely a
# neighbouring sector/domain name). A sentence enters a dimension's evidence
# profile only on a core-term hit (gap_analyzer._dimension_profile).
# ── Sense-disambiguation guard (anti topic-collision) ────────────────────
# Some core terms are genuinely the right vocabulary for a dimension but
# carry a second, unrelated sense in policy prose:
#
#   "sustainable growth and innovation"      -> economic, not environmental
#   "relevant, accessible and comprehensible" -> availability, not disability
#   "transparent financing models"            -> fiscal, not AI transparency
#
# Removing the stem entirely would lose real matches ("transparen" IS the
# right term for Transparency), so instead the OFF-SENSE PHRASES are masked
# out of the sentence before core terms are matched. A sentence whose only
# hit lies inside a masked phrase correctly stops matching, while the same
# stem used in its governance sense elsewhere in the sentence still counts.
DIMENSION_TERM_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    "Transparency": (
        "transparent financing",
        "transparent funding",
        "transparent pricing",
        "transparent procurement",
        "transparent market",
        "transparent tax",
        "financial transparency",
        "fiscal transparency",
        "budget transparency",
        "transparency in financing",
        "transparency of markets",
    ),
    "Inclusivity": (
        # "inclusive growth/economy" is an economic-development claim, not a
        # demographic-inclusion governance mechanism.
        "inclusive growth",
        "inclusive economy",
        "inclusive economic",
        "financial inclusion",
        "inclusive development",
    ),
    "Fairness": (
        # "fair market"/"fair competition"/"fair trade" are competition-policy
        # senses, not algorithmic fairness.
        "fair market",
        "fair competition",
        "fair trade",
        "fair value",
        "fair price",
        "fair pricing",
        "fair share",
    ),
    "Safety": (
        # Occupational/road/food safety are different policy domains.
        "food safety",
        "road safety",
        "occupational safety",
        "public safety net",
    ),
}


@lru_cache(maxsize=64)
def _exclusion_pattern(dimension: str) -> re.Pattern | None:
    """Compiled matcher for a dimension's off-sense phrases."""
    phrases = DIMENSION_TERM_EXCLUSIONS.get(dimension)
    if not phrases:
        return None
    return re.compile("|".join(ocr_flexible_fragment(p) for p in phrases), re.IGNORECASE)


DIMENSION_CORE_TERMS: dict[str, tuple[str, ...]] = {
    "Transparency": (
        "transparen",
        "disclos",
        "explainab",
        "interpretab",
        "documentation",
        "audit trail",
        "black box",
        "black-box",
        # Real-world equivalents of "transparency" in a country's own
        # legal terminology (e.g. Korea's AI Basic Act phrases its
        # transparency duty as "advance notification" + "labeling", never
        # the word "transparency" itself) — the gate must recognize the
        # MECHANISM, not just the abstract vocabulary.
        "notif",
        "label",
        "inform users",
        "inform individuals",
    ),
    "Accountability": (
        # Incident-reporting vocabulary is included because
        # DIMENSION_MECHANISMS lists "incident reporting" as an Accountability
        # mechanism: a mechanism the table expects must have vocabulary the
        # gate admits.
        "accountab",
        # KNOWN OVERLAP, KEPT DELIBERATELY. "liable", "sanction", "penalt"
        # and "fine" are also the words CONSEQUENCE_RE reads to decide a
        # provision is Enforceable, so a penalty sentence enters this
        # dimension and earns its tier on one signal. That makes this the
        # least discriminating cell, but for many jurisdictions the penalty
        # regime IS the accountability regime; removing the vocabulary would
        # remove the finding with it.
        "liabilit",
        "liable",
        "redress",
        "sanction",
        "penalt",
        "fine",
        "grievance",
        "complaint mechanism",
        "answerable",
        "duty of care",
        "serious incident",
        "incident report",
        "report an incident",
        "notify the authorit",
        "report to the market surveillance",
    ),
    "Privacy": (
        "privacy",
        "personal data",
        "personal information",
        "data protection",
        "anonymiz",
        "pseudonymiz",
        "data subject",
        "confidential",
    ),
    "Safety": (
        "safety",
        "safe design",
        "risk management",
        "fail-safe",
        "failsafe",
        "red team",
        "red-team",
        "adversarial test",
        "robustness",
    ),
    "Human Autonomy": (
        "human oversight",
        "human control",
        "human-in-the-loop",
        "human in the loop",
        "override",
        "human agency",
        "autonomy",
        "meaningful control",
        "opt-out",
        # "human oversight" is EU drafting. Other traditions express the same
        # binding duty in their own words: Korea's AI Framework Act requires
        # "Human management and supervision of high-impact AI", GDPR
        # Article 22 speaks of "human intervention".
        #
        # All bigrams beginning with "human", deliberately: bare "supervision"
        # and "management" collide with regulatory supervision and corporate
        # management throughout these documents.
        "human management",
        "human supervision",
        "human intervention",
        "human review",
        "human monitoring",
        "human judgment",
        "human judgement",
    ),
    "Inclusivity": (
        # Bare "accessib" is deliberately NOT listed: transparency provisions
        # require information to be "accessible" in the sense of available
        # ("relevant, accessible and comprehensible information" — EU AI Act
        # Article 13), which has nothing to do with disability inclusion.
        "inclusiv",
        "inclusion",
        # The disability sense is carried by compounds, never by bare
        # "accessib" — including the compounds naming accessibility
        # requirements and directives, as the EU AI Act's own duty does.
        "accessibility requirement",
        "accessibility standard",
        "accessibility need",
        "accessibility for persons with disabilities",
        "digital accessibility",
        "accessible design",
        "web accessibility",
        "disabilit",
        "digital divide",
        "underserved",
        "marginalis",
        "persons with disabilities",
        "multi-stakeholder",
        "multistakeholder",
        "public participation",
    ),
    "Fairness": (
        "fair",
        "fairness",
        "bias",
        "discrimina",
        "demographic parity",
        "protected characteristics",
        "stereotype",
    ),
    "Environmental Sustainability": (
        # Bare "sustainab" is deliberately NOT listed: in policy documents
        # "sustainable" overwhelmingly modifies ECONOMIC growth. Bare
        # "ecosystem" usually means an INNOVATION ecosystem. Bare
        # "environment" appears in safety provisions ("damage to property or
        # the environment" among incident consequences). Only
        # environment-anchored forms are counted.
        "environmentally sustainable",
        "environmental sustainability",
        "sustainable development",
        # Bare "ecological" is deliberately NOT listed: in Chinese internet
        # regulation 生态 is rendered "ecological" and means the CONTENT
        # ecosystem ("ecological management of algorithm recommendation
        # service pages"). The genuine senses are anchored below.
        "ecological footprint",
        "ecological impact",
        "natural ecosystem",
        "ecosystems and biodiversity",
        "biodiversity",
        "carbon",
        "emission",
        "e-waste",
        "electronic waste",
        "energy efficiency",
        "energy consumption",
        "power consumption",
        "climate",
        "footprint",
        "green computing",
        "green energy",
        "resource consumption",
        "resource-efficient",
        "resource efficiency",
        "renewable",
    ),
}


@lru_cache(maxsize=64)
def _core_term_pattern(dimension: str) -> re.Pattern | None:
    """Compiled, OCR-tolerant matcher for a dimension's core terms."""
    terms = DIMENSION_CORE_TERMS.get(dimension)
    if not terms:
        return None
    return re.compile("|".join(ocr_flexible_fragment(t) for t in terms), re.IGNORECASE)


def _sentence_has_core_term(text: str, dimension: str) -> bool:
    """True when `text` contains a HIGH-PRECISION core term for `dimension`.

    Substring match (not whole-word) is deliberate: these are already
    multi-character stems/phrases chosen to be unambiguous, and a substring
    check catches inflections (transparency/transparent/transparently)
    without a bigger regex table. Dimensions without a core-term entry are
    not gated (defensive default — never blocks an unrecognised dimension).

    Matching is OCR-tolerant (see ocr_flexible_fragment): PDF extraction
    splits words with spurious internal spaces, and a literal substring test
    silently dropped nearly every core-term match in the most heavily
    corrupted document in the corpus.
    """
    pattern = _core_term_pattern(dimension)
    if pattern is None:
        return True
    candidate = text or ""
    # Mask off-sense phrases first (see DIMENSION_TERM_EXCLUSIONS) so a hit
    # that exists only inside e.g. "transparent financing models" does not
    # qualify the sentence, while the same stem used in its governance sense
    # elsewhere in the sentence still does.
    exclusions = _exclusion_pattern(dimension)
    if exclusions is not None:
        candidate = exclusions.sub(" ", candidate)
    return bool(pattern.search(candidate))


def _chunk_matches_dimension(text: str, dimension: str) -> bool:
    """True when a chunk is topically related to the dimension.

    A chunk that merely contains governance vocabulary but is about
    something else never counts for the dimension (a UN advisory-body participation
    paragraph is not Accountability evidence; an events calendar is not
    Inclusivity evidence). Unknown dimensions are not gated (no false
    blocking).
    """
    keywords = DIMENSION_TOPIC_KEYWORDS.get(dimension)
    if not keywords:
        return True
    lower = (text or "").lower()
    return any(kw in lower for kw in keywords)


# ── Sentence splitting ───────────────────────────────────────────────────
# Evidence is graded sentence by sentence, never chunk by chunk: a long legal
# passage can carry a genuine duty in one sentence and procedural boilerplate
# in the next, and a chunk-level test lets the two borrow from each other (a
# safety duty in a mixed Article 32/33 chunk once counted for Fairness).
# Terminators include U+FFFD and the mojibake bullets PDF extraction leaves
# where a full stop or list bullet should be. Documents in this corpus were
# found using "�" as their ONLY sentence terminator across whole sections —
# with a plain [.!?] splitter every such chunk collapsed into one enormous
# pseudo-sentence, which then failed every downstream length filter, so those
# documents contributed almost no scorable sentences at all. That looked like
# "this policy says nothing about the dimension" when the real cause was an
# encoding artifact.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?�•·])\s+|�")

# Hard ceiling for a single sentence. Legal prose runs long, but a segment
# past this is unsplit layout (a table dump or a run-on with no terminators),
# and must still be broken up rather than discarded — see _split_sentences.
_MAX_SENTENCE_CHARS = 600


def _split_sentences(text: str) -> list[str]:
    """Split `text` into sentences on punctuation boundaries.

    A chunk with no sentence-ending punctuation is treated as a single
    sentence (keeps single-clause chunks working). Empty segments are
    dropped.

    Segments longer than _MAX_SENTENCE_CHARS are further split on newlines and
    then on clause punctuation, because a chunk that never terminates a
    sentence (common in extracted tables and implementation matrices) would
    otherwise be dropped wholesale by the callers' length filters and count as
    an absence of governance.
    """
    if not text:
        return []
    out: list[str] = []
    for seg in _SENTENCE_SPLIT_RE.split(text):
        if not seg or not seg.strip():
            continue
        seg = seg.strip()
        if len(seg) <= _MAX_SENTENCE_CHARS:
            out.append(seg)
            continue
        # Too long to be one sentence — fall back to newline, then clause
        # boundaries, keeping any residue as a trimmed window.
        parts = [p.strip() for p in re.split(r"[\r\n]+", seg) if p.strip()]
        for p in parts:
            if len(p) <= _MAX_SENTENCE_CHARS:
                out.append(p)
                continue
            for clause in re.split(r"(?<=[;:])\s+", p):
                clause = clause.strip()
                if not clause:
                    continue
                while len(clause) > _MAX_SENTENCE_CHARS:
                    out.append(clause[:_MAX_SENTENCE_CHARS].strip())
                    clause = clause[_MAX_SENTENCE_CHARS:].strip()
                if clause:
                    out.append(clause)
    return out
