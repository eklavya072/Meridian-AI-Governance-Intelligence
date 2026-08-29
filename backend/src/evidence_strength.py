"""Governance evidence strength profiling — the substance of a dimension verdict.

WHY THIS EXISTS
───────────────
The original coverage ladder (R1/R2 in deterministic.py) asked one question per
dimension: "does ANY retrieved chunk contain commitment language / a named body
next to a programme word?" That is an existence check over the whole document,
and it does not discriminate between national governance frameworks, because
essentially EVERY national AI document satisfies it somewhere:

  - every strategy names its own ministry (implementation matrices are built
    from ministry names),
  - every strategy contains "programme", "initiative", "roadmap",
  - every strategy promises to "develop" or "establish" something.

So the ladder raised nearly every dimension of nearly every document to
Covered, and maturity — which was derived from the same binary flags — followed
it up to Institutionalized. A binding statutory duty and an aspirational bullet
in a vision statement produced identical verdicts.

WHAT REPLACES IT
────────────────
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

Two exclusions run BEFORE tiering, because both were confirmed to be inflating
real verdicts in this pipeline:

  1. THIRD-PARTY ATTRIBUTION. Kenya's entire retrieved Transparency evidence
     described Australia's AI Action Plan and other jurisdictions' privacy
     enforcement authorities — comparative background from the strategy's
     literature-review section, scored as though it were Kenya's own
     governance. A sentence that attributes a provision to a DIFFERENT
     jurisdiction is evidence about that jurisdiction, not about this
     document's governance.
  2. STRUCTURAL NOISE. Rwanda's Environmental Sustainability evidence was
     table-of-contents lines and a vision statement. Contents listings,
     bare headings and definition-section boilerplate are not provisions.

DESIGN COMMITMENTS
──────────────────
  - No country, document, or expected score is referenced anywhere in this
    module. Differentiation must emerge from the text's own normative force,
    or it is not a real finding.
  - A named institution is NOT the top of the scale. A binding obligation on a
    regulated party outranks a named body with a vague mandate: naming a
    ministry is near-universal boilerplate in national strategies, whereas
    "providers shall disclose" is a genuine governance act. The old ladder had
    this backwards (a named body was R2's gate).
  - Duty-bearer matters. "The Ministry will develop guidelines" is government
    promising itself something; "providers shall disclose" binds a regulated
    actor. Only the latter reaches T3.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from src.utils import ocr_flexible_fragment

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
# ("the guidelines mandate X", "the provisions require Y") — an exact-form
# list tuned to singular subjects ("the Act mandates X") silently missed
# these. Confirmed live: "the guidelines mandate the implementation of
# human-in-the-loop mechanisms" scored as unowned aspiration (T0) purely
# because "mandates" didn't match "mandate".
IMPOSITION_RE = _words(
    "prohibit*",
    "requir*",
    "mandate*",
    "impose*",
    "oblige*",
    "restrict*",
    "forbid*",
    "bar*",
    "prescribe*",
    "compel*",
    "shall ensure",
    "shall provide",
    "shall establish",
)
# Consequence / supervisory power — what lifts an obligation to enforceable.
ENFORCEMENT_RE = _words(
    "penalty",
    "penalties",
    "fine",
    "fines",
    "sanction",
    "sanctions",
    "liable",
    "liability",
    "enforcement",
    "enforce",
    "enforced",
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
    "revocation",
    "suspend",
    "suspension",
    "corrective action",
    "redress",
    "grievance",
    "complaint",
    "complaints",
    "appeal",
    "remedy",
    "remedies",
    "compensation",
    "prosecut*",
    "offence",
    "offense",
    "non-compliance",
    "noncompliance",
    "breach",
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
)
# PROMOTION verbs — coordination/advocacy mandates. Explicitly NOT strength.
PROMOTION_VERB_RE = _words(
    "coordinate",
    "coordinates",
    "coordination",
    "promote",
    "promotes",
    "promotion",
    "facilitate",
    "facilitates",
    "encourage",
    "encourages",
    "raise awareness",
    "advocate",
    "advocates",
    "support",
    "supports",
    "convene",
    "convenes",
    "collaborate",
    "collaborates",
    "engage",
    "champion",
    "champions",
    "spearhead",
    "lead",
    "leads",
)

# A NAMED BINDING LEGAL INSTRUMENT (an Act, Law, Regulation, Decree...). A
# national strategy frequently governs a dimension by INCORPORATING AN
# EXISTING STATUTE BY REFERENCE rather than restating the duty itself —
# "AI privacy requirements are anchored in the Data Protection Act 2023,
# requiring adherence to data minimisation and purpose limitation". That is
# materially stronger than a bare principle (a real statute, with a real
# regulator, creating real duties) but weaker than this document imposing a
# duty of its own, so it lands at ASSIGNED rather than OBLIGATORY.
# Confirmed live: Nigeria's Privacy and India's Human Autonomy both scored as
# unowned aspiration despite citing genuine binding instruments, because the
# grammatical subject was the statute, not a regulated party.
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
    r"|voluntary\s+(?:in\s+nature|basis|framework|guidelines?|code)"
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
# that jurisdiction. Confirmed live: Kenya's Transparency evidence was
# entirely about Australia's AI Action Plan and foreign privacy-enforcement
# authorities, drawn from the strategy's comparative literature review.
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
        # provision. This is the form that slipped through before — narrative
        # reporting such as "In Canada, the Office of the Privacy Commissioner
        # launched an investigation…" carries a real institution and real
        # enforcement verbs, so it scored as top-tier domestic governance
        # while describing an entirely different country.
        if not self_voice:
            return True
    return False


def _has_real_duty_bearer(sentence: str) -> str:
    """Classify the duty-bearer: 'regulated' | 'government' | 'none'."""
    if REGULATED_PARTY_RE.search(sentence):
        return "regulated"
    if GOV_BODY_RE.search(sentence):
        return "government"
    return "none"


def classify_sentence(
    sentence: str,
    dimension: str = "",
    own_jurisdiction: str = "",
    document_is_nonbinding: bool = False,
) -> ScoredSentence:
    """Classify one sentence's normative force.

    Exclusions run first: a passage about another jurisdiction, or a contents
    listing, is not evidence of THIS document's governance at any tier.

    The tier rules follow the legalization literature's separation of
    OBLIGATION from DELEGATION:

      - A binding duty on an EXTERNAL, regulated duty-bearer is the strongest
        ordinary provision (T3), and T4 when a consequence or supervisory
        power attaches.
      - A government body directing ITSELF caps at T2 no matter how hard the
        modal ("the Ministry shall develop guidelines" is a plan, not a duty —
        there is no correlative right-holder). This single rule is what stops
        strategy implementation matrices from outranking statutes.
      - A government body earns above T2 only when it wields an AUTHORITY
        power (licence, certify, inspect, investigate, sanction, prohibit) —
        not a coordination or promotion mandate.
      - A hedged provision ("shall, where feasible, endeavour to") is demoted
        one tier, and every provision in a self-declared voluntary document is
        capped at T1.
    """
    s = _norm(sentence)

    if is_structural_noise(s):
        return ScoredSentence(s, TIER_ASPIRATIONAL, "none", False, excluded="structural")
    if is_third_party_attribution(s, own_jurisdiction):
        return ScoredSentence(s, TIER_ASPIRATIONAL, "none", False, excluded="foreign")

    # Both actor kinds are tracked independently: one sentence can name a
    # supervisory body AND the parties it regulates ("the Board may investigate
    # and impose penalties on any entity…"). Collapsing to a single bearer
    # label lost the government-authority reading whenever a regulated noun
    # also appeared, under-scoring exactly the strongest provisions.
    has_regulated = bool(REGULATED_PARTY_RE.search(s))
    has_gov = bool(GOV_BODY_RE.search(s))
    bearer = "regulated" if has_regulated else ("government" if has_gov else "none")

    has_enf = bool(ENFORCEMENT_RE.search(s))
    has_obligation = bool(OBLIGATION_RE.search(s)) or bool(IMPOSITION_RE.search(s))
    has_commitment = bool(COMMITMENT_RE.search(s))
    has_authority = bool(AUTHORITY_VERB_RE.search(s))
    hedged = bool(HEDGE_RE.search(s))

    tier = TIER_ASPIRATIONAL
    enforcement_credit = False

    if has_gov and has_authority and has_enf:
        # Supervisory machinery: a body vested with a real power over others
        # ("empowers the Board to investigate", "the Authority may inspect").
        tier = TIER_ENFORCEABLE
        enforcement_credit = True
    elif has_regulated and has_obligation:
        # A duty imposed on an external actor — the genuine governance act.
        tier = TIER_ENFORCEABLE if has_enf else TIER_OBLIGATORY
        enforcement_credit = has_enf
    elif has_gov and has_authority:
        tier = TIER_OBLIGATORY
    elif has_gov and (has_commitment or has_obligation):
        # Self-directed: institutional ownership exists, but the government is
        # the addressee of its own instruction. Capped at Assigned regardless
        # of modal force.
        tier = TIER_ASSIGNED
    elif has_regulated and has_enf:
        tier = TIER_OBLIGATORY
        enforcement_credit = True
    elif LEGAL_INSTRUMENT_RE.search(s) and (has_obligation or has_enf):
        # Governs by reference to an existing statute (see
        # LEGAL_INSTRUMENT_RE): real binding law is invoked, but this
        # document is not itself the instrument imposing the duty.
        tier = TIER_ASSIGNED
    elif has_commitment:
        tier = TIER_INTENTIONAL
    elif has_regulated and ASPIRATION_RE.search(s):
        # A RECOMMENDED duty on an external actor ("providers should disclose
        # the limitations of the system"). Weaker than an obligation, but
        # materially stronger than an unaddressed principle ("AI should be
        # transparent") because it names who is expected to act — this is the
        # characteristic provision of a soft-law instrument, and without this
        # branch such instruments score as though they said nothing at all.
        tier = TIER_INTENTIONAL

    # Hedges soften an otherwise-BINDING provision by one tier. They are not
    # applied at or below Intentional: a recommendation ("actors should
    # consider…") is already soft, and the hedge lexicon overlaps the
    # recommendation lexicon ("should consider"), so demoting there would
    # double-count the same softness and erase the provision entirely.
    if hedged and tier > TIER_INTENTIONAL:
        tier -= 1
        if tier < TIER_ENFORCEABLE:
            enforcement_credit = False

    # A self-declared voluntary/advisory instrument cannot create duties.
    if document_is_nonbinding and tier > TIER_INTENTIONAL:
        tier = TIER_INTENTIONAL
        enforcement_credit = False

    return ScoredSentence(s, tier, bearer, enforcement_credit)


def detect_nonbinding_document(sample_texts: Iterable[str]) -> bool:
    """True when the document declares itself voluntary / non-binding.

    Checked once per document against a corpus sample rather than per
    sentence, because the disclaimer usually appears once in a preface and
    governs every provision that follows.
    """
    for t in sample_texts:
        if t and NONBINDING_DISCLAIMER_RE.search(t):
            return True
    return False


def detect_enforcement_regime(sample_texts: Iterable[str], min_signals: int = 3) -> bool:
    """True when the DOCUMENT establishes supervisory or penalty machinery.

    Checked once per document, like detect_nonbinding_document, because
    enforcement in a legal instrument is document-level. The EU AI Act's
    penalties, market surveillance authorities and corrective powers apply to a
    breach of ANY obligation in the regulation; Article 10 does not restate
    them, and it does not need to.

    Scoring enforcement only from sentences that also match a dimension's
    vocabulary therefore measures drafting style rather than governing
    strength. On the live EU run it left Human Autonomy (5 binding provisions)
    and Fairness (3 binding provisions) at Operationalized purely because their
    own sentences mention enforcement once instead of twice — while the
    regulation they sit in has the strongest enforcement regime in the corpus.

    `min_signals` guards against a single passing mention: a document that
    names a supervisory authority once in a preamble has not established a
    regime.
    """
    signals = 0
    for t in sample_texts:
        if not t:
            continue
        for sent in _split_sentences_for_scoring(t):
            scored = classify_sentence(sent)
            if scored.tier >= TIER_ENFORCEABLE:
                signals += 1
                if signals >= min_signals:
                    return True
    return False


def _split_sentences_for_scoring(text: str) -> list[str]:
    """Cheap sentence split for the document-level sweep.

    Deliberately not the full deterministic splitter: this only needs enough
    granularity to classify normative force, and it runs over a whole-document
    sample rather than a retrieved pool.
    """
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p for p in (x.strip() for x in parts) if 40 <= len(p) <= 600]


def build_profile(
    sentences: Iterable[str],
    dimension: str = "",
    own_jurisdiction: str = "",
    document_is_nonbinding: bool = False,
) -> EvidenceProfile:
    """Score every dimension-relevant sentence and aggregate the distribution.

    Near-duplicate sentences are collapsed before counting: retrieval chunks
    overlap, so the same provision is routinely returned several times at
    different offsets, and counting it repeatedly would inflate density for
    documents that simply chunk more redundantly.
    """
    profile = EvidenceProfile(dimension=dimension)
    accepted_keys: list[str] = []

    for raw in sentences:
        s = _norm(raw)
        if len(s) < 40:
            continue
        # Collapse near-duplicates from overlapping chunks by CONTAINMENT, not
        # by prefix. Overlapping chunks return the same provision cut at
        # different offsets ("...fostering sustainable growth. The development
        # of..." vs "...sustainable growth. The development of..."), so a
        # prefix key treats them as distinct and the same sentence is counted
        # once per overlapping chunk — which inflated one Kenyan sentence into
        # "5 binding provisions". Containment catches truncation at either end.
        key = re.sub(r"[^a-z0-9]", "", s.lower())
        if not key:
            continue
        if any(key in k or k in key for k in accepted_keys):
            continue
        accepted_keys.append(key)

        scored = classify_sentence(
            s,
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


# ── Profile → verdict mappings ───────────────────────────────────────────
# Both mappings read the SAME profile but measure different things, so a
# dimension can be broadly addressed yet shallowly implemented (Covered /
# Emerging) or narrowly addressed but rigorously so (Partial / Operationalized).
# Deriving maturity from coverage — the old behaviour — made that impossible.


def meets_force_bar(profile: EvidenceProfile) -> bool:
    """Does the document actually impose governing force on this dimension?

    ONE definition, used by BOTH coverage_from_profile and
    maturity_from_profile. It lives here rather than being inlined in each
    because the two ladders drifted apart once already: the degenerate
    `n_binding >= 1` threshold was found and fixed on the coverage side but
    silently left in place on the maturity side, so a document with a single
    unenforced duty read "Partial ... stands alone rather than forming a
    developed regime" and "Operationalized" at the same time. Two functions
    answering the same question must not each keep their own answer.

    The bar is deliberately NOT `n_binding >= 1`. The counters are cumulative
    (n_binding counts tier>=3, n_institutional tier>=2), so any lone binding
    sentence also lifts every weaker counter — pairing a single duty with
    ENFORCEMENT is the one genuinely independent signal available.
    """
    return profile.n_binding >= 2 or (profile.n_binding >= 1 and profile.n_enforceable >= 1)


def coverage_from_profile(
    profile: EvidenceProfile,
    mechanisms: MechanismCoverage | None = None,
    mechanism_floor: float = 1 / 3,
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
    # NOTE on counter semantics: the n_* counters are CUMULATIVE — n_binding
    # counts tier>=3 and n_institutional counts tier>=2, so n_institutional is
    # a superset of n_binding. The original rule here read
    #   n_binding >= 2 or (n_binding >= 1 and n_institutional >= 1)
    # which silently collapsed to plain `n_binding >= 1`, because any binding
    # provision also increments n_institutional. That made a SINGLE binding
    # sentence sufficient for Covered and left the "Partial: one lone binding
    # duty" branch below permanently unreachable. The corrected rule pairs a
    # lone duty with ENFORCEMENT (a genuinely independent signal) instead.
    force_bar = meets_force_bar(profile)
    # MECHANISM BREADTH GATE (downgrade only, never a raise).
    #
    # Normative force and mechanism breadth are orthogonal, and a document can
    # clear the force bar on one narrow provision while providing almost none
    # of what the dimension actually needs. Observed live: a soft-law
    # instrument scored Covered for Privacy on 1 of 7 mechanisms — no consent
    # rule, no data minimisation, no purpose limitation, no anonymisation, no
    # data-subject rights — purely because a single provision was binding and
    # enforcement-backed. Calling that "Covered" overstates the document.
    #
    # The gate can only hold a verdict DOWN. It never promotes: the document
    # must still supply its own binding provisions, so mechanism vocabulary
    # can never substitute for governing force. (The inverse case is real too
    # — a document with 6/6 mechanisms but no binding force stays Partial.)
    if force_bar and mechanisms is not None and mechanisms.total:
        if (mechanisms.met / mechanisms.total) < mechanism_floor:
            return "Partial", (
                f"The document imposes binding requirements for this dimension "
                f"({profile.n_binding} binding provision(s)), but provides only "
                f"{mechanisms.met} of {mechanisms.total} governance mechanisms "
                "the dimension calls for"
                + (
                    f" — not addressed: {', '.join(mechanisms.absent[:4])}."
                    if mechanisms.absent
                    else "."
                )
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
    # A "breadth" path to Covered — many commitment-tier sentences, no
    # binding duty required — used to exist here. Removed: it directly
    # contradicted the rule stated above it ("pure aspiration can never
    # reach Covered no matter how often repeated") and produced exactly the
    # inconsistency that contradiction predicts. Confirmed live across three
    # independent country runs: Kenya's Inclusivity, Nigeria's Inclusivity,
    # and (implicitly) EU's Inclusivity/Environmental Sustainability all hit
    # this path and were marked Covered, while sibling dimensions in the
    # SAME document with equal or weaker evidence — cited from the identical
    # source passages in Nigeria's case (Fairness vs. Inclusivity share
    # verbatim citations) — landed on Partial through the rule below. A
    # verdict that depends on which side of an arbitrary commitment-count
    # threshold a dimension falls, rather than on whether a duty exists, is
    # not a defensible Coverage signal. High commitment density with no
    # binding duty is exactly what maturity_from_profile's "Emerging" tier
    # already exists to represent — it does not also need to inflate Coverage.

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
    mechanisms: MechanismCoverage | None = None,
) -> tuple[str, str]:
    """Say WHY this dimension carries risk, and what follows if it is not fixed.

    Returns (risk_basis, potential_consequence).

    The risk LEVEL is decided elsewhere (compute_risk) by coverage tier and
    cluster compounding, and that logic is untouched. This supplies the
    sentence a reader actually needs, because the previous one restated the
    verdict in different words and leaked internal taxonomy:

        "Supporting dimension 'Environmental Sustainability' is partially
         addressed. Risk compounded by related dimension gaps."

    "Supporting" is this tool's own classification, not a property of the
    policy, and "is partially addressed" tells a reader nothing they did not
    already learn from the Partial label. What matters is the shape of the
    weakness: duties that nothing enforces behave differently from duties that
    do not exist, and both differ from a dimension covered in principle only.

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


def maturity_from_profile(
    profile: EvidenceProfile,
    document_enforcement_regime: bool = False,
) -> tuple[str, str]:
    """Map an evidence profile to a Governance Maturity stage.

    Maturity answers a different question from coverage: how far has the
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
    # Operationalized clears the SAME force bar as Covered. It used to read
    # `n_binding >= 1`, which called a single unenforced sentence
    # "Operationalized" — the stage name asserts the governance is built out
    # and running, and one duty in isolation plainly is not. That also put
    # maturity in direct contradiction with coverage, which describes the very
    # same profile as "stands alone rather than forming a developed regime".
    if meets_force_bar(profile):
        return "Operationalized", (
            "Binding requirements exist, but without the enforcement, audit or "
            "redress machinery that would make them self-sustaining."
        )
    # Delegated separates "someone owns this" from "someone said this matters".
    # Both used to return Emerging, so a dimension carrying a real binding duty
    # scored identically to one carrying a bare principle — see the note on
    # MATURITY_STAGE_SCORE for the live cases that exposed it.
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


# ── Framework alignment: an approach that was TRIED AND REJECTED ──────────
#
# Coverage and maturity are computed from the uploaded document's OWN
# provisions. That means the ingested reference corpus (UNESCO, OECD, NIST,
# UNDP, CDEI, ...) does NOT influence the verdict — it supplies the normative
# citation, the recommendations and the alignment narrative, but adding or
# removing a framework does not change whether a dimension reads Covered.
#
# An attempt was made to close that gap by measuring "framework alignment":
# extract requirement sentences from the framework corpus for a dimension,
# then count how many are semantically matched by some sentence in the
# document (cosine over bge-small embeddings), and use the ratio to gate the
# Covered tier.
#
# It was measured against the live corpora and REJECTED, because the metric is
# anti-correlated with governance strength. Transparency, 12 extracted
# requirements, requirements-met by cosine threshold:
#
#     threshold      EU AI Act    Japan (soft law)    Rwanda
#       0.55-0.65      12/12           12/12           12/12   (saturated)
#       0.70            7/12           12/12            3/12
#       0.75            5/12            7/12            2/12
#       0.80            0/12            4/12            0/12
#
# At every usable threshold the non-binding instrument outscores the binding
# regulation, and at 0.80 the EU AI Act scores zero. The cause is register,
# not compliance: Japan's guidelines are written in the same principles-document
# voice as the frameworks themselves ("should ensure transparency..."), so they
# embed close to framework requirement prose, while the AI Act's statutory
# phrasing ("Providers of high-risk AI systems shall...") embeds further away
# despite being far stronger governance. Prose-to-prose similarity measures
# how a document is WRITTEN, not what it REQUIRES.
#
# A workable design would compare at the MECHANISM level rather than the
# sentence level — frameworks define the set of mechanisms a dimension needs
# (disclosure duty, explainability right, model documentation, audit trail,
# public registry, incident notification), and each is checked against the
# document with the same tier classifier used everywhere else, which measures
# force rather than style. That requires deciding how the mechanism list is
# derived, and is deliberately not implemented here rather than shipping a
# signal that inverts the thing it claims to measure.


# ── Required governance mechanisms per dimension ──────────────────────────
# The concrete mechanisms the ingested reference corpus (UNESCO Recommendation,
# OECD AI Principles, NIST AI RMF, CDEI, ICO/Turing, UN Global Digital Compact)
# recurrently requires for each dimension.
#
# This is the MECHANISM-level comparison that the rejected sentence-similarity
# approach above could not do. Matching happens on what a provision DOES, via
# the same tier classifier used for coverage, so a statute phrased "providers
# shall log" and a strategy phrased "we will establish audit trails" are both
# recognised as the audit-trail mechanism while still being graded differently
# on force. That is what makes it immune to the writing-register confound that
# inverted the previous attempt.
#
# Hardcoded rather than auto-extracted, deliberately and visibly: deriving the
# list from the corpus is exactly what failed, and an explicit table that can
# be inspected and argued with is more honest than a computed one that quietly
# tracks prose style.
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
        "purpose limitation": ("purpose limitation", "specified purpose", "compatible purpose"),
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
        ),
        "fairness metrics": (
            "demographic parity",
            "equalis",
            "disparate impact",
            "fairness metric",
            "equal opportunity",
        ),
        "non-discrimination duty": ("discriminat", "non-discriminat", "equal treatment"),
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
            "resource efficien",
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


@dataclass
class MechanismCoverage:
    """Which framework-required mechanisms the document actually provides."""

    dimension: str = ""
    present: dict[str, int] = field(default_factory=dict)  # mechanism -> best tier
    absent: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.present) + len(self.absent)

    @property
    def met(self) -> int:
        return len(self.present)

    @property
    def binding_met(self) -> int:
        """Mechanisms provided as an actual duty, not merely mentioned."""
        return sum(1 for t in self.present.values() if t >= TIER_OBLIGATORY)

    def summary(self) -> str:
        if not self.total:
            return ""
        parts = [
            f"Provides {self.met} of {self.total} governance mechanisms the "
            f"reference frameworks expect for this dimension"
        ]
        if self.binding_met:
            parts.append(f"{self.binding_met} of them as a binding requirement")
        tail = "; ".join(parts)
        if self.absent:
            tail += f". Not addressed: {', '.join(self.absent[:4])}"
        return tail + "."


def detect_mechanisms(
    scored_sentences: list[ScoredSentence],
    dimension: str,
) -> MechanismCoverage:
    """Identify which required mechanisms the document provides, and how strongly.

    Operates on ALREADY-CLASSIFIED sentences, so a mechanism inherits the
    normative force of the provision that supplies it: the same mechanism can
    be Aspirational in one document and Obligatory in another, which is
    precisely the distinction the sentence-similarity approach lost.
    """
    result = MechanismCoverage(dimension=dimension)
    table = DIMENSION_MECHANISMS.get(dimension)
    if not table:
        return result
    usable = [s for s in scored_sentences if not s.excluded]
    for name, cues in table.items():
        # \b PREFIX anchor, no trailing anchor: stems still match their
        # inflections ("liabilit" -> liability/liabilities) but can no
        # longer match mid-word. Without it "liab" matched inside
        # "re-liab-le" and scored "Consistent and reliable data" as a
        # liability-allocation mechanism; "age" matched "agency", "log"
        # matched "logic", "fine" matched "define".
        pattern = re.compile(
            "|".join(r"\b" + ocr_flexible_fragment(c) for c in cues),
            re.IGNORECASE,
        )
        best: int | None = None
        for s in usable:
            if pattern.search(s.text):
                if best is None or s.tier > best:
                    best = s.tier
        if best is None:
            result.absent.append(name)
        else:
            result.present[name] = best
    return result
