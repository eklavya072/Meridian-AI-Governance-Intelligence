from __future__ import annotations

import os
import re
from typing import Any

from src.models import (
    CoverageLevel,
    EvidenceStrength,
    GovernanceMaturity,
    GovernanceMaturityLevel,
)

# When "0", Rule R1 (the Missing→Partial floor) is disabled entirely:
# Missing is never raised by acknowledgment/commitment language alone, only
# Rule R2 may raise a dimension to Covered. Used for before/after
# comparisons of floor impact (see README Methodology).
LADDER_FLOOR_ENABLED = os.getenv("LADDER_FLOOR_ENABLED", "1").lower() not in (
    "0", "false", "no"
)


def detect_document_type(chunks_text: list[str]) -> str:
    """Determine document type from chunk text patterns."""
    combined = " ".join(chunks_text[:10]).lower()
    if any(w in combined for w in ["strategy", "national ai strategy", "action plan", "roadmap"]):
        return "strategy"
    if any(w in combined for w in ["regulation", "regulatory", "act ", "legislation"]):
        return "legislation"
    if any(w in combined for w in ["code of conduct", "ethics", "ethical"]):
        return "code_of_conduct"
    if any(w in combined for w in ["technical", "guideline", "standard"]):
        return "standard"
    if any(w in combined for w in ["framework"]):
        return "standard"
    return "other"


# ── Governance Maturity (Module 1) — deterministic rule ────────────────
#
# Maturity is a 5-stage scale (Ad Hoc → Developing → Defined → Managed →
# Optimized) that is deliberately DISTINCT from Coverage. It is computed
# deterministically from (a) the Coverage level and (b) whether the document
# specifies actual operational mechanisms (a named body, a reporting
# requirement, an enforcement/redress mechanism) versus merely acknowledging
# a principle in passing. The LLM never freely assigns maturity — the same
# structural discipline already applied to Risk severity.
#
# Rule table (documented, reproducible):
#
#   Coverage   | Principle acknowledged | Operational mechanism(s)      | Maturity
#   -----------|----------------------|-------------------------------|----------
#   Missing    | No                   | —                             | Ad Hoc
#   Missing    | Yes                  | —                             | Developing
#   Partial    | Yes                  | None                          | Developing
#   Partial    | Yes                  | Named body / reporting        | Defined
#   Covered    | Yes                  | None (principle-level only)   | Defined
#   Covered    | Yes                  | Named body / reporting        | Managed
#   Covered    | Yes                  | + enforcement / redress /     | Optimized
#   Covered    | Yes                  |   monitoring                  |
#
# Invariants enforced:
#   - Missing coverage can only ever map to Ad Hoc or Developing.
#   - Fully Covered requires evidence of a named mechanism to reach
#     Managed/Optimized, not just principle-acknowledgment.

# Keywords that signal an operational mechanism in the document text.
# Includes the IRREGULAR plurals the whole-word matcher's "(?:s)?" cannot
# produce (agencies/ministries/authorities/ombudsmen) so plural body names
# still earn the named-body co-occurrence credit.
NAMED_BODY_KEYWORDS = (
    "commission", "board", "authority", "ministry", "agency", "council",
    "task force", "committee", "directorate", "office", "institute",
    "centre", "center", "department", "ombudsman", "inspectorate",
    "agencies", "ministries", "authorities", "ombudsmen",
)
REPORTING_KEYWORDS = (
    "report", "reporting", "reported", "register", "registered", "registry",
    "registries", "publication", "annual report", "disclosure",
    "transparency report", "publish", "published", "publishing",
    "notify", "records", "documentation requirement", "audit trail",
)
ENFORCEMENT_KEYWORDS = (
    "enforce", "enforcement", "enforcing", "redress", "grievance",
    "complaint", "appeal", "sanction", "penalty", "penalties", "fine",
    "remedy", "remedies", "liability", "liabilities", "audit", "auditing",
    "inspect", "inspecting", "inspection", "inspections", "monitor",
    "monitoring", "oversight", "supervision", "compliance check",
    "corrective action", "revocation", "order to stop",
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
GLOSSARY_ENTRY_RE = re.compile(
    r"^[A-Z][A-Za-z&'\- ]{1,80}?\s*\d{1,3}(\s*,\s*\d{1,3})*\s*\.?\s*$"
)


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
                w.isupper() or not w[:1].islower() or len(w) <= 3 or w.isdigit()
                for w in words
            ):
                return True
    return False


_KEYWORD_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _word_pattern(phrase: str) -> re.Pattern:
    """Compile a whole-word regex for a phrase/keyword.

    Word boundaries on both sides: "program" matches only the standalone
    word (and its plural "programs"), never inside "programming" or
    "programme"; "roadmap" never matches inside "roadmapping"; "board"
    never matches inside "keyboard". An optional trailing "s" keeps simple
    plurals ("programs", "roadmaps", "initiatives") matching without
    reopening the substring holes. This is the pure regex-boundary fix
    applied everywhere the ladder pattern-matches text.
    """
    pattern = _KEYWORD_PATTERN_CACHE.get(phrase)
    if pattern is None:
        pattern = re.compile(
            r"\b" + re.escape(phrase) + r"(?:s)?\b", re.IGNORECASE
        )
        _KEYWORD_PATTERN_CACHE[phrase] = pattern
    return pattern


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """True when any keyword occurs in `text` as a whole word (word boundaries)."""
    return any(_word_pattern(kw).search(text or "") for kw in keywords)


def classify_mechanisms(mechanisms: list[str] | None) -> dict[str, bool]:
    """Classify the presence of named body / reporting / enforcement mechanisms.

    Accepts a list of mechanism descriptions (e.g. from the LLM or extracted
    from the document) and returns boolean flags per mechanism category.
    """
    mechanisms = [m for m in (mechanisms or []) if m and m.strip()]
    has_named_body = any(_has_keyword(m, NAMED_BODY_KEYWORDS) for m in mechanisms)
    has_reporting = any(_has_keyword(m, REPORTING_KEYWORDS) for m in mechanisms)
    has_enforcement = any(_has_keyword(m, ENFORCEMENT_KEYWORDS) for m in mechanisms)
    return {
        "has_named_body": has_named_body,
        "has_reporting": has_reporting,
        "has_enforcement": has_enforcement,
        "has_operational_mechanism": has_named_body or has_reporting or has_enforcement,
    }


def compute_governance_maturity(
    coverage: str,
    principle_acknowledged: bool = True,
    operational_mechanisms: list[str] | None = None,
) -> tuple[GovernanceMaturity, str]:
    """Compute the Module 1 governance maturity stage from Coverage + mechanisms.

    Returns (maturity_stage, reasoning) where reasoning documents which rule
    applied, keeping the decision fully explainable.
    """
    mechanisms = [m for m in (operational_mechanisms or []) if m and m.strip()]
    mech = classify_mechanisms(mechanisms)
    cov = coverage.lower()

    if cov == "missing":
        if not principle_acknowledged:
            return (
                GovernanceMaturity.AD_HOC,
                "Coverage is Missing and the principle is not acknowledged at all — "
                "maturity stays at Ad Hoc (rule: Missing → Ad Hoc/Developing only).",
            )
        return (
            GovernanceMaturity.DEVELOPING,
            "Coverage is Missing but the document acknowledges the principle in "
            "passing — maturity capped at Developing (rule: Missing → "
            "Ad Hoc/Developing only; no mechanism evidence required for Developing).",
        )

    if cov == "partial":
        if mech["has_operational_mechanism"]:
            return (
                GovernanceMaturity.DEFINED,
                "Coverage is Partial and a named operational mechanism is present "
                f"(body={mech['has_named_body']}, reporting={mech['has_reporting']}) "
                "— maturity is Defined (rule: Partial + named mechanism → Defined).",
            )
        return (
            GovernanceMaturity.DEVELOPING,
            "Coverage is Partial with no named operational mechanism — "
            "maturity is Developing (rule: Partial + no mechanism → Developing).",
        )

    # Covered
    if not mech["has_operational_mechanism"]:
        return (
            GovernanceMaturity.DEFINED,
            "Coverage is Fully Covered at principle-acknowledgment level only — "
            "no named body, reporting requirement, or enforcement mechanism found. "
            "Maturity is Defined (rule: Fully Covered without a named mechanism "
            "cannot reach Managed/Optimized).",
        )
    if mech["has_enforcement"]:
        return (
            GovernanceMaturity.OPTIMIZED,
            "Coverage is Fully Covered with a named operational mechanism AND "
            "enforcement/redress/monitoring evidence — maturity is Optimized "
            "(rule: Covered + named mechanism + enforcement → Optimized).",
        )
    return (
        GovernanceMaturity.MANAGED,
        "Coverage is Fully Covered with a named operational mechanism "
        f"(body={mech['has_named_body']}, reporting={mech['has_reporting']}) "
        "— maturity is Managed (rule: Covered + named mechanism → Managed).",
    )


MATURITY_LEVEL_MIN = 0
MATURITY_LEVEL_MAX = 5

LEVEL_TO_COVERAGE = {
    0: "Missing",
    1: "Partial",
    2: "Partial",
    3: "Covered",
    4: "Covered",
    5: "Covered",
}

LEVEL_LABELS = {
    0: "No Governance Intent",
    1: "Governance Recognised",
    2: "Institutional Ownership Identified",
    3: "Implementation Commitment Exists",
    4: "Operational Mechanisms Established",
    5: "Continuous Monitoring and Enforcement",
}

# ── Deterministic Coverage Validation (combined Module 1+2 path) ─────────
#
# The merged single-call pipeline lets the LLM's raw `coverage` label stand
# on its own. That dropped the governance-ladder enforcement the old
# Stage 1-4 plausibility validator provided (strategy → never Missing,
# Level 0 with evidence → raise, Missing with evidence → raise). The rules
# below reinstate that discipline deterministically from the document's own
# signals — NEVER from free LLM judgment about the final label:
#
#   R1 — Explicit-Commitment floor (Missing → Partial), gated by
#        LADDER_FLOOR_ENABLED: Missing is raised to Partial only when the
#        document shows evidence of an ACTUAL attempted mechanism or
#        EXPLICIT commitment (even a weak one, e.g. "the government will
#        establish guidelines for X") — a mechanism report, strong
#        commitment language, or an explicit commitment verb ("commits to",
#        "plans to", "will ensure"...). A bare risk acknowledgment with no
#        proposed action attached does NOT satisfy this bar and stays
#        Missing. "Mentioned once" and "genuinely partial" are deliberately
#        kept apart: Partial means the document proposes real action,
#        however early. (This replaced the old "principle acknowledged →
#        Partial" floor, which treated a passing mention as Partial.)
#
#   R2 — Implementation-Commitment raise (Partial → Covered): fires ONLY on
#        a Partial verdict, never directly on Missing. The document (or the
#        model's own mechanism report) shows a CONCRETE implementation
#        commitment — a named body, programme/initiative, establishment
#        language, roadmap, mandate — → coverage is raised to Covered,
#        because Level 3 "Implementation Commitment Exists" maps to Covered.
#        Because R2 cannot touch a Missing verdict, disabling R1
#        (LADDER_FLOOR_ENABLED=0) leaves genuinely under-addressed
#        dimensions at Missing — which is exactly what makes the floor
#        observable in before/after comparisons.
#
#   Two hardening rules apply to BOTH rules' chunk-based paths:
#     1. WHOLE-WORD matching (regex word boundaries): "program" never
#        matches inside "programming"/"programme", "roadmap" never matches
#        inside "roadmapping", etc. — a pure boundary bug, fixed everywhere.
#     2. R2's STRONG-phrase path additionally requires a named-body/
#        institution keyword to co-occur in the SAME chunk (the stricter-bar
#        simulation: all 8 off-topic chunks failed co-occurrence). A bare
#        "programme"/"initiative" mention in an AI-security or events-
#        calendar passage is not an implementation commitment.
#     3. DIMENSION GROUNDING: a chunk may only fire R1/R2 for a dimension
#        when it is actually topically related to that dimension (see
#        DIMENSION_TOPIC_KEYWORDS) — a UN advisory-body participation
#        paragraph must not trigger Accountability, an events calendar must
#        not trigger Inclusivity.

# Phrases that signal a Level-3 implementation commitment when found in
# dimension-scoped document chunks or in the model's mechanism report.
#
# Two tiers, deliberately:
#   STRONG — conclusive ONLY when the phrase co-occurs with a named-body /
#     institution keyword in the same chunk (R2). Establishment verbs and
#     dedicated programme/initiative language are unequivocal commitments
#     ("will establish", "setting up", "program", "task force", "roadmap"),
#     but the bare noun alone (e.g. "program" in an AI-security passage)
#     is not — the co-occurrence bar is what stopped the Accountability /
#     Inclusivity false positives.
#   WEAK — a lone mention is too noisy to be conclusive ("budget
#     constraints", "no dedicated program", "a mandate is debated" could
#     appear in a passage that is NOT a commitment). Weak phrases only
#     count when they co-occur with a named-body keyword in the same chunk
#     or appear in at least two distinct chunks.
STRONG_COMMITMENT_PHRASES = (
    "will establish", "shall establish", "will set up", "shall set up",
    "setting up", "establishment of", "establish a", "establish an",
    "establish the", "will create", "shall create", "will launch",
    "shall launch", "will develop", "shall develop", "will implement",
    "shall implement", "will invest", "shall invest", "to establish",
    "to set up", "to create", "to launch", "to develop", "roadmap",
    "action plan", "program", "programme", "initiative", "mission",
    "task force", "pledge", "mandatory",
)
WEAK_COMMITMENT_PHRASES = (
    "commitment", "mandate", "mandated", "dedicated",
    "allocate", "allocation", "budget",
)

# Explicit commitment verbs — the R1 floor bar. These signal the document
# commits to addressing the dimension even without a concrete mechanism yet
# ("the government commits to improving AI transparency", "plans to",
# "will ensure"). Broader than the R2 bar: a commitment verb alone floors to
# Partial but does not raise to Covered.
EXPLICIT_COMMITMENT_VERBS = (
    "commits to", "committed to", "pledge", "pledges", "pledged",
    "plans to", "intends to", "will ensure", "working towards",
    "aims to", "seeks to", "will address", "will promote",
    "will support",
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
NEGATION_WORDS = frozenset({
    "not", "no", "never", "unable", "fails", "failed", "won't",
    "doesn't", "cannot", "can't", "isn't", "aren't", "without",
    "lacks", "refuses", "declines", "against",
})


def _is_negated_occurrence(text: str, idx: int) -> bool:
    """True when the match at `idx` in `text` is preceded by a negation word."""
    window = text[max(0, idx - 16):idx].split()
    if not window:
        return False
    return any(tok in NEGATION_WORDS for tok in window[-2:])


def _contains_commitment_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    """True when any phrase occurs in `text` on a non-negated, whole-word occurrence.

    Word-boundary matching (fixes substring false positives): "program"
    no longer matches inside "programming"/"programme", "roadmap" no
    longer matches inside "roadmapping", etc. Negated occurrences
    ("will not support", "not committed to") never count.
    """
    for phrase in phrases:
        pattern = _word_pattern(phrase)
        for match in pattern.finditer(text):
            if not _is_negated_occurrence(text, match.start()):
                return True
    return False


# ── Dimension grounding (R1/R2 topical eligibility) ─────────────────────
#
# A chunk must be topically related to the dimension being evaluated before
# its commitment phrases can fire R1/R2. This is the deeper fix beyond the
# named-body co-occurrence rule: the UN-advisory-body paragraph matched R1
# on "will support" and the events-calendar paragraph matched R2 on
# "program"/"intends to" purely on vocabulary, with no check that the
# content was actually about Accountability / Inclusivity governance.
DIMENSION_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Transparency": (
        "transparen", "disclos", "explainab", "documentation", "audit trail",
        "logging", "open", "public report", "inform", "opacity", "opaque",
        "black box", "decision-making", "interpretab",
    ),
    "Accountability": (
        "accountab", "liabilit", "redress", "grievance", "complaint",
        "oversight", "audit", "enforce", "enforcement", "responsib",
        "sanction", "penalty", "remedy", "remedies", "answerable", "blame",
        "consequence", "governance structure", "ownership", "obligation", "duty",
    ),
    "Privacy": (
        "privacy", "personal data", "consent", "anonymiz", "pseudonymiz",
        "data protection", "data minimiz", "purpose limitation", "data subject",
        "breach", "confidential", "data security",
    ),
    "Safety": (
        "safety", "safe", "robust", "fail-safe", "failsafe", "adversarial",
        "monitor", "monitoring", "incident", "emergency", "shut-off",
        "certification", "harm", "reliability", "test", "testing", "validation",
        "red team",
    ),
    "Human Autonomy": (
        "autonomy", "human control", "human oversight", "opt-out",
        "human-in-the-loop", "human in the loop", "self-determination",
        "non-automated", "manipulation", "nudge", "nudging", "human agency",
        "override", "meaningful control",
    ),
    "Inclusivity": (
        "inclusiv", "inclusion", "accessib", "digital divide",
        "multi-stakeholder", "multistakeholder", "public participation",
        "diversity", "diverse", "disabilit", "linguistic", "cultural",
        "represent", "underserved", "marginalis", "equitab", "equity",
        "non-discriminat", "gender", "persons with disabilities",
    ),
    "Fairness": (
        "fair", "fairness", "bias", "discrimina", "equitab", "demographic parity",
        "protected characteristics", "prejudice", "stereotype", "parity",
    ),
    "Environmental Sustainability": (
        "environment", "environmental", "sustainab", "energy efficiency",
        "carbon", "footprint", "climate", "lifecycle", "e-waste", "emissions",
        "green", "computational resource", "resource consumption",
        "energy consumption",
    ),
}


def _chunk_matches_dimension(text: str, dimension: str) -> bool:
    """True when a chunk is topically related to the dimension.

    R1/R2 must never fire on a chunk that merely contains commitment
    vocabulary but is about something else (a UN advisory-body participation
    paragraph is not Accountability evidence; an events calendar is not
    Inclusivity evidence). Unknown dimensions are not gated (no false
    blocking).
    """
    keywords = DIMENSION_TOPIC_KEYWORDS.get(dimension)
    if not keywords:
        return True
    lower = (text or "").lower()
    return any(kw in lower for kw in keywords)


def detect_explicit_commitment(
    operational_mechanisms: list[str] | None,
    document_chunk_texts: list[str] | None,
    dimension: str = "",
) -> bool:
    """R1 floor bar: actual attempted mechanism OR explicit commitment.

    Broader than detect_implementation_commitment (the R2 bar). Returns True
    on ANY of:
      (a) a non-empty operational-mechanism report (named body / reporting /
          enforcement-redress, classified with the same keyword sets used by
          governance maturity), or
      (b) a STRONG commitment phrase in a dimension-TOPICAL retrieved
          document chunk (programme, initiative, task force, "will
          establish", ...), or
      (c) an explicit commitment verb in a dimension-topical chunk ("commits
          to", "plans to", "will ensure", "will address", ...).

    Dimension grounding: chunks are only eligible when they are actually
    topically related to the dimension (see _chunk_matches_dimension) — a
    UN advisory-body participation paragraph containing "will support" is
    NOT Accountability evidence and never fires R1.

    A bare risk acknowledgment with no proposed action attached matches
    none of these and returns False — such a document stays Missing.
    Negated occurrences ("will not support", "not committed to") never count.
    """
    if classify_mechanisms(operational_mechanisms)["has_operational_mechanism"]:
        return True
    for text in document_chunk_texts or []:
        if dimension and not _chunk_matches_dimension(text, dimension):
            continue
        lower = (text or "").lower()
        if _contains_commitment_phrase(lower, STRONG_COMMITMENT_PHRASES):
            return True
        if _contains_commitment_phrase(lower, EXPLICIT_COMMITMENT_VERBS):
            return True
    return False


def detect_implementation_commitment(
    operational_mechanisms: list[str] | None,
    document_chunk_texts: list[str] | None,
    dimension: str = "",
) -> bool:
    """Detect Level-3+ implementation-commitment evidence.

    Three independent signals, any of which suffices:
      (a) the model's own operational-mechanism report contains a named
          body / reporting requirement / enforcement-redress mechanism
          (classified with the same keyword sets used by governance
          maturity), or
      (b) the retrieved document chunks contain a STRONG commitment phrase
          (programme, initiative, task force, "will establish", "setting
          up", roadmap, ...) THAT CO-OCCURS WITH A NAMED-BODY/INSTITUTION
          KEYWORD IN THE SAME CHUNK — a bare programme/initiative mention
          in an off-topic passage (AI security, events calendar) is not an
          implementation commitment, or
      (c) WEAK commitment phrases co-occur with a named-body keyword in the
          same chunk, or appear in at least two distinct chunks.

    Dimension grounding: only chunks actually topically related to the
    dimension are eligible (see _chunk_matches_dimension). Deterministic and
    document-agnostic — the same detector runs for any uploaded policy. It
    never judges the verdict; it only reports whether commitment language
    exists.
    """
    if classify_mechanisms(operational_mechanisms)["has_operational_mechanism"]:
        return True
    weak_hits = 0
    for text in document_chunk_texts or []:
        if dimension and not _chunk_matches_dimension(text, dimension):
            continue
        lower = (text or "").lower()
        if (
            _contains_commitment_phrase(lower, STRONG_COMMITMENT_PHRASES)
            and _has_keyword(text, NAMED_BODY_KEYWORDS)
        ):
            return True
        if _contains_commitment_phrase(lower, WEAK_COMMITMENT_PHRASES):
            weak_hits += 1
            if _has_keyword(text, NAMED_BODY_KEYWORDS):
                return True
    return weak_hits >= 2


def validate_coverage_deterministic(
    coverage: CoverageLevel,
    principle_acknowledged: bool,
    operational_mechanisms: list[str] | None,
    document_chunks: list[dict[str, Any]] | None = None,
    dimension: str = "",
) -> tuple[CoverageLevel, list[str]]:
    """Deterministic coverage validation for the combined Module 1+2 path.

    Reinstates the governance-ladder enforcement (R1 + R2 above) that the
    merged single-call pipeline dropped. Returns
    (validated_coverage, applied_rule_notes); the caller appends the notes
    to the coverage reasoning so the explainability chain stays transparent.

    `dimension` grounds the ladder: chunks are only eligible to fire R1/R2
    when they are topically related to the dimension being evaluated.
    """
    applied: list[str] = []
    cov = coverage
    if cov not in (CoverageLevel.MISSING, CoverageLevel.PARTIAL, CoverageLevel.COVERED):
        return cov, applied

    # Real document evidence = chunks actually retrieved for this dimension.
    chunk_texts = [
        (c.get("text") or "") for c in (document_chunks or [])
        if isinstance(c, dict) and c.get("chunk_id")
    ]
    has_doc_evidence = bool(chunk_texts)

    # R1 — explicit-commitment floor. Gated by LADDER_FLOOR_ENABLED so the
    # floor's impact is measurable. A bare acknowledgment with no proposed
    # action (principle_acknowledged alone) does NOT satisfy the bar — the
    # document must show an actual attempted mechanism or explicit
    # commitment. (principle_acknowledged is deliberately NOT used here: it
    # is exactly the permissive signal that used to inflate "mentioned once"
    # into Partial.)
    if (
        LADDER_FLOOR_ENABLED
        and cov == CoverageLevel.MISSING
        and has_doc_evidence
        and detect_explicit_commitment(operational_mechanisms, chunk_texts, dimension=dimension)
    ):
        cov = CoverageLevel.PARTIAL
        applied.append(
            "R1 explicit-commitment floor: the document shows an actual "
            "attempted mechanism or explicit commitment with retrieved "
            "evidence (establishment language, programme/initiative, named "
            "body, roadmap, mandate, or an explicit commitment verb); a bare "
            "risk acknowledgment with no proposed action does not satisfy "
            "this bar. Level 1 (Governance Recognised) maps to Partial — "
            "Missing was raised."
        )

    # R2 — implementation-commitment raise. Fires ONLY on Partial: R1 is the
    # only rule that rescues a Missing verdict, so disabling the floor is
    # observable. A Missing dimension with commitment language is raised to
    # Partial by R1 first (when enabled) and then to Covered here.
    if cov == CoverageLevel.PARTIAL and has_doc_evidence:
        if detect_implementation_commitment(operational_mechanisms, chunk_texts, dimension=dimension):
            cov = CoverageLevel.COVERED
            applied.append(
                "R2 implementation-commitment raise: the document (or the "
                "model's own mechanism report) shows a concrete implementation "
                "commitment — a named body/institution co-occurring with "
                "programme/initiative, establishment language, roadmap or "
                "mandate in dimension-relevant evidence; Level 3 (Implementation "
                "Commitment Exists) maps to Covered — Partial was raised."
            )

    return cov, applied


class FrameworkMatchResult:
    """Result of matching framework requirements against policy evidence."""

    def __init__(
        self,
        universal_requirements: list[str],
        framework_agreements: list[str],
        framework_differences: list[str],
        existing_mechanisms: list[str],
        missing_mechanisms: list[str],
        framework_specific_requirements: dict[str, list[str]],
        implementation_maturity_comparison: dict[str, list[str]],
        synthesis: str,
    ):
        self.universal_requirements = universal_requirements
        self.framework_agreements = framework_agreements
        self.framework_differences = framework_differences
        self.existing_mechanisms = existing_mechanisms
        self.missing_mechanisms = missing_mechanisms
        self.framework_specific_requirements = framework_specific_requirements
        self.implementation_maturity_comparison = implementation_maturity_comparison
        self.synthesis = synthesis

    def to_dict(self) -> dict[str, Any]:
        return {
            "universal_requirements": self.universal_requirements,
            "framework_agreements": self.framework_agreements,
            "framework_differences": self.framework_differences,
            "existing_mechanisms": self.existing_mechanisms,
            "missing_mechanisms": self.missing_mechanisms,
            "framework_specific_requirements": self.framework_specific_requirements,
            "implementation_maturity_comparison": self.implementation_maturity_comparison,
            "synthesis": self.synthesis,
        }


class DeterministicFrameworkMatcher:
    """Replace Stage 3 (Framework Synthesis) with deterministic semantic matching.

    Algorithm:
      1. Group framework evidence by source framework (UNESCO/OECD/UNDP).
      2. For each framework chunk, compute multi-factor match score against
         all policy evidence items, combining:
         - semantic similarity (cosine)
         - evidence strength multiplier
         - explicit vs implicit evidence boost
         - corroboration count
         - aspect alignment
      3. Classify each requirement as Implemented / Partially Implemented /
         Missing / Beyond Framework.
    """

    def __init__(self, embed_function):
        self._embed = embed_function

    def match(
        self,
        dimension: str,
        evidence_strength: str,
        explicit_evidence: list[str],
        implicit_evidence: list[str],
        strong_evidence: list[str],
        weak_evidence: list[str],
        policy_evidence_texts: list[str],
        framework_evidence_texts: list[tuple[str, str]],
        aspect_groups: list[Any] | None = None,
    ) -> FrameworkMatchResult:
        evidence_items = self._build_matched_evidence(
            explicit_evidence, implicit_evidence, strong_evidence,
            weak_evidence, policy_evidence_texts,
        )
        fw_embeddings = self._compute_embeddings([t for _, t in framework_evidence_texts])
        ev_embeddings = self._compute_embeddings([e["text"] for e in evidence_items])

        if not fw_embeddings or not ev_embeddings:
            return self._empty_result(dimension)

        fw_by_framework: dict[str, list[tuple[int, str]]] = {}
        for idx, (fw_name, text) in enumerate(framework_evidence_texts):
            fw_by_framework.setdefault(fw_name, []).append((idx, text))

        strength_multiplier = {
            "Strongly Operationalised": 1.3,
            "Explicitly Addressed": 1.1,
            "Implicitly Addressed": 1.0,
            "Weakly Demonstrated": 0.7,
            "Not Demonstrated": 0.4,
        }.get(evidence_strength, 1.0)

        all_implemented: list[str] = []
        all_partial: list[str] = []
        all_missing: list[str] = []
        all_beyond: list[str] = []
        fw_specific: dict[str, list[str]] = {}

        for fw_name, chunks in fw_by_framework.items():
            fw_implemented: list[str] = []
            fw_partial: list[str] = []
            fw_missing: list[str] = []

            for idx, text in chunks:
                if idx >= len(fw_embeddings):
                    continue
                fw_emb = fw_embeddings[idx]

                max_sim = 0.0
                best_explicit_sim = 0.0
                best_implicit_sim = 0.0
                corroboration_count = 0

                for ev_idx, ev_item in enumerate(evidence_items):
                    if ev_idx >= len(ev_embeddings):
                        continue
                    sim = self._cosine_similarity(fw_emb, ev_embeddings[ev_idx])
                    if sim > max_sim:
                        max_sim = sim
                    if ev_item["is_explicit"] and sim > best_explicit_sim:
                        best_explicit_sim = sim
                    if ev_item["is_implicit"] and sim > best_implicit_sim:
                        best_implicit_sim = sim
                    if sim > 0.35:
                        corroboration_count += 1

                score = self._compute_match_score(
                    max_sim=max_sim,
                    best_explicit_sim=best_explicit_sim,
                    best_implicit_sim=best_implicit_sim,
                    corroboration_count=corroboration_count,
                    strength_multiplier=strength_multiplier,
                )

                short_text = text[:120].strip()
                if score >= 0.6:
                    fw_implemented.append(short_text)
                elif score >= 0.35:
                    fw_partial.append(short_text)
                else:
                    fw_missing.append(short_text)

            all_implemented.extend(fw_implemented)
            all_partial.extend(fw_partial)
            all_missing.extend(fw_missing)
            fw_specific[fw_name] = fw_implemented + fw_partial

        has_strong = evidence_strength == "Strongly Operationalised"
        strong_count = len(strong_evidence)
        if has_strong and strong_count > 1 and len(all_implemented) < strong_count:
            beyond_count = strong_count - len(all_implemented)
            all_beyond = [f"Policy exceeds framework expectations on {beyond_count} mechanism(s)"]

        universal = list(set(
            r for r in all_implemented + all_partial + all_missing
        ))

        return FrameworkMatchResult(
            universal_requirements=universal,
            framework_agreements=["All frameworks agree on core governance requirements"],
            framework_differences=self._find_differences(fw_specific),
            existing_mechanisms=all_implemented + all_beyond,
            missing_mechanisms=all_missing,
            framework_specific_requirements=fw_specific,
            implementation_maturity_comparison={
                "Already implemented": all_implemented,
                "Partially implemented": all_partial,
                "Missing implementation": all_missing,
                "More advanced than framework": all_beyond,
                "Framework-specific requirement": [],
            },
            synthesis=self._build_synthesis(
                dimension=dimension,
                implemented=all_implemented,
                partial=all_partial,
                missing=all_missing,
                beyond=all_beyond,
            ),
        )

    def _compute_match_score(
        self,
        max_sim: float,
        best_explicit_sim: float,
        best_implicit_sim: float,
        corroboration_count: int,
        strength_multiplier: float,
    ) -> float:
        semantic_signal = max_sim * 0.35
        explicit_signal = best_explicit_sim * 0.25
        implicit_signal = best_implicit_sim * 0.10
        corroboration_signal = min(corroboration_count / 4.0, 1.0) * 0.15
        strength_signal = (strength_multiplier - 0.5) * 0.15
        raw = semantic_signal + explicit_signal + implicit_signal + corroboration_signal + strength_signal
        return max(0.0, min(1.0, raw))

    def _compute_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [self._embed(t) for t in texts]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def _build_matched_evidence(
        self,
        explicit_evidence: list[str],
        implicit_evidence: list[str],
        strong_evidence: list[str],
        weak_evidence: list[str],
        policy_evidence_texts: list[str],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        for t in strong_evidence:
            if t not in seen:
                seen.add(t)
                items.append({"text": t, "is_explicit": True, "is_implicit": False})
        for t in explicit_evidence:
            if t not in seen:
                seen.add(t)
                items.append({"text": t, "is_explicit": True, "is_implicit": False})
        for t in implicit_evidence:
            if t not in seen:
                seen.add(t)
                items.append({"text": t, "is_explicit": False, "is_implicit": True})
        for t in weak_evidence:
            if t not in seen:
                seen.add(t)
                items.append({"text": t, "is_explicit": False, "is_implicit": False})
        for t in policy_evidence_texts:
            if t not in seen:
                seen.add(t)
                items.append({"text": t, "is_explicit": False, "is_implicit": False})

        return items

    def _find_differences(self, fw_specific: dict[str, list[str]]) -> list[str]:
        if len(fw_specific) <= 1:
            return []
        fw_names = list(fw_specific.keys())
        all_items = set()
        for items in fw_specific.values():
            all_items.update(items)
        diffs = []
        for item in all_items:
            present = [fw for fw, items in fw_specific.items() if item in items]
            if len(present) < len(fw_names):
                diffs.append(f"'{item}' mentioned in {', '.join(present)} but not others")
        return diffs

    def _build_synthesis(
        self,
        dimension: str,
        implemented: list[str],
        partial: list[str],
        missing: list[str],
        beyond: list[str],
    ) -> str:
        parts = [f"Framework comparison for {dimension}:"]
        if implemented:
            parts.append(f"Already implemented ({len(implemented)}): {'; '.join(implemented[:5])}")
        if partial:
            parts.append(f"Partially implemented ({len(partial)}): {'; '.join(partial[:5])}")
        if missing:
            parts.append(f"Missing ({len(missing)}): {'; '.join(missing[:5])}")
        if beyond:
            parts.append(f"Beyond framework expectations: {'; '.join(beyond[:3])}")
        return " | ".join(parts)

    def _empty_result(self, dimension: str) -> FrameworkMatchResult:
        return FrameworkMatchResult(
            universal_requirements=[],
            framework_agreements=[],
            framework_differences=[],
            existing_mechanisms=[],
            missing_mechanisms=[],
            framework_specific_requirements={},
            implementation_maturity_comparison={
                "Already implemented": [],
                "Partially implemented": [],
                "Missing implementation": [],
                "More advanced than framework": [],
                "Framework-specific requirement": [],
            },
            synthesis=f"No framework requirements available for {dimension}.",
        )


class PlausibilityResult:
    def __init__(
        self,
        validated_maturity_level: int,
        validated_coverage: str,
        plausibility_checks: list[str],
        adjustment_rationale: str,
        confidence_in_assessment: str,
        uncertainty_acknowledged: list[str],
        maturity_trace: str,
    ):
        self.validated_maturity_level = validated_maturity_level
        self.validated_coverage = validated_coverage
        self.plausibility_checks = plausibility_checks
        self.adjustment_rationale = adjustment_rationale
        self.confidence_in_assessment = confidence_in_assessment
        self.uncertainty_acknowledged = uncertainty_acknowledged
        self.maturity_trace = maturity_trace

    def to_dict(self) -> dict[str, Any]:
        return {
            "validated_maturity_level": self.validated_maturity_level,
            "validated_coverage": self.validated_coverage,
            "plausibility_checks": self.plausibility_checks,
            "adjustment_rationale": self.adjustment_rationale,
            "confidence_in_assessment": self.confidence_in_assessment,
            "uncertainty_acknowledged": self.uncertainty_acknowledged,
            "maturity_trace": self.maturity_trace,
        }


class DeterministicPlausibilityValidator:
    """Replace Stage 4 (Plausibility Validation) with deterministic rules.

    Applies 7 rule-based checks that can modify or validate the maturity
    result. Rules are explainable and reproducible.
    """

    def validate(
        self,
        dimension: str,
        maturity_level: int,
        coverage: str,
        evidence_strength: str,
        document_type: str,
        explicit_evidence: list[str],
        implicit_evidence: list[str],
        strong_evidence: list[str],
        weak_evidence: list[str],
        demonstrated_capability: str,
        absent_capability: str,
        num_aspect_groups: int,
        missing_aspects: list[str],
        framework_synthesis: dict[str, Any] | None = None,
    ) -> PlausibilityResult:
        level = maturity_level
        cov = coverage
        checks: list[str] = []
        adjustments: list[str] = []

        rule_triggers: list[str] = []

        has_explicit = bool(explicit_evidence)
        has_implicit = bool(implicit_evidence)
        has_strong = bool(strong_evidence)
        has_weak = bool(weak_evidence)
        has_any_evidence = has_explicit or has_implicit or has_strong

        # Check 1: Document type
        if document_type == "strategy" and cov == "Missing" and has_any_evidence:
            checks.append(
                "Document type is strategy: strategies establish direction, "
                "not procedural completeness. Overriding Missing to Partial."
            )
            level = max(level, 1)
            cov = "Partial"
            adjustments.append(
                f"Document type 'strategy' -> Missing overridden to Partial "
                f"(level raised to {level})"
            )
            rule_triggers.append("doc_type")

        # Check 2: Governance ladder consistency
        expected_cov = LEVEL_TO_COVERAGE.get(level, "Missing")
        if cov != expected_cov:
            checks.append(
                f"Governance ladder: Level {level} maps to '{expected_cov}', "
                f"was '{cov}'. Corrected."
            )
            adjustments.append(
                f"Level {level} -> coverage '{cov}' corrected to '{expected_cov}'"
            )
            cov = expected_cov
            rule_triggers.append("ladder")

        # Check 3: Functional equivalence (level 0 safeguards)
        if level == 0 and has_any_evidence:
            checks.append(
                "Functional equivalence: policy evidence exists despite Level 0. "
                "Raising to Level 1 (Governance Recognised)."
            )
            level = 1
            cov = "Partial"
            adjustments.append("Level 0 with evidence -> raised to Level 1")
            rule_triggers.append("functional_equiv")

        # Check 4: Level 0 safeguard (final Missing check)
        if cov == "Missing" and has_any_evidence:
            checks.append(
                "Level 0 safeguard: evidence exists. Overriding Missing to Partial."
            )
            level = max(level, 1)
            cov = "Partial"
            adjustments.append(
                f"Missing overridden to Partial due to existing evidence"
            )
            rule_triggers.append("level0")

        # Check 5: Level 5 safeguard
        if level == 5:
            if evidence_strength != "Strongly Operationalised":
                checks.append(
                    f"Level 5 safeguard: evidence strength is '{evidence_strength}', "
                    f"not 'Strongly Operationalised'. Lowering to Level 4."
                )
                level = 4
                cov = "Covered"
                adjustments.append(
                    f"Level 5 -> Level 4 (evidence strength too weak)"
                )
                rule_triggers.append("level5")
            elif not has_strong:
                checks.append(
                    "Level 5 safeguard: no strong evidence items. Lowering to Level 4."
                )
                level = 4
                cov = "Covered"
                adjustments.append("Level 5 -> Level 4 (no strong evidence)")
                rule_triggers.append("level5")

        # Check 6: Distributed governance (for strategies)
        if document_type == "strategy" and level < 2 and num_aspect_groups > 2:
            checks.append(
                f"Distributed governance: {num_aspect_groups} aspect groups "
                f"suggest distributed coverage. Raising from Level {level}."
            )
            level = max(level, 2)
            cov = "Partial"
            adjustments.append(
                f"Level raised to {level} via distributed governance rule"
            )
            rule_triggers.append("distributed")

        # Check 7: Missing final check
        if cov == "Missing":
            if demonstrated_capability and demonstrated_capability != "None":
                checks.append(
                    "Missing final check: demonstrated capability exists. "
                    "Overriding to Partial."
                )
                level = max(level, 1)
                cov = "Partial"
                adjustments.append(
                    "Missing -> Partial (demonstrated capability exists)"
                )
                rule_triggers.append("missing_final")
            elif has_implicit:
                checks.append(
                    "Missing final check: implicit evidence exists. "
                    "Overriding to Partial."
                )
                level = max(level, 1)
                cov = "Partial"
                adjustments.append(
                    "Missing -> Partial (implicit evidence exists)"
                )

        # Confidence calibration
        confidence = self._calibrate_confidence(
            level=level,
            coverage=cov,
            evidence_strength=evidence_strength,
            has_explicit=has_explicit,
            has_implicit=has_implicit,
            has_weak=bool(weak_evidence),
            num_adjustments=len(adjustments),
        )

        uncertainty: list[str] = []
        if has_weak and not has_strong:
            uncertainty.append("Evidence is predominantly weak or implicit")
        if not has_explicit and has_implicit:
            uncertainty.append("Assessment relies on implicit evidence")
        if document_type == "strategy" and cov == "Missing":
            uncertainty.append("Strategy document may address this through future actions")
        if "distributed" in rule_triggers:
            uncertainty.append("Governance capability may be distributed across multiple mechanisms")

        trace = self._build_trace(
            dimension=dimension,
            document_type=document_type,
            original_level=maturity_level,
            original_coverage=coverage,
            validated_level=level,
            validated_coverage=cov,
            rule_triggers=rule_triggers,
            adjustments=adjustments,
        )

        rationale = "; ".join(adjustments) if adjustments else "No adjustment needed"

        return PlausibilityResult(
            validated_maturity_level=level,
            validated_coverage=cov,
            plausibility_checks=checks,
            adjustment_rationale=rationale,
            confidence_in_assessment=confidence,
            uncertainty_acknowledged=uncertainty,
            maturity_trace=trace,
        )

    def _calibrate_confidence(
        self,
        level: int,
        coverage: str,
        evidence_strength: str,
        has_explicit: bool,
        has_implicit: bool,
        has_weak: bool,
        num_adjustments: int,
    ) -> str:
        score = 0.5

        strength_scores = {
            "Strongly Operationalised": 0.9,
            "Explicitly Addressed": 0.75,
            "Implicitly Addressed": 0.55,
            "Weakly Demonstrated": 0.35,
            "Not Demonstrated": 0.2,
        }
        score = strength_scores.get(evidence_strength, 0.5)

        if has_explicit:
            score = min(1.0, score + 0.1)
        if has_weak and not has_explicit:
            score = max(0.1, score - 0.1)

        if num_adjustments > 1:
            score = max(0.1, score - 0.05 * num_adjustments)

        if score >= 0.7:
            return "High"
        elif score >= 0.4:
            return "Medium"
        else:
            return "Low"

    def _build_trace(
        self,
        dimension: str,
        document_type: str,
        original_level: int,
        original_coverage: str,
        validated_level: int,
        validated_coverage: str,
        rule_triggers: list[str],
        adjustments: list[str],
    ) -> str:
        doc_type_label = {
            "strategy": "National AI Strategy",
            "legislation": "Legislation or Regulation",
            "standard": "Technical Standard",
            "code_of_conduct": "Code of Conduct",
            "other": "Other",
        }.get(document_type, document_type.capitalize())

        fn_findings = "Functional equivalence: "
        if "functional_equiv" in rule_triggers or "level0" in rule_triggers or "missing_final" in rule_triggers:
            fn_findings += "Evidence found despite level 0/Missing classification. Overridden."
        else:
            fn_findings += "No functional equivalence issues detected."

        trace_lines = [
            f"1) Document Type: {doc_type_label}",
            f"2) Functional Equivalence findings: {fn_findings}",
            f"3) Level selected: {validated_level}",
            f"4) Why that level: {LEVEL_LABELS.get(validated_level, 'Unknown')}",
            f"5) Why final coverage label: {validated_coverage}",
        ]
        if adjustments:
            trace_lines.append(f"6) Adjustments applied: {'; '.join(adjustments)}")

        return "\n".join(trace_lines)


def assemble_framework_context(
    framework_chunks: list[dict[str, Any]],
) -> str:
    """Build a summary of framework requirements from retrieved chunks."""
    fw_map: dict[str, list[str]] = {}
    for chunk in framework_chunks:
        fw = chunk.get("source_framework", "framework")
        text = chunk.get("text", "")[:600]
        if fw not in fw_map:
            fw_map[fw] = []
        fw_map[fw].append(text)

    parts: list[str] = []
    for fw, texts in fw_map.items():
        combined = "\n".join(texts[:3])[:2000]
        parts.append(f"[Framework: {fw}]\n{combined}")

    return "\n\n---\n\n".join(parts) if parts else "No framework requirements retrieved for this dimension."
