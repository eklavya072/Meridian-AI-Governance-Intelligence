from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any, Callable

from src.utils import ocr_flexible_fragment

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
# Maturity is a 4-stage Institutionalization Scale (Unaddressed → Emerging →
# Operationalized → Institutionalized) that is deliberately DISTINCT from Coverage —
# each stage is a strictly stronger, unambiguous claim than the last (see
# GovernanceMaturity's docstring in models.py). It is computed
# deterministically from (a) the Coverage level and (b) whether the SAME
# evidence that grounds the Coverage verdict shows an actual operational
# mechanism (a named body, a reporting requirement) and/or enforcement
# evidence (audit, redress, monitoring) versus merely signalling intent.
# The LLM never freely assigns maturity — the same structural discipline
# already applied to Risk severity.
#
# Rule table (documented, reproducible):
#
#   Coverage   | Mechanism found | Enforcement found | Maturity
#   -----------|------------------|--------------------|-------------
#   Missing    | —                | —                  | Unaddressed
#   Partial    | No               | —                  | Emerging
#   Partial    | Yes              | —                  | Operationalized
#   Covered    | No               | —                  | Emerging
#   Covered    | Yes              | No                 | Operationalized
#   Covered    | Yes              | Yes                | Institutionalized
#
# Invariants enforced:
#   - Missing coverage always maps to Unaddressed — R1/R2 guarantee that a
#     Missing verdict has no qualifying commitment/mechanism evidence.
#   - A bare Covered LABEL is never treated as proof of a mechanism: Covered
#     without any mechanism evidence (self-reported OR ladder evidence)
#     caps at Emerging, same as an under-evidenced Partial — this is what
#     stops a ladder-raised "Covered" from silently reading as mature.
#   - Institutionalized requires BOTH a mechanism and enforcement/redress/
#     monitoring evidence, never enforcement language alone.

# Keywords that signal an operational mechanism in the document text.
# Includes the IRREGULAR plurals the whole-word matcher's "(?:s)?" cannot
# produce (agencies/ministries/authorities/ombudsmen) so plural body names
# still earn the named-body co-occurrence credit.
NAMED_BODY_KEYWORDS = (
    "commission", "board", "authority", "ministry", "agency", "council",
    "task force", "committee", "directorate", "office", "institute",
    "centre", "center", "department", "ombudsman", "inspectorate",
    "agencies", "ministries", "authorities", "ombudsmen",
    # Stem form: Korean-style body names assign duties to "the Minister of
    # Science and ICT" (not "the ministry"), which the literal "ministry"
    # entry cannot match. "minister*" → \bminister\w*\b covers minister,
    # ministers, ministerial — and never "administration" (no word boundary
    # before "minist").
    "minister*",
)
REPORTING_KEYWORDS = (
    "report", "reporting", "reported", "register", "registered", "registry",
    "registries", "publication", "annual report", "disclosure",
    "transparency report", "publish", "published", "publishing",
    "notify", "records", "documentation requirement", "audit trail",
    # Noun stems: the Korea Act's duties are phrased as "advance notification
    # duty" and "labeling/indication requirement", which the verb keyword
    # "notify" misses under word-boundary matching. "notif*" → \bnotif\w*\b
    # covers the whole notification family; "label*" covers labeling/labelling;
    # "indicatio*" covers indication(s) only — never "indicator" or
    # "indicative" (stems diverge after "indicat"), so a performance-
    # indicator mention is not credited as a reporting duty.
    "notif*", "label*", "indicatio*",
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
    r"""Compile a whole-word regex for a phrase/keyword.

    Word boundaries on both sides: "program" matches only the standalone
    word (and its plural "programs"), never inside "programming" or
    "programme"; "roadmap" never matches inside "roadmapping"; "board"
    never matches inside "keyboard". An optional trailing "s" keeps simple
    plurals ("programs", "roadmaps", "initiatives") matching without
    reopening the substring holes. This is the pure regex-boundary fix
    applied everywhere the ladder pattern-matches text.

    A trailing "*" marks a STEM-PREFIX keyword: the stem matches followed by
    any word characters, so one entry covers a word family the "(?:s)?"
    plural cannot — "notif*" compiles to \bnotif\w*\b and matches notify,
    notification, notifications, notified, notifying; "minister*" matches
    minister, ministers, ministerial. Word boundaries still apply on both
    sides, so a stem never reaches inside a longer word: "minister*" never
    matches "administration" (no boundary before "minist"), and
    "indicatio*" never matches "indicator" or "indicative" (their stems
    diverge after "indicat"). This is the same boundary discipline as the
    earlier program/programming fix, applied deliberately where whole-word
    families share a prefix.
    """
    stem_key = phrase.endswith("*")
    cached = _KEYWORD_PATTERN_CACHE.get(phrase)
    if cached is not None:
        return cached
    if stem_key:
        pattern = re.compile(
            r"\b" + re.escape(phrase[:-1]) + r"\w*\b", re.IGNORECASE
        )
    else:
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
    evidence_texts: list[str] | None = None,
) -> tuple[GovernanceMaturity, str]:
    """Compute the Module 1 governance maturity stage from Coverage + mechanisms.

    Four levels, each a strictly stronger claim than the last — Unaddressed
    → Emerging → Operationalized → Institutionalized (see GovernanceMaturity docstring
    for what each level means).

    `operational_mechanisms` is the LLM's own self-reported mechanism list;
    `evidence_texts` (new) is the SAME dimension-grounded, document-sourced
    chunk/sentence text that the coverage ladder (R1/R2) actually used to
    reach its verdict. The two signals are OR-combined before classifying
    named-body/reporting/enforcement presence, so maturity can never
    disagree with the evidence that justified Coverage — the previous
    version scored maturity from the LLM's self-report alone, which could
    diverge from what actually fired R1/R2 (e.g. a ladder-raised Covered
    verdict with an empty self-reported mechanism list scored as
    principle-only, when the raising evidence itself named a mechanism).

    Returns (maturity_stage, reasoning) where reasoning documents which rule
    applied and what evidence it drew on, keeping the decision auditable.
    """
    mechanisms = [m for m in (operational_mechanisms or []) if m and m.strip()]
    mech = classify_mechanisms(mechanisms)
    if evidence_texts:
        ev_body = any(_has_keyword(t, NAMED_BODY_KEYWORDS) for t in evidence_texts if t)
        ev_reporting = any(_has_keyword(t, REPORTING_KEYWORDS) for t in evidence_texts if t)
        ev_enforcement = any(_has_keyword(t, ENFORCEMENT_KEYWORDS) for t in evidence_texts if t)
        mech = {
            "has_named_body": mech["has_named_body"] or ev_body,
            "has_reporting": mech["has_reporting"] or ev_reporting,
            "has_enforcement": mech["has_enforcement"] or ev_enforcement,
        }
        mech["has_operational_mechanism"] = (
            mech["has_named_body"] or mech["has_reporting"] or mech["has_enforcement"]
        )
    cov = coverage.lower()

    if cov == "missing":
        return (
            GovernanceMaturity.UNADDRESSED,
            "Coverage is Missing — no dimension-relevant mechanism or "
            "explicit commitment survived the deterministic ladder, so the "
            "dimension is not meaningfully addressed. Maturity is "
            "Unaddressed (rule: Missing → Unaddressed only).",
        )

    if cov == "partial":
        if mech["has_operational_mechanism"]:
            return (
                GovernanceMaturity.DEVELOPING,
                "Coverage is Partial and a concrete mechanism is present "
                f"(named body={mech['has_named_body']}, reporting="
                f"{mech['has_reporting']}) but without enforcement/redress "
                "evidence — maturity is Operationalized (rule: Partial + "
                "mechanism, no enforcement → Operationalized).",
            )
        return (
            GovernanceMaturity.EMERGING,
            "Coverage is Partial: dimension-relevant terms and an explicit "
            "commitment/intent are present, but no concrete mechanism "
            "(named body or documented process) exists yet — maturity is "
            "Emerging (rule: Partial + no mechanism → Emerging).",
        )

    # Covered
    if mech["has_operational_mechanism"] and mech["has_enforcement"]:
        return (
            GovernanceMaturity.ESTABLISHED,
            "Coverage is Covered with a concrete mechanism AND "
            "enforcement/monitoring/audit/redress evidence — maturity is "
            "Institutionalized (rule: Covered + mechanism + enforcement → "
            "Institutionalized).",
        )
    if mech["has_operational_mechanism"]:
        return (
            GovernanceMaturity.DEVELOPING,
            "Coverage is Covered with a concrete mechanism "
            f"(named body={mech['has_named_body']}, reporting="
            f"{mech['has_reporting']}) but no enforcement/monitoring/redress "
            "evidence yet — maturity is Operationalized (rule: Covered + "
            "mechanism, no enforcement → Operationalized).",
        )
    return (
        GovernanceMaturity.EMERGING,
        "Coverage is Covered at principle/intent level only — no named "
        "body, documented process, or enforcement mechanism found in "
        "either the model's self-report or the grounding evidence. "
        "Maturity is capped at Emerging (rule: Covered without any "
        "mechanism evidence cannot exceed Emerging — a bare Covered label "
        "is not, by itself, proof of an operational mechanism).",
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
#     4. MECHANISM-REPORT co-occurrence (R2 path a): the model's
#        operational-mechanism report only counts as an implementation
#        commitment when a NAMED BODY co-occurs with a reporting or
#        enforcement mechanism in it. A single keyword alone — a lone
#        reporting keyword like "disclosure", or a bare "penalties" — is
#        NOT enough, and neither is a bare named body with nothing
#        alongside it. (This is the tightened bar that fixed the India
#        Transparency false positive: notification/labeling mechanisms
#        with no named body were raising Partial -> Covered against the
#        model's own reasoning.)

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

# Obligation language — the R1 floor's mechanism bar. A dimension-relevant
# passage that IMPOSES a requirement ("shall notify", "must ensure", "is
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
    "shall", "must", "requires", "is required to", "are required to",
    "obligated", "obliges", "mandates", "establishes", "sets out",
    "provides for", "lays down", "prohibits", "ensures that",
    "guarantees", "directs", "instructs", "imposes",
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


def text_contains_mechanism(text: str) -> bool:
    """True when a passage imposes a governance mechanism.

    Mechanism-agnostic: a named body, a reporting/disclosure duty, an
    enforcement/redress duty, or obligation language ("shall", "must",
    "requires"...) in the passage. The same categories apply to every
    dimension — this is the "governance mechanism exists" level of the
    principle → mechanism → operationalized ladder, recognised in the
    policy's own terminology rather than a per-dimension keyword checklist.
    """
    if not text:
        return False
    if _has_keyword(
        text,
        NAMED_BODY_KEYWORDS + REPORTING_KEYWORDS + ENFORCEMENT_KEYWORDS,
    ):
        return True
    return _contains_commitment_phrase(text.lower(), OBLIGATION_VERBS)


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


# ── Core-term precision gate (anti false-positive, collision fix) ───────
#
# DIMENSION_TOPIC_KEYWORDS (above) is deliberately broad — it is a RECALL
# gate for the loose relevance check. That breadth has a failure mode:
# vocabulary that is topically adjacent but NOT about the dimension can
# still match a broad keyword. Confirmed live case: a Korea AI Basic Act
# sentence listing "healthcare, energy, public services" as HIGH-IMPACT AI
# SECTORS matches "Environmental Sustainability" via the bare word "energy"
# and, when it also contains obligation language ("operators shall..."),
# fires R1 — even though the sentence is about sector scoping, not AI's own
# environmental/carbon footprint. Confirmed by the model's own raw output:
# principle_acknowledged=False, operational_mechanisms=[], zero
# document_evidence, yet the ladder still floored Missing → Partial.
#
# CORE_TERMS is a tighter, higher-precision anchor per dimension: unlike
# the topic list, every phrase here is nearly unambiguous evidence the
# sentence is actually ABOUT the dimension's substance (not merely a
# neighbouring sector/domain name). R1/R2 require a core-term hit IN
# ADDITION TO the (looser) semantic/topic gates — recall stays with the
# topic keywords / embedding gate, precision comes from this list.
# ── Sense-disambiguation guard (anti topic-collision) ────────────────────
# Some core terms are genuinely the right vocabulary for a dimension but
# carry a second, unrelated sense in policy prose. Three such collisions were
# confirmed live and each one inflated a verdict:
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
        "transparent financing", "transparent funding", "transparent pricing",
        "transparent procurement", "transparent market", "transparent tax",
        "financial transparency", "fiscal transparency", "budget transparency",
        "transparency in financing", "transparency of markets",
    ),
    "Inclusivity": (
        # "inclusive growth/economy" is an economic-development claim, not a
        # demographic-inclusion governance mechanism.
        "inclusive growth", "inclusive economy", "inclusive economic",
        "financial inclusion", "inclusive development",
    ),
    "Fairness": (
        # "fair market"/"fair competition"/"fair trade" are competition-policy
        # senses, not algorithmic fairness.
        "fair market", "fair competition", "fair trade", "fair value",
        "fair price", "fair pricing", "fair share",
    ),
    "Safety": (
        # Occupational/road/food safety are different policy domains.
        "food safety", "road safety", "occupational safety", "public safety net",
    ),
}


@lru_cache(maxsize=64)
def _exclusion_pattern(dimension: str) -> re.Pattern | None:
    """Compiled matcher for a dimension's off-sense phrases."""
    phrases = DIMENSION_TERM_EXCLUSIONS.get(dimension)
    if not phrases:
        return None
    return re.compile(
        "|".join(ocr_flexible_fragment(p) for p in phrases), re.IGNORECASE
    )


DIMENSION_CORE_TERMS: dict[str, tuple[str, ...]] = {
    "Transparency": (
        "transparen", "disclos", "explainab", "interpretab", "documentation",
        "audit trail", "black box", "black-box",
        # Real-world equivalents of "transparency" in a country's own
        # legal terminology (e.g. Korea's AI Basic Act phrases its
        # transparency duty as "advance notification" + "labeling", never
        # the word "transparency" itself) — the gate must recognize the
        # MECHANISM, not just the abstract vocabulary.
        "notif", "label", "inform users", "inform individuals",
    ),
    "Accountability": (
        # Incident-reporting vocabulary is included because
        # DIMENSION_MECHANISMS lists "incident reporting" as an Accountability
        # mechanism. Without it the two tables contradicted each other: the
        # mechanism audit looked for a mechanism whose own vocabulary this gate
        # filtered out, so the EU AI Act's Article 73 serious-incident duty —
        # present in the retrieved pool — was reported as "incident reporting:
        # not addressed". A mechanism the table expects must have vocabulary
        # the gate admits.
        "accountab", "liabilit", "liable", "redress", "sanction", "penalt",
        "fine", "grievance", "complaint mechanism", "answerable", "duty of care",
        "serious incident", "incident report", "report an incident",
        "notify the authorit", "report to the market surveillance",
    ),
    "Privacy": (
        "privacy", "personal data", "personal information", "data protection",
        "anonymiz", "pseudonymiz", "data subject", "confidential",
    ),
    "Safety": (
        "safety", "safe design", "risk management", "fail-safe", "failsafe",
        "red team", "red-team", "adversarial test", "robustness",
    ),
    "Human Autonomy": (
        "human oversight", "human control", "human-in-the-loop",
        "human in the loop", "override", "human agency", "autonomy",
        "meaningful control", "opt-out",
        # "human oversight" is EU drafting. Other traditions express the same
        # binding duty in their own words, and matching only the EU phrasing
        # silently reports the duty as absent. Korea's AI Framework Act,
        # Article 34(1)(4), requires "Human management and supervision of
        # high-impact AI" under a "must implement the following measures"
        # obligation — Meridian scored Human Autonomy as Missing / Unaddressed
        # / High risk for a law that mandates human oversight of its highest
        # risk tier. GDPR Article 22's "human intervention" was missing for
        # the same reason.
        #
        # All bigrams beginning with "human", deliberately: bare "supervision"
        # and "management" collide with regulatory supervision and corporate
        # management throughout these documents.
        "human management", "human supervision", "human intervention",
        "human review", "human monitoring", "human judgment", "human judgement",
    ),
    "Inclusivity": (
        # Bare "accessib" is deliberately NOT listed (removed after a
        # confirmed live false positive): AI-instrument transparency
        # provisions routinely require information to be "accessible" in the
        # sense of understandable/available ("relevant, accessible and
        # comprehensible information" — EU AI Act Article 13), a Transparency
        # concept with nothing to do with disability/demographic inclusion.
        # A sandbox confidentiality clause restricting data to be "accessible
        # only to market surveillance authorities" hit the same collision.
        # Genuine disability-accessibility content is still caught via
        # "persons with disabilities", "disabilit", and "digital divide"
        # below, so nothing is lost by anchoring the compound instead.
        "inclusiv", "inclusion", "accessibility for persons with disabilities",
        "digital accessibility", "accessible design", "web accessibility",
        "disabilit", "digital divide", "underserved",
        "marginalis", "persons with disabilities", "multi-stakeholder",
        "multistakeholder", "public participation",
    ),
    "Fairness": (
        "fair", "fairness", "bias", "discrimina", "demographic parity",
        "protected characteristics", "stereotype",
    ),
    "Environmental Sustainability": (
        # NOTE: a bare "sustainab" stem is deliberately NOT listed. In policy
        # documents "sustainable" overwhelmingly modifies ECONOMIC growth
        # ("sustainable growth and innovation", "sustainable socio-economic
        # transformation"), which is a different dimension entirely — that
        # collision was scoring a skills-and-curricula sentence as an
        # environmental-sustainability provision. Only environment-anchored
        # forms of the word are counted.
        # "ecosystem" alone is excluded for the same reason as bare
        # "sustainab": in technology policy it overwhelmingly means an
        # INNOVATION ecosystem ("catalyze the AI ecosystem"), not an
        # ecological one — that collision scored a start-up partnership
        # sentence as environmental-sustainability governance.
        # Bare "environment" is deliberately NOT listed either (removed after
        # a confirmed live false positive): EU AI Act incident-reporting
        # language lists "damage to property or the environment" as one of
        # several possible incident consequences alongside critical-
        # infrastructure disruption and fundamental-rights infringements —
        # a real, binding Article 73 SAFETY provision, misclassified as
        # environmental-sustainability governance purely because its last
        # six words happened to contain the bare stem.
        "environmentally sustainable", "environmental sustainability",
        "sustainable development", "ecological", "natural ecosystem",
        "ecosystems and biodiversity", "biodiversity",
        "carbon", "emission", "e-waste", "electronic waste",
        "energy efficiency", "energy consumption", "power consumption",
        "climate", "footprint", "green computing", "green energy",
        "resource consumption", "resource-efficient", "resource efficiency",
        "renewable",
    ),
}


@lru_cache(maxsize=64)
def _core_term_pattern(dimension: str) -> re.Pattern | None:
    """Compiled, OCR-tolerant matcher for a dimension's core terms."""
    terms = DIMENSION_CORE_TERMS.get(dimension)
    if not terms:
        return None
    return re.compile(
        "|".join(ocr_flexible_fragment(t) for t in terms), re.IGNORECASE
    )


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


# ── Sentence-level evidence discipline ───────────────────────────────────
# A retrieved chunk can be a long legal passage where one sentence carries a
# genuine dimension mechanism while another is procedural boilerplate ("the
# Minister shall promote measures to facilitate the production, collection,
# management, distribution, utilization of Learning Data"). The substantive
# gate validates ANY mechanism-bearing sentence of the chunk, so R1/R2 could
# fire using a strong obligation phrase / named body located in a DIFFERENT
# sentence than the one that passed the gate — the co-location leak that let
# a safety mechanism in a mixed Article 32/33 chunk promote Fairness. The
# ladder therefore evaluates evidence SENTENCE by SENTENCE: the sentence
# that carries the commitment/obligation phrase (and the named body for R2)
# must itself pass the dimension + substantive gates.
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


def detect_explicit_commitment(
    operational_mechanisms: list[str] | None,
    document_chunk_texts: list[str] | None,
    dimension: str = "",
    dimension_match_fn: Callable[[str, str], bool] | None = None,
    substantive_match_fn: Callable[[str, str], bool] | None = None,
) -> bool:
    """R1 floor bar: actual attempted mechanism OR explicit commitment.

    Broader than detect_implementation_commitment (the R2 bar). Returns True
    on ANY of:
      (a) a non-empty operational-mechanism report (named body / reporting /
          enforcement-redress, classified with the same keyword sets used by
          governance maturity), or
      (b) a STRONG commitment phrase in a dimension-relevant document chunk
          (programme, initiative, task force, "will establish", ...), or
      (c) an explicit commitment verb in a dimension-relevant chunk
          ("commits to", "plans to", "will ensure", "will address", ...),
          or
      (d) OBLIGATION language in a dimension-relevant chunk ("shall",
          "must", "requires", "prohibits"...) — a requirement the policy
          imposes about the dimension is a governance mechanism expressed
          in the policy's own terminology, so a "shall notify"
          transparency duty floors Missing -> Partial exactly like a
          named-body mechanism would. This is the deterministic
          "principle mentioned → governance mechanism exists"
          distinction: a bare principle mention ("recognizes the
          importance of X") carries no obligation and stays Missing.

    Dimension grounding: chunks are only eligible when they are actually
    topically related to the dimension. The gate is pluggable
    (dimension_match_fn) so the general pipeline can use semantic
    equivalence (chunks whose meaning matches the dimension even when the
    terminology differs) instead of a keyword checklist; the default is
    _chunk_matches_dimension. A UN advisory-body participation paragraph
    containing "will support" is NOT Accountability evidence and never
    fires R1.

    SUBSTANTIVE grounding (anti-false-positive): when the pipeline supplies
    a substantive_match_fn, the evidence carrying the commitment/obligation
    language must ALSO be substantively about the dimension's operational
    content — not merely pass the loose relevance gate. This is the
    "procedural authority ≠ substantive governance mechanism" rule: a
    provision that merely assigns a minister or body a power to
    approve/support/administer something ("the Minister may approve/support
    AI data centres", "shall promote measures to facilitate the production,
    collection, management, distribution, utilization of learning data") is
    NOT a governance mechanism for Environmental Sustainability unless it
    actually establishes environmental governance requirements.

    SENTENCE-LEVEL discipline: the gates are evaluated on the SENTENCE that
    carries the phrase, not the whole chunk. A long chunk can contain a
    genuine dimension mechanism in one sentence and procedural boilerplate
    with obligation language in another — the co-located boilerplate must
    not fire R1 ("the same evidence that contains the commitment language
    must itself pass the substantive gate").

    A bare risk acknowledgment with no proposed action attached matches
    none of these and returns False — such a document stays Missing.
    Negated occurrences ("will not support", "not committed to") never count.
    """
    fired, _ = detect_explicit_commitment_evidence(
        operational_mechanisms, document_chunk_texts, dimension,
        dimension_match_fn, substantive_match_fn,
    )
    return fired


def detect_explicit_commitment_evidence(
    operational_mechanisms: list[str] | None,
    document_chunk_texts: list[str] | None,
    dimension: str = "",
    dimension_match_fn: Callable[[str, str], bool] | None = None,
    substantive_match_fn: Callable[[str, str], bool] | None = None,
) -> tuple[bool, str]:
    """Same rule as detect_explicit_commitment, but also returns the actual
    matched sentence (empty string when the mechanism-report path fired
    instead of a chunk sentence) — so the ladder's reasoning can quote real
    evidence instead of a generic rule description."""
    if classify_mechanisms(operational_mechanisms)["has_operational_mechanism"]:
        return True, ""
    match = dimension_match_fn or _chunk_matches_dimension
    substantive = substantive_match_fn or match
    for text in document_chunk_texts or []:
        for sentence in _split_sentences(text):
            if dimension and not (
                match(sentence, dimension)
                and substantive(sentence, dimension)
                # Precision gate: the sentence must ALSO contain a
                # high-precision core term for the dimension, not merely
                # pass the broader relevance/substantive checks — blocks
                # sector-name collisions (e.g. "energy" in a HIGH-IMPACT-AI
                # sector list matching Environmental Sustainability).
                and _sentence_has_core_term(sentence, dimension)
            ):
                continue
            lower = sentence.lower()
            if (
                _contains_commitment_phrase(lower, STRONG_COMMITMENT_PHRASES)
                or _contains_commitment_phrase(lower, EXPLICIT_COMMITMENT_VERBS)
                or _contains_commitment_phrase(lower, OBLIGATION_VERBS)
            ):
                return True, sentence
    return False, ""


def detect_implementation_commitment(
    operational_mechanisms: list[str] | None,
    document_chunk_texts: list[str] | None,
    dimension: str = "",
    dimension_match_fn: Callable[[str, str], bool] | None = None,
    substantive_match_fn: Callable[[str, str], bool] | None = None,
) -> bool:
    """Detect Level-3+ implementation-commitment evidence.

    Three independent signals, any of which suffices:
      (a) the model's own operational-mechanism report shows a NAMED BODY
          co-occurring with a reporting/enforcement mechanism (classified
          with the same keyword sets used by governance maturity) — the
          same co-occurrence standard as path (b). A single keyword alone
          (a lone reporting keyword like "disclosure", or a bare
          "penalties") is NOT enough, and neither is a bare named body
          with nothing alongside it; this is the tightened bar that fixed
          the India Transparency false positive (labeling/notification
          mechanisms with no named body must not raise), or
      (b) the retrieved document chunks contain a STRONG commitment phrase
          (programme, initiative, task force, "will establish", "setting
          up", roadmap, ...) THAT CO-OCCURS WITH A NAMED-BODY/INSTITUTION
          KEYWORD IN THE SAME CHUNK — a bare programme/initiative mention
          in an off-topic passage (AI security, events calendar) is not an
          implementation commitment, or
      (c) WEAK commitment phrases co-occur with a named-body keyword in the
          same chunk, or appear in at least two distinct chunks.

    Dimension grounding: only chunks actually topically related to the
    dimension are eligible. The gate is pluggable (dimension_match_fn) so
    the general pipeline can use semantic equivalence instead of a keyword
    checklist; the default is _chunk_matches_dimension. Deterministic and
    document-agnostic — the same detector runs for any uploaded policy. It
    never judges the verdict; it only reports whether commitment language
    exists.

    SUBSTANTIVE grounding (anti-false-positive): when the pipeline supplies
    a substantive_match_fn, the evidence carrying the implementation
    language must be substantively about the dimension's operational
    content — Covered must rest on substantive implementation evidence, not
    merely a named authority + mandate. A procedural authority provision
    ("the Minister may approve/support AI data centres") carries
    implementation language but is not a substantive governance mechanism
    for the dimension; it can neither raise to Covered nor corroborate weak
    phrases.

    SENTENCE-LEVEL discipline: paths (b)/(c) are evaluated on the SENTENCE
    that carries the strong phrase and the named body, not the whole chunk.
    A long chunk can contain a genuine dimension mechanism in one sentence
    and an unrelated strong obligation phrase / named body in another — the
    same evidence sentence that contains the strong implementation phrase
    and/or named responsible body must itself pass the substantive
    dimension gate before it can trigger the R2 promotion. Co-located
    evidence elsewhere in the chunk never satisfies the requirement (the
    fix for the mixed Article 32/33 chunk that promoted Fairness on a
    safety provision).
    """
    fired, _ = detect_implementation_commitment_evidence(
        operational_mechanisms, document_chunk_texts, dimension,
        dimension_match_fn, substantive_match_fn,
    )
    return fired


def detect_implementation_commitment_evidence(
    operational_mechanisms: list[str] | None,
    document_chunk_texts: list[str] | None,
    dimension: str = "",
    dimension_match_fn: Callable[[str, str], bool] | None = None,
    substantive_match_fn: Callable[[str, str], bool] | None = None,
) -> tuple[bool, str]:
    """Same rule as detect_implementation_commitment, but also returns the
    matched sentence (empty when the mechanism-report path fired) for
    quoting real evidence in the ladder's reasoning."""
    mech = classify_mechanisms(operational_mechanisms)
    # Path (a) — tightened: a mechanism report is a concrete implementation
    # commitment only when a named body co-occurs with a reporting OR
    # enforcement mechanism (the same co-occurrence standard as path (b)).
    # A lone reporting keyword ("disclosure") — the India Transparency
    # false positive — or a bare named body alone must never raise.
    if mech["has_named_body"] and (mech["has_reporting"] or mech["has_enforcement"]):
        return True, ""
    match = dimension_match_fn or _chunk_matches_dimension
    substantive = substantive_match_fn or match
    weak_hits = 0
    for text in document_chunk_texts or []:
        chunk_weak = False
        for sentence in _split_sentences(text):
            if dimension and not (
                match(sentence, dimension)
                and substantive(sentence, dimension)
                # Precision gate — same collision fix as R1 (see
                # DIMENSION_CORE_TERMS docstring).
                and _sentence_has_core_term(sentence, dimension)
            ):
                continue
            lower = sentence.lower()
            if (
                _contains_commitment_phrase(lower, STRONG_COMMITMENT_PHRASES)
                and _has_keyword(sentence, NAMED_BODY_KEYWORDS)
            ):
                return True, sentence
            if _contains_commitment_phrase(lower, WEAK_COMMITMENT_PHRASES):
                chunk_weak = True
                if _has_keyword(sentence, NAMED_BODY_KEYWORDS):
                    return True, sentence
        if chunk_weak:
            weak_hits += 1
    return weak_hits >= 2, ""


def validate_coverage_deterministic(
    coverage: CoverageLevel,
    principle_acknowledged: bool,
    operational_mechanisms: list[str] | None,
    document_chunks: list[dict[str, Any]] | None = None,
    dimension: str = "",
    dimension_match_fn: Callable[[str, str], bool] | None = None,
    substantive_match_fn: Callable[[str, str], bool] | None = None,
) -> tuple[CoverageLevel, list[str]]:
    """Deterministic coverage validation for the combined Module 1+2 path.

    Reinstates the governance-ladder enforcement (R1 + R2 above) that the
    merged single-call pipeline dropped. Returns
    (validated_coverage, applied_rule_notes); the caller appends the notes
    to the coverage reasoning so the explainability chain stays transparent.

    `dimension` grounds the ladder: chunks are only eligible to fire R1/R2
    when they are topically related to the dimension being evaluated.
    `dimension_match_fn` plugs in the pipeline's semantic-equivalence gate
    (chunks whose MEANING matches the dimension even when the terminology
    differs, e.g. an "advance notification" duty for Transparency or a
    "confidentiality" duty for Privacy); the default is the keyword gate
    _chunk_matches_dimension.

    `substantive_match_fn` (anti-false-positive) plugs in the pipeline's
    SUBSTANTIVE-specificity gate: when supplied, a chunk must ALSO be
    substantively about the dimension's operational content to fire R1/R2 —
    a procedural authority provision ("the Minister may approve/support AI
    data centres") passes the loose relevance gate but is not a governance
    mechanism for Environmental Sustainability, so it stays inert. When
    None, the substantive gate defaults to the dimension gate (no stricter
    bar) for backward compatibility.
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
    # document must show an actual attempted mechanism, an explicit
    # commitment, or OBLIGATION language about the dimension (a mechanism
    # expressed in the policy's own terminology). (principle_acknowledged is
    # deliberately NOT used here: it is exactly the permissive signal that
    # used to inflate "mentioned once" into Partial.)
    r1_fired = False
    if LADDER_FLOOR_ENABLED and cov == CoverageLevel.MISSING and has_doc_evidence:
        r1_fired, r1_sentence = detect_explicit_commitment_evidence(
            operational_mechanisms, chunk_texts, dimension=dimension,
            dimension_match_fn=dimension_match_fn,
            substantive_match_fn=substantive_match_fn,
        )
        if r1_fired:
            cov = CoverageLevel.PARTIAL
            quote = f' Firing evidence: "{r1_sentence[:220]}"' if r1_sentence else ""
            applied.append(
                "R1 explicit-commitment floor: the document shows an actual "
                "attempted mechanism, an explicit commitment, or an obligation "
                "imposing a governance mechanism with retrieved evidence "
                "(establishment language, programme/initiative, named body, "
                "roadmap, mandate, an explicit commitment verb, or obligation "
                "language such as shall/must/requires); a bare risk "
                "acknowledgment with no proposed action does not satisfy this "
                "bar. Level 1 (Governance Recognised) maps to Partial — Missing "
                f"was raised.{quote}"
            )

    # R2 — implementation-commitment raise. Fires ONLY on Partial: R1 is the
    # only rule that rescues a Missing verdict, so disabling the floor is
    # observable. A Missing dimension with commitment language is raised to
    # Partial by R1 first (when enabled) and then to Covered here.
    if cov == CoverageLevel.PARTIAL and has_doc_evidence:
        r2_fired, r2_sentence = detect_implementation_commitment_evidence(
            operational_mechanisms, chunk_texts, dimension=dimension,
            dimension_match_fn=dimension_match_fn,
            substantive_match_fn=substantive_match_fn,
        )
        if r2_fired:
            cov = CoverageLevel.COVERED
            quote = f' Firing evidence: "{r2_sentence[:220]}"' if r2_sentence else ""
            applied.append(
                "R2 implementation-commitment raise: the document (or the "
                "model's own mechanism report) shows a concrete implementation "
                "commitment — a named body/institution co-occurring with a "
                "reporting/enforcement mechanism or with programme/initiative, "
                "establishment language, roadmap or mandate in "
                "dimension-relevant evidence; a lone mechanism keyword (e.g. "
                "a single reporting keyword like 'disclosure') with no named "
                "body does NOT satisfy this bar; Level 3 (Implementation "
                f"Commitment Exists) maps to Covered — Partial was raised.{quote}"
            )

    return cov, applied


_FIRING_QUOTE_RE = re.compile(r'Firing evidence: "([^"]*)"')


def plain_language_ladder_note(coverage_rules: list[str]) -> str:
    """Translate the ladder's technical rule-audit strings into one short,
    plain-language sentence for END USERS.

    `coverage_rules` (from validate_coverage_deterministic) is written for
    developers/tests — "R1 explicit-commitment floor", "Level 1 (Governance
    Recognised) maps to Partial" — and must never reach a user-facing field
    (coverage_reasoning, reason_flagged). This is the ONLY translation of
    that audit trail a user should see: what changed, and — when the ladder
    quoted a real sentence — what specifically justified it. The technical
    strings themselves stay available for logs/tests via the original
    `coverage_rules` list.
    """
    if not coverage_rules:
        return ""
    combined = " ".join(coverage_rules)
    r1_rule = next((r for r in coverage_rules if r.startswith("R1")), None)
    r2_rule = next((r for r in coverage_rules if r.startswith("R2")), None)

    def _quote(rule: str | None) -> str:
        if not rule:
            return ""
        m = _FIRING_QUOTE_RE.search(rule)
        return m.group(1)[:180] if m else ""

    parts: list[str] = []
    if r1_rule:
        note = "Raised from Missing to Partial: the document commits to acting on this"
        q = _quote(r1_rule)
        if q:
            note += f' — for example, it states: "{q}"'
        note += ", even though no governing body, reporting requirement, or enforcement process is defined for it yet."
        parts.append(note)
    if r2_rule:
        note = (
            "Raised from Partial to Covered: the document assigns this to a "
            "named body and includes a reporting or enforcement mechanism"
        )
        q = _quote(r2_rule)
        if q:
            note += f' — for example: "{q}"'
        note += "."
        parts.append(note)
    if not parts and combined:
        # Defensive fallback for a future rule label this function doesn't
        # recognize yet — never show the raw technical string.
        parts.append("The coverage level was adjusted based on evidence found in the document.")
    return " ".join(parts)


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
