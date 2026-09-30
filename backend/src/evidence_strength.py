"""Governance evidence strength profiling — the substance of a dimension verdict.

WHY THIS EXISTS
───────────────
An existence check ("does ANY passage contain commitment language or a named
body?") does not discriminate between national AI documents: every strategy
names its own ministry, mentions a "programme" and promises to "develop"
something. A binding statutory duty and an aspirational bullet in a vision
statement would produce identical verdicts.

HOW IT WORKS
────────────
Governance provisions are scored on NORMATIVE FORCE — how strongly the text
actually governs — rather than on keyword presence. Each dimension-relevant
sentence is classified into one of five tiers, and the dimension's verdict is
computed from the DISTRIBUTION of tiers, not from any single match:

  T4 ENFORCEABLE  a duty backed by a consequence or supervisory power
                  (penalties, sanctions, audit, inspection, conformity
                  assessment, "empowers X to investigate")
  T3 OBLIGATORY   a binding duty on an identifiable duty-bearer
                  ("providers shall ensure", "the controller must notify",
                  "processing is prohibited without consent")
  T2 ASSIGNED     a named institution carrying a concrete function
                  ("MINICT shall lead the programme", "the Board publishes")
  T1 INTENTIONAL  a commitment to future action, no duty yet
                  ("the government will develop guidelines", "we recommend")
  T0 ASPIRATIONAL a principle, value, or vision statement
                  ("AI should be transparent", "AI must serve as an enabler")

Two exclusions run BEFORE tiering:

  1. THIRD-PARTY ATTRIBUTION. A sentence that attributes a provision to a
     DIFFERENT jurisdiction (a strategy's comparative literature review) is
     evidence about that jurisdiction, not about this document.
  2. STRUCTURAL NOISE. Contents listings, bare headings and definition-section
     boilerplate are not provisions.

DESIGN COMMITMENTS
──────────────────
  - No country, document, or expected score is referenced anywhere in this
    module. Differentiation must emerge from the text's own normative force,
    or it is not a real finding.
  - A named institution is NOT the top of the scale. A binding obligation on a
    regulated party outranks a named body with a vague mandate: naming a
    ministry is near-universal boilerplate in national strategies, whereas
    "providers shall disclose" is a genuine governance act.
  - Duty-bearer matters. "The Ministry will develop guidelines" is government
    promising itself something; "providers shall disclose" binds a regulated
    actor. Only the latter reaches T3.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from src.utils import ocr_flexible_fragment

if TYPE_CHECKING:
    from src.mechanism_matching import MechanismMatch

logger = structlog.get_logger()

# ── Tier constants ───────────────────────────────────────────────────────
TIER_ASPIRATIONAL = 0
TIER_INTENTIONAL = 1
TIER_ASSIGNED = 2
TIER_OBLIGATORY = 3
TIER_ENFORCEABLE = 4

TIER_LABELS = {
    TIER_ASPIRATIONAL: "Aspirational",
    TIER_INTENTIONAL: "Intentional",
    TIER_ASSIGNED: "Assigned",
    TIER_OBLIGATORY: "Obligatory",
    TIER_ENFORCEABLE: "Enforceable",
}


def _words(*items: str) -> re.Pattern:
    """Whole-word alternation pattern, tolerant of PDF intra-word spacing.

    Every term is compiled through ocr_flexible_fragment so that vocabulary
    shattered by PDF extraction ("deplo yers", "conf or mity", "high-r isk")
    still matches — see that function for why this is essential rather than
    defensive. Trailing '*' allows a stem match.
    """
    parts = []
    for it in items:
        if it.endswith("*"):
            parts.append(ocr_flexible_fragment(it[:-1]) + r"\w*")
        else:
            parts.append(ocr_flexible_fragment(it))
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.IGNORECASE)


# ── Duty-bearers ─────────────────────────────────────────────────────────
# A REGULATED party: an actor class the instrument can impose duties on. This
# is what separates a governance obligation from an internal government plan.
REGULATED_PARTY_RE = _words(
    "provider",
    "providers",
    "deployer",
    "deployers",
    "operator",
    "operators",
    "developer",
    "developers",
    "manufacturer",
    "manufacturers",
    "importer",
    "importers",
    "distributor",
    "distributors",
    "controller",
    "controllers",
    "processor",
    "processors",
    "data fiduciary",
    "data fiduciaries",
    "fiduciary",
    # PIPL's own name for the party it regulates (the GDPR's "controller").
    "personal information handler",
    "personal information handlers",
    "personal data handler",
    "personal data handlers",
    "algorithmic recommendation service provider",
    "algorithmic recommendation service providers",
    "deep synthesis service provider",
    "deep synthesis service providers",
    # Conformity-assessment third parties, which EU product law places duties on.
    "notified body",
    "notified bodies",
    "conformity assessment body",
    "conformity assessment bodies",
    "company",
    "companies",
    "firm",
    "firms",
    "enterprise",
    "enterprises",
    "organisation",
    "organisations",
    "organization",
    "organizations",
    "entity",
    "entities",
    "business",
    "businesses",
    "actor",
    "actors",
    "licensee",
    "licensees",
    "vendor",
    "vendors",
    "supplier",
    "suppliers",
    "platform",
    "platforms",
    "service provider",
    "service providers",
    "person",
    "persons",
    "party",
    "parties",
    "user",
    "users",
    "institution",
    "institutions",
)

# A GOVERNMENT / institutional actor. Naming one is necessary for T2 but is
# deliberately NOT sufficient for T3 — see the module docstring.
GOV_BODY_RE = _words(
    "ministry",
    "ministries",
    "minister*",
    "commission",
    "commissions",
    "board",
    "boards",
    "authority",
    "authorities",
    "agency",
    "agencies",
    "council",
    "councils",
    "committee",
    "committees",
    "directorate",
    "bureau",
    "inspectorate",
    "ombudsman",
    "ombudsmen",
    "regulator",
    "regulators",
    "commissioner",
    "commissioners",
    "supervisory authority",
    "data protection supervisor",
    "department",
    "departments",
    "office",
    "institute",
    "secretariat",
    "task force",
    "taskforce",
    "government",
    "state",
    "supervisory authority",
    "competent authority",
    "national authority",
)

# ── Normative-force markers ──────────────────────────────────────────────
# Binding modal verbs — the core signal of an imposed duty.
OBLIGATION_RE = _words(
    "shall",
    "must",
    "is required to",
    "are required to",
    "required to",
    "obliged to",
    "obligated to",
    "is obliged",
    "shall not",
    "must not",
)
# Prohibition / imposition verbs used in the third person by an instrument.
# Stemmed ("mandate*" not "mandates") because the subject is often plural
# ("the guidelines mandate X"). Stems that match mostly noise are spelled out
# instead: bar* matches "barriers", compel* "compelling", restrict*
# "restrictive". "require" is handled separately below, because its
# descriptive sense ("professionals require AI fluency") creates no duty.
IMPOSITION_RE = _words(
    "prohibit*",
    "mandate*",
    "impose*",
    "oblige*",
    "forbid*",
    "prescribe*",
    "restrict",
    "restricts",
    "restricted",
    "restricting",
    "restriction",
    "restrictions",
    "barred",
    "barring",
    "compels",
    "compelled",
    "shall ensure",
    "shall provide",
    "shall establish",
)

# "require" only in its imposing sense. The bare transitive use — "X requires
# Y" where Y is a thing someone needs — is descriptive and creates no duty.
DEONTIC_REQUIRE_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+required\s+to\b"
    r"|\bshall\s+requir\w*"
    r"|\brequire[sd]?\s+that\b"
    r"|\brequirements?\b"
    r"|\bas\s+required\b"
    r"|\brequired\s+(?:by|under|pursuant)\b",
    re.IGNORECASE,
)
# AUTHORITY verbs — powers that actually govern (Abbott/Snidal "delegation"
# with real teeth). An institution earns strength credit only when it wields
# one of these. Promotion verbs below do not count: policy-instrument research
# is explicit that a body mandated to "coordinate" or "promote" is delegation
# WITHOUT obligation — the weakest cell of the legalization cube, and the
# genre-defining convention of national strategy implementation matrices.
AUTHORITY_VERB_RE = _words(
    "license",
    "licenses",
    "licence",
    "licences",
    "licensing",
    "certify",
    "certifies",
    "certification",
    "accredit",
    "accredits",
    "inspect",
    "inspects",
    "inspection",
    "audit",
    "audits",
    "investigate",
    "investigates",
    "investigation",
    "sanction",
    "sanctions",
    "penalise",
    "penalize",
    "fine",
    "fines",
    "enforce",
    "enforces",
    "enforcement",
    "supervise",
    "supervises",
    "authorise",
    "authorises",
    "authorize",
    "authorizes",
    "approve",
    "approves",
    "approval",
    "prohibit",
    "prohibits",
    "revoke",
    "revokes",
    "suspend",
    "suspends",
    "require",
    "requires",
    "empowered to",
    "empowers",
    "shall have the power",
    "adjudicate",
    "impose",
    "imposes",
    # NOTE: a bare "order"/"orders" is deliberately excluded — "in order to"
    # is one of the commonest constructions in policy prose, and matching it
    # promoted an innovation-partnership sentence to a supervisory power.
    "order to stop",
    "cease and desist",
    "confiscate",
    "confiscates",
    "confiscation",
)

# A NAMED BINDING LEGAL INSTRUMENT (an Act, Law, Regulation, Decree...). A
# national strategy frequently governs a dimension by INCORPORATING AN
# EXISTING STATUTE BY REFERENCE rather than restating the duty itself —
# "AI privacy requirements are anchored in the Data Protection Act 2023,
# requiring adherence to data minimisation and purpose limitation". That is
# materially stronger than a bare principle (a real statute, with a real
# regulator, creating real duties) but weaker than this document imposing a
# duty of its own, so it lands at ASSIGNED rather than OBLIGATORY.
LEGAL_INSTRUMENT_RE = re.compile(
    r"\b(?:"
    r"[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,6}\s+"
    r"(?:Act|Law|Regulation|Decree|Statute|Ordinance|Code)\b"
    r"(?:\s*,?\s*(?:No\.?\s*)?\d{1,4})?"
    r"|\b(?:Act|Law|Regulation)\s+No\.?\s*\d{1,4}"
    r")",
)

# HEDGES — qualifiers that soften an otherwise-binding provision. Per the
# legalization literature these reduce obligation even when a hard modal is
# present ("shall, as appropriate, endeavour to..."), so a hedged obligation
# is demoted one tier rather than counted at full force.
HEDGE_RE = _words(
    "as appropriate",
    "where appropriate",
    "where feasible",
    "if feasible",
    "as far as possible",
    "to the extent possible",
    "where possible",
    "endeavour",
    "endeavor",
    "strive",
    "best efforts",
    "reasonable efforts",
    "voluntary",
    "voluntarily",
    "non-binding",
    "nonbinding",
    "encouraged to",
    "may wish to",
    "should consider",
    "where relevant",
    "as necessary",
    "insofar as",
    "subject to availability",
)

# Explicit non-binding self-characterisation. A document that declares itself
# advisory caps its own provisions: a "shall" inside a voluntary code is a
# recommendation, not a duty.
NONBINDING_DISCLAIMER_RE = re.compile(
    r"\b(?:"
    r"(?:this|these)\s+(?:document|guidelines?|framework|code|principles?)\s+"
    r"(?:is|are)\s+(?:not\s+legally\s+binding|non-?binding|voluntary|advisory)"
    r"|do(?:es)?\s+not\s+(?:impose|create)\s+(?:any\s+)?(?:legal\s+)?"
    r"(?:obligations?|binding|duties)"
    r"|no\s+legal\s+(?:force|effect|obligation)"
    r"|voluntary\s+(?:in\s+nature|framework|guidelines?|code)"
    # How instruments actually declare their own softness, e.g. "through soft
    # laws without any legally binding force".
    r"|without\s+any\s+legally\s+binding\s+(?:force|effect|nature|power)"
    r"|not\s+legally\s+binding"
    r"|(?:is|are)\s+not\s+(?:intended\s+to\s+be\s+)?(?:legally\s+)?binding"
    r"|(?:through|by|via)\s+soft\s+laws?\b"
    r"|voluntary\s+compliance\s+(?:rather\s+than|to\s+avoid|instead\s+of)"
    # NOT included: a bare "soft law", which appears in comparative
    # discussion inside binding instruments; "best practice", which appears
    # in every genre; a diagnosis such as "voluntary frameworks lack legal
    # enforceability"; and "voluntary basis", which the EU AI Act uses for
    # EARLY compliance with its binding obligations.
    r")\b",
    re.IGNORECASE,
)

# Commitment to future action — T1.
COMMITMENT_RE = _words(
    "will establish",
    "will develop",
    "will create",
    "will launch",
    "will implement",
    "will introduce",
    "will set up",
    "will publish",
    "will provide",
    "will support",
    "will promote",
    "will ensure",
    "shall be established",
    "to be established",
    "plans to",
    "intends to",
    "commits to",
    "committed to",
    "aims to",
    "seeks to",
    "proposes",
    "proposed",
    "recommends",
    "recommended",
    "recommendation",
    "is in favour of",
    "in favour of",
    "roadmap",
    "action plan",
    "will be developed",
    "will be implemented",
    "we recommend",
)
# Pure principle / value language — T0.
ASPIRATION_RE = _words(
    "should",
    "encourage",
    "encouraged",
    "encourages",
    "promote",
    "promotes",
    "foster",
    "fosters",
    "recognise",
    "recognises",
    "recognize",
    "recognizes",
    "acknowledge",
    "acknowledges",
    "importance",
    "principle",
    "principles",
    "value",
    "values",
    "vision",
    "mission",
    "aspire",
    "strive",
    "believe",
    "may",
    "could",
    "can",
)

# ── Exclusion 1: third-party jurisdiction attribution ────────────────────
# A sentence describing ANOTHER jurisdiction's framework is evidence about
# that jurisdiction, typically drawn from a strategy's comparative review.
FOREIGN_MARKER_RE = re.compile(
    r"\b("
    r"other (?:countries|jurisdictions|nations|states)"
    r"|(?:various|several|many|across) jurisdictions"
    r"|international (?:experience|practice|examples|benchmark)"
    r"|globally|worldwide|elsewhere"
    r"|(?:for|as an) example,"
    r"|case stud(?:y|ies)"
    r"|lessons (?:from|learned from)"
    r"|best practices? (?:from|in)"
    r")\b",
    re.IGNORECASE,
)

# Named jurisdictions and their instruments. A sentence naming one of these is
# comparative UNLESS it is this document's own jurisdiction (passed in at call
# time, so no jurisdiction is privileged in the code itself).
JURISDICTION_NAMES = (
    "european union",
    "eu",
    "european commission",
    "european parliament",
    "united states",
    "usa",
    "u.s.",
    "america",
    "american",
    "united kingdom",
    "uk",
    "britain",
    "british",
    "china",
    "chinese",
    "japan",
    "japanese",
    "korea",
    "korean",
    "singapore",
    "singaporean",
    "australia",
    "australian",
    "canada",
    "canadian",
    "india",
    "indian",
    "brazil",
    "brazilian",
    "germany",
    "german",
    "france",
    "french",
    "netherlands",
    "dutch",
    "rwanda",
    "rwandan",
    "kenya",
    "kenyan",
    "nigeria",
    "nigerian",
    "zambia",
    "zambian",
    "ghana",
    "ghanaian",
    "south africa",
    "estonia",
    "estonian",
    "finland",
    "finnish",
    "norway",
    "norwegian",
    "oecd",
    "unesco",
    "african union",
    "asean",
    "g7",
    "g20",
)

# Instrument nouns that, next to a jurisdiction name, mark an external
# framework reference ("Australia's 2021 AI Action Plan", "the EU AI Act").
FOREIGN_INSTRUMENT_RE = _words(
    "act",
    "regulation",
    "directive",
    "law",
    "strategy",
    "framework",
    "guidelines",
    "policy",
    "plan",
    "code",
    "standard",
    "recommendation",
    "principles",
    "approach",
    "model",
)

# ── Exclusion 2: structural / non-provision text ─────────────────────────
STRUCTURAL_NOISE_RE = re.compile(
    r"^\s*(?:"
    r"table of contents?"
    r"|contents?"
    r"|executive summary"
    r"|list of (?:tables|figures|abbreviations|acronyms)"
    r"|annex(?:ure)?\b"
    r"|appendix\b"
    r"|glossary"
    r"|key definitions?"
    r"|this section defines"
    r"|definitions?\s*$"
    r"|bibliography|references"
    r"|figure \d|table \d"
    r")",
    re.IGNORECASE,
)


@dataclass
class ScoredSentence:
    """One dimension-relevant sentence with its normative-force classification."""

    text: str
    tier: int
    duty_bearer: str  # "regulated" | "government" | "none"
    has_enforcement: bool
    excluded: str = ""  # non-empty = why it was excluded from scoring

    @property
    def counts(self) -> bool:
        return not self.excluded


@dataclass
class EvidenceProfile:
    """Aggregate normative-force profile for one dimension of one document."""

    dimension: str = ""
    sentences: list[ScoredSentence] = field(default_factory=list)
    tier_counts: dict[int, int] = field(default_factory=dict)
    max_tier: int = -1
    n_enforceable: int = 0
    n_binding: int = 0  # tier >= 3
    n_institutional: int = 0  # tier >= 2
    n_commitment: int = 0  # tier >= 1
    n_scored: int = 0
    n_excluded_foreign: int = 0
    n_excluded_structural: int = 0

    def summary(self) -> str:
        """Short auditable description of what the evidence actually contains."""
        if not self.n_scored:
            bits = []
            if self.n_excluded_foreign:
                bits.append(
                    f"{self.n_excluded_foreign} passage(s) described other "
                    "jurisdictions' frameworks rather than this document's own "
                    "provisions"
                )
            if self.n_excluded_structural:
                bits.append(
                    f"{self.n_excluded_structural} passage(s) were contents "
                    "listings or headings rather than provisions"
                )
            tail = ("; " + "; ".join(bits)) if bits else ""
            return f"No governing provision found for this dimension{tail}."
        parts = [
            f"{self.n_scored} dimension-relevant provision(s)",
            f"strongest is {TIER_LABELS.get(self.max_tier, 'n/a')}",
        ]
        if self.n_binding:
            parts.append(f"{self.n_binding} binding")
        if self.n_enforceable:
            parts.append(f"{self.n_enforceable} enforceable")
        if self.n_excluded_foreign:
            parts.append(f"{self.n_excluded_foreign} excluded as another jurisdiction's framework")
        return "; ".join(parts) + "."


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def is_structural_noise(sentence: str) -> bool:
    """True when the sentence is a contents listing, heading, or definitions stub."""
    s = _norm(sentence)
    if not s:
        return True
    if STRUCTURAL_NOISE_RE.match(s):
        return True
    # A "sentence" that is mostly digits/page numbers is a contents line, even
    # when it starts with prose (PDF extraction concatenates these).
    tokens = s.split()
    if len(tokens) >= 6:
        numeric = sum(1 for t in tokens if t.strip(".,;:").isdigit())
        if numeric / len(tokens) >= 0.30:
            return True
    return False


def is_third_party_attribution(sentence: str, own_jurisdiction: str = "") -> bool:
    """True when the sentence describes ANOTHER jurisdiction's framework.

    `own_jurisdiction` is this document's own country/bloc (from the workspace
    record). It is used only to avoid discounting self-reference — no
    jurisdiction is treated as stronger or weaker anywhere in this module.
    """
    s = _norm(sentence).lower()
    if not s:
        return False

    own = (own_jurisdiction or "").strip().lower()
    own_tokens = {t for t in re.split(r"[^a-z]+", own) if len(t) > 2}

    if FOREIGN_MARKER_RE.search(s):
        return True

    # Does the sentence speak in this document's OWN voice? A provision the
    # document enacts for itself reads "we will…", "this Policy requires…",
    # or names its own jurisdiction. Comparative passages in a literature
    # review do none of these — they narrate what someone else did.
    self_voice = bool(
        re.search(
            r"\b(?:we|our|this (?:policy|strategy|act|regulation|framework|"
            r"guideline|document|law|bill|code))\b",
            s,
        )
    )
    if own_tokens and any(t in s for t in own_tokens):
        self_voice = True

    for name in JURISDICTION_NAMES:
        if name in own or (own_tokens and any(t in name for t in own_tokens)):
            continue  # this document's own jurisdiction — self-reference is fine
        pat = re.compile(r"\b" + re.escape(name) + r"(?:'s|’s)?\b", re.IGNORECASE)
        m = pat.search(s)
        if not m:
            continue
        # Possessive ("Australia's ... Plan") or a nearby instrument noun is
        # conclusive on its own.
        window = s[m.start() : m.end() + 90]
        if "'s" in m.group(0) or "’s" in m.group(0):
            return True
        if FOREIGN_INSTRUMENT_RE.search(window):
            return True
        # Otherwise: a foreign jurisdiction named in a sentence that never
        # speaks in this document's own voice is a comparative example, not a
        # provision — "In Canada, the Office of the Privacy Commissioner
        # launched an investigation…" carries a real institution and real
        # enforcement verbs, but describes a different country.
        if not self_voice:
            return True
    return False


def detect_nonbinding_document(sample_texts: Iterable[str]) -> bool:
    """True when the document declares itself voluntary / non-binding.

    Checked once per document against a corpus sample rather than per
    sentence, because the disclaimer usually appears once in a preface and
    governs every provision that follows.

    A false positive here is catastrophic and silent: the flag caps EVERY
    provision in the document at T1, so every dimension collapses to Emerging.
    So the disclaimer is overruled when the same sample shows the instrument
    carrying its own supervisory or penalty machinery. A document that fines
    people is not voluntary, whatever one of its recitals says.
    """
    # Imported locally: the regime detector lives in src/grading.py, which
    # imports this module, so a top-level import would be circular.
    from src.grading import detect_enforcement_regime

    texts = [t for t in sample_texts if t]
    if not any(NONBINDING_DISCLAIMER_RE.search(t) for t in texts):
        return False
    if detect_enforcement_regime(texts):
        logger.info("nonbinding_disclaimer_overruled_by_enforcement_regime")
        return False
    return True


def _split_sentences_for_scoring(text: str) -> list[str]:
    """Cheap sentence split for the document-level sweep.

    Deliberately not the full deterministic splitter: this only needs enough
    granularity to classify normative force, and it runs over a whole-document
    sample rather than a retrieved pool.
    """
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p for p in (x.strip() for x in parts) if 40 <= len(p) <= 600]


# ── Profile → verdict mappings ───────────────────────────────────────────
# Both mappings read the SAME profile but measure different things, so a
# dimension can be broadly addressed yet shallowly implemented (Covered /
# Emerging) or narrowly addressed but rigorously so (Partial / Operationalized).


def meets_force_bar(profile: EvidenceProfile) -> bool:
    """Does the document actually impose governing force on this dimension?

    ONE definition, used by BOTH coverage_from_profile and
    depth_from_profile, so the two can never disagree about whether a
    dimension is governed.

    The bar is deliberately NOT `n_binding >= 1`. The counters are cumulative
    (n_binding counts tier>=3, n_institutional tier>=2), so any lone binding
    sentence also lifts every weaker counter — pairing a single duty with
    ENFORCEMENT is the one genuinely independent signal available.
    """
    return profile.n_binding >= 2 or (profile.n_binding >= 1 and profile.n_enforceable >= 1)


#: Below this share of a dimension's mechanisms, a force-bar pass is held at
#: Partial. See the MECHANISM BREADTH GATE comment in coverage_from_profile.
MECHANISM_FLOOR = 1 / 3


def coverage_from_profile(
    profile: EvidenceProfile,
    mechanisms: MechanismMatch | None = None,
    mechanism_floor: float = MECHANISM_FLOOR,
) -> tuple[str, str]:
    """Map an evidence profile to a Coverage level. Returns (level, rationale).

    Coverage answers: does the document actually govern this dimension?

    """
    if profile.n_scored == 0:
        return "Missing", profile.summary()

    # Covered: the dimension is genuinely governed — several binding duties, a
    # binding duty carried by institutional machinery, or a sustained body of
    # concrete commitments. Pure aspiration can NEVER reach Covered no matter
    # how often it is repeated: a document that only ever says "AI should be
    # fair" does not govern fairness, it endorses it.
    # The force bar itself is meets_force_bar.
    force_bar = meets_force_bar(profile)
    # MECHANISM BREADTH GATE (downgrade only, never a raise).
    #
    # Normative force and mechanism breadth are orthogonal: a document can
    # clear the force bar on one narrow provision while providing almost none
    # of what the dimension needs (a single enforceable privacy provision, and
    # no consent rule, minimisation or data-subject rights). The gate holds
    # such a verdict at Partial. It never promotes, so mechanism vocabulary
    # can never substitute for governing force.
    #
    # Zero detections is not evidence of absence: mechanism matching is
    # imprecise, so a zero count cannot distinguish "no mechanisms" from "the
    # detector found none". The gate demotes only on a measured shortfall.
    if force_bar and mechanisms is not None and mechanisms.total and mechanisms.met:
        if (mechanisms.met / mechanisms.total) < mechanism_floor:
            # Named, not counted: the absent mechanisms are ordered by how many
            # reference instruments expect each, so the sentence opens with the
            # gap most widely agreed to matter.
            from src.framework_salience import framework_count, rank_absent

            ranked = rank_absent(profile.dimension, mechanisms.absent)
            corpus = framework_count()
            if ranked and corpus:
                missing = "; ".join(
                    f"{row['mechanism']} (expected by {row['expected_by']} of {corpus} "
                    f"reference instruments)"
                    for row in ranked[:3]
                )
            else:
                missing = ", ".join(mechanisms.absent[:4])
            return "Partial", (
                f"The document imposes binding requirements for this dimension "
                f"({profile.n_binding} binding provision(s)), but leaves "
                f"{len(mechanisms.absent)} of the {mechanisms.total} governance "
                f"mechanisms this dimension calls for without any supporting "
                f"provision" + (f" — most notably {missing}." if missing else ".")
            )
    if force_bar:
        return "Covered", (
            f"The document imposes binding requirements for this dimension "
            f"({profile.n_binding} binding provision(s)"
            + (
                f", {profile.n_enforceable} backed by enforcement or oversight"
                if profile.n_enforceable
                else ""
            )
            + ")."
        )
    # There is deliberately no "breadth" path to Covered: many commitments
    # with no binding duty is what depth_from_profile's Emerging stage
    # represents, and pure aspiration never reaches Covered.

    # Partial: genuine governance activity, but thin.
    if profile.n_binding >= 1:
        return "Partial", (
            "The document imposes a binding requirement for this dimension, but "
            "it stands alone rather than forming a developed regime."
        )

    if profile.n_institutional >= 1 or profile.n_commitment >= 1:
        return "Partial", (
            "The document commits to acting on this dimension"
            + (" and assigns it to a named institution" if profile.n_institutional else "")
            + ", but imposes no binding requirement on anyone."
        )
    if profile.n_scored >= 4:
        return "Partial", (
            "The dimension is discussed in the document, but only as a "
            "principle — no commitment to act, responsible institution, or "
            "requirement was found."
        )

    return "Missing", (
        "The document refers to this dimension only in passing — no binding "
        "requirement, named responsible institution, or concrete commitment to "
        "act was found."
    )


def describe_risk_basis(
    coverage: str,
    profile: EvidenceProfile,
    mechanisms: MechanismMatch | None = None,
) -> tuple[str, str]:
    """Say WHY this dimension carries risk, and what follows if it is not fixed.

    Returns (risk_basis, potential_consequence).

    The risk LEVEL is decided elsewhere (compute_risk) by coverage tier and
    cluster compounding. This supplies the sentence a reader needs: the shape
    of the weakness. Duties that nothing enforces behave differently from
    duties that do not exist, and both differ from a dimension covered in
    principle only.

    Everything here is derived from counters already computed for the verdict,
    so it introduces no new judgement and cannot disagree with the label.
    """
    absent = list(mechanisms.absent) if mechanisms is not None else []
    absent_str = ", ".join(absent[:3]) if absent else ""

    if coverage == "Covered":
        if profile.n_enforceable >= 2:
            basis = (
                f"The document imposes {profile.n_binding} binding requirement(s) "
                f"here, {profile.n_enforceable} of them backed by supervisory or "
                "enforcement powers."
            )
            consequence = (
                "Residual exposure is limited to implementation quality rather "
                "than to the rules themselves."
            )
        else:
            basis = (
                f"The document imposes {profile.n_binding} binding requirement(s) "
                "here, but little of it carries enforcement or oversight language."
            )
            consequence = (
                "Duties exist on paper; without a supervisory route, compliance "
                "depends on the goodwill of the parties they bind."
            )
        if absent_str:
            consequence += f" Still unaddressed: {absent_str}."
        return basis, consequence

    if coverage == "Partial":
        if profile.n_binding >= 1 and profile.n_enforceable == 0:
            basis = (
                f"{profile.n_binding} binding requirement(s) exist with no "
                "enforcement, audit or redress machinery behind them."
            )
            consequence = (
                "A duty nobody supervises is difficult to rely on: non-compliance "
                "surfaces only after harm has already occurred."
            )
        elif profile.n_binding == 0 and profile.n_institutional >= 1:
            basis = (
                "The dimension is assigned to a named body, but no binding "
                "requirement is placed on anyone."
            )
            consequence = (
                "Responsibility without obligation leaves the body free to act, "
                "and equally free not to."
            )
        else:
            basis = (
                "The dimension is acknowledged as a commitment rather than "
                "translated into requirements."
            )
            consequence = (
                "Stated intent does not bind future decisions; the commitment can "
                "lapse without any rule being broken."
            )
        if absent_str:
            basis += f" Not addressed: {absent_str}."
        return basis, consequence

    # Missing
    basis = (
        "No binding requirement, responsible institution or concrete commitment "
        "for this dimension was found in the document."
    )
    consequence = (
        "The dimension is left to sectoral regulators or to the discretion of "
        "deployers, with no national position to appeal to."
    )
    if absent_str:
        basis += f" Absent mechanisms include: {absent_str}."
    return basis, consequence


def depth_from_profile(
    profile: EvidenceProfile,
    document_enforcement_regime: bool = False,
) -> tuple[str, str]:
    """Map an evidence profile to a Implementation Depth stage.

    Implementation depth answers a different question from coverage: how far has the
    governance been built out — from stated intent to enforced machinery?
    """
    if profile.n_scored == 0:
        return "Unaddressed", profile.summary()

    # Institutionalized: binding duties BACKED by enforcement.
    #
    # Enforcement counts either way it can genuinely exist. Restated inside the
    # dimension's own provisions (>=2 enforceable sentences), or supplied by the
    # document as a whole — a regulation's penalties and supervisory powers
    # apply to a breach of any obligation in it, so a dimension carrying real
    # duties inside such an instrument IS enforcement-backed even when its own
    # sentences do not repeat the machinery.
    #
    # The document-level route still requires the dimension to carry its own
    # duties (>=2 binding) AND at least one enforcement signal of its own, so a
    # dimension that is merely mentioned inside a strong regulation cannot ride
    # the document's regime to the top stage. See detect_enforcement_regime.
    if profile.n_binding >= 2 and (
        profile.n_enforceable >= 2 or (document_enforcement_regime and profile.n_enforceable >= 1)
    ):
        backing = (
            f"{profile.n_enforceable} provision(s) carry supervisory or consequence language"
            if profile.n_enforceable >= 2
            else "the instrument's own supervisory and penalty machinery applies to these duties"
        )
        return "Institutionalized", (
            f"Binding requirements are paired with enforcement, oversight or "
            f"redress machinery ({backing})."
        )
    # Operationalized clears the SAME force bar as Covered: a single
    # unenforced duty is not a governance regime that is built out and running.
    if meets_force_bar(profile):
        return "Operationalized", (
            "Binding requirements exist, but without the enforcement, audit or "
            "redress machinery that would make them self-sustaining."
        )
    # Delegated separates "someone owns this" from "someone said this matters"
    # (see DEPTH_STAGE_SCORE in gap_analyzer).
    if profile.n_binding >= 1:
        return "Delegated", (
            "A binding requirement exists but stands alone, with neither a "
            "second duty nor any enforcement behind it — the dimension has "
            "started to be governed, not yet operated."
        )
    if profile.n_institutional >= 1:
        return "Delegated", (
            "An institution is named to carry this dimension, but no binding "
            "requirement has been created for it to enforce."
        )
    if profile.n_commitment >= 1 or profile.n_scored >= 4:
        return "Emerging", (
            "The dimension is recognised and addressed, but no institution has "
            "been made responsible for it and no binding requirement exists."
        )
    return "Unaddressed", (
        "Only passing references were found — the dimension has not been "
        "translated into commitments, institutions or requirements."
    )


# ── Why the reference corpus does not score sentence similarity ─────────
#
# Coverage and depth are computed from the uploaded document's OWN
# provisions. Comparing document prose to framework prose (cosine over
# embeddings) was measured and rejected: it is anti-correlated with governance
# strength, because a soft-law guideline written in the frameworks' own
# principles voice embeds closer to them than a statute's "Providers shall..."
# phrasing. Prose similarity measures how a document is WRITTEN, not what it
# REQUIRES. The corpus informs the verdict at the mechanism level instead.


# ── Required governance mechanisms per dimension ──────────────────────────
# The concrete mechanisms the ingested reference corpus (UNESCO Recommendation,
# OECD AI Principles, NIST AI RMF, CDEI, ICO/Turing, UN Global Digital Compact)
# recurrently requires for each dimension.
#
# Matching happens on what a provision DOES, via the same tier classifier used
# for coverage, so a statute phrased "providers shall log" and a strategy
# phrased "we will establish audit trails" are both recognised as the
# audit-trail mechanism while still being graded differently on force.
#
# Hardcoded rather than auto-extracted, deliberately: an explicit table can be
# inspected and argued with.
DIMENSION_MECHANISMS: dict[str, dict[str, tuple[str, ...]]] = {
    "Transparency": {
        "user disclosure": ("inform", "notify", "disclos", "made aware", "label"),
        "decision explanation": ("explain", "explanab", "explanation", "rationale", "interpretab"),
        "model documentation": (
            "technical documentation",
            "model card",
            "datasheet",
            "document the",
            "documentation",
        ),
        "audit trail / logging": (
            "logging",
            "logged",
            "log of",
            "record keeping",
            "records",
            "audit trail",
            "traceab",
        ),
        "public registry": ("registry", "register", "publicly available", "publish"),
        "capability & limitation disclosure": (
            "limitation",
            "capabilit",
            "intended purpose",
            "performance",
        ),
    },
    "Accountability": {
        "liability allocation": (
            "liabilit",
            "liable",
            "responsib",
            "accountable for",
            "answerable",
        ),
        "grievance / redress": ("grievance", "redress", "complaint", "appeal", "remedy"),
        "named responsible body": ("authority", "commission", "board", "regulator", "supervisory"),
        "incident reporting": ("incident", "report serious", "notify the authorit", "malfunction"),
        "audit requirement": ("audit", "inspect", "conformity assessment", "certification"),
        "sanctions / penalties": (
            "penalt",
            "sanction",
            "fines",
            "administrative fine",
            "enforcement action",
        ),
    },
    "Privacy": {
        "consent": ("consent", "opt-in", "permission"),
        "data minimisation": ("minimis", "minimiz", "only the data", "necessary data"),
        # Statutes name these rights and duties in their own terms: Japan's
        # APPI says "purpose of use" and lets the "identifiable person" request
        # disclosure, correction or deletion, never "data subject".
        "purpose limitation": (
            "purpose limitation",
            "specified purpose",
            "compatible purpose",
            "purpose of use",
            "purpose of utiliz",
            "purpose of utilis",
            "specify the purpose",
        ),
        "anonymisation / PETs": (
            "anonymis",
            "anonymiz",
            "pseudonym",
            "differential privacy",
            "encryption",
            "privacy-enhancing",
            "privacy-preserving",
        ),
        "data subject rights": (
            "data subject",
            "right to erasure",
            "rectification",
            "access their",
            "portab",
            "right of access",
            "right to access",
            "right to object",
            "right to correction",
            "request disclosure",
            "request correction",
            "request deletion",
            "request erasure",
        ),
        "privacy by design": ("privacy by design", "data protection by design", "by default"),
        "impact assessment": ("impact assessment", "dpia", "privacy assessment"),
    },
    "Safety": {
        "risk assessment": (
            "risk assessment",
            "risk management",
            "impact assessment",
            "identify risk",
        ),
        "pre-deployment testing": ("testing", "test", "validat", "evaluat", "red team", "trial"),
        "robustness requirement": ("robust", "resilien", "accuracy", "reliab"),
        "incident monitoring": ("incident", "monitor", "malfunction", "failure"),
        "post-market monitoring": (
            "post-market",
            "after deployment",
            "ongoing monitoring",
            "continuous",
        ),
        "human failsafe / shutdown": (
            "fail-safe",
            "failsafe",
            "shutdown",
            "circuit breaker",
            "stop button",
            "kill switch",
        ),
    },
    "Human Autonomy": {
        "human-in-the-loop": (
            "human-in-the-loop",
            "human in the loop",
            "human oversight",
            "human review of",
        ),
        "right to human review": (
            "right to human",
            "request human",
            "human intervention",
            "contest",
        ),
        "override capability": ("override", "intervene", "disregard", "reverse the decision"),
        "prohibition of manipulation": ("manipulat", "subvert", "exploit vulnerab", "deceptive"),
        "meaningful control": (
            "meaningful control",
            "human control",
            "human agency",
            "final decision",
        ),
    },
    "Inclusivity": {
        "disability accessibility": (
            "persons with disabilities",
            "accessibility for",
            "accessible design",
            "universal design",
        ),
        "demographic representation": (
            "representat",
            "underrepresent",
            "demographic",
            "diverse group",
        ),
        "stakeholder participation": ("stakeholder", "consultation", "participat", "civil society"),
        "digital divide": ("digital divide", "underserved", "rural", "marginalis", "marginaliz"),
        "language / localisation": ("language", "local language", "linguistic", "translat"),
    },
    "Fairness": {
        "bias testing": (
            "bias test",
            "bias assessment",
            "bias audit",
            "test for bias",
            "detect bias",
            "bias detection",
        ),
        "protected characteristics": (
            "protected characteristic",
            "racial",
            "gender",
            "ethnicit",
            "disabilit",
            "age group",
            "older persons",
            # Groups every legal tradition protects, named as that tradition
            # names them. The EU/GDPR vocabulary above misses the way China's
            # Algorithmic Recommendations Provisions do the same work —
            # Article 18 on minors, Article 19 on seniors — and those are
            # binding articles with a regulator behind them.
            "minors",
            "children",
            "elderly",
            "seniors",
            "vulnerable group",
        ),
        "fairness metrics": (
            "demographic parity",
            "equalis",
            "disparate impact",
            "fairness metric",
            "equal opportunity",
        ),
        # Consumer-law phrasing carries the same duty: China states it as
        # "protect the consumers' rights to fair transactions". A duty not to
        # treat people unfairly is that duty whatever body of law it sits in.
        "non-discrimination duty": (
            "discriminat",
            "non-discriminat",
            "equal treatment",
            "fair treatment",
            "fair transaction",
            "fair and equitable",
            "equitable treatment",
        ),
        "bias mitigation": ("mitigat", "correct", "remediat", "debias"),
    },
    "Environmental Sustainability": {
        "energy reporting": (
            "energy consumption",
            "energy use",
            "energy efficiency",
            "power consumption",
        ),
        "carbon disclosure": ("carbon", "emission", "co2", "greenhouse", "footprint"),
        "compute efficiency": (
            "computational",
            "compute",
            # Both spacings: documents write "resource-efficient" either way.
            "resource efficien",
            "resource-efficien",
            "model size",
            "optimis",
            "optimiz",
        ),
        "e-waste / hardware lifecycle": (
            "e-waste",
            "electronic waste",
            "hardware",
            "lifecycle",
            "disposal",
            "recycl",
        ),
        "green procurement / energy": ("renewable", "green energy", "clean energy", "procurement"),
    },
}


def detect_mechanisms(
    scored_sentences: list[ScoredSentence],
    dimension: str,
) -> MechanismMatch:
    """Which required mechanisms the document provides, and how strongly.

    The implementation lives in src/mechanism_matching.py, imported inside the
    function because that module reads DIMENSION_MECHANISMS from here.
    """
    from src.mechanism_matching import detect_mechanisms as _detect

    return _detect(scored_sentences, dimension)
