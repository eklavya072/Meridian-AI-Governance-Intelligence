"""What Meridian is, and why it scores the way it does.

The chat surfaces could answer questions about AI governance and about the
frameworks in the knowledge base, but not about the instrument asking the
questions. "Why eight dimensions?", "what frameworks do you use?", "why is
your maturity scale five stages?" all landed on retrieval, found nothing —
no document in the corpus describes Meridian — and came back either refusing
or improvising. A tool that cannot explain its own method is not defensible
in front of a policy specialist, which is the whole bar this project is held
to.

So the method is stated here, once, as context the LLM is given rather than
as canned replies. Everything countable is DERIVED from the live constants —
the dimension list, the tier labels, the stage scores, the mechanism
vocabulary, the framework roster read out of the vector store. A hand-typed
description drifts the first time a threshold moves; an imported one cannot.
The prose explains only the reasoning that no constant can carry.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from src.evidence_strength import DIMENSION_MECHANISMS, TIER_LABELS
from src.gap_analyzer import GOVERNANCE_DIMENSIONS, MATURITY_STAGE_SCORE

logger = structlog.get_logger()


# ── Which questions are about the instrument itself ──────────────────────
#
# Two families, and they are deliberately separate. A question can be about
# the METHOD ("why eight dimensions", "how do you decide Partial") or about
# the CORPUS ("what frameworks do you use", "why not add more frameworks").
# Both need the method brief, but only the second needs the roster pulled
# out of the vector store, which costs a query.

_METHOD_MARKERS = re.compile(
    r"\b("
    # Self-reference: you/your/this tool, paired with a method word.
    r"(why|how|what)\s+(do|does|did|are|is|would)?\s*(you|your|this (tool|system|app|instrument|platform))|"
    r"your (method|methodology|approach|scale|scoring|score|rating|analysis|assessment|framework|criteria|rubric)|"
    # The scoring machinery by name.
    r"(normative[- ]force|force ladder|binding force|coverage index|maturity index|"
    r"maturity (stage|scale|level)s?|binding share|force bar|"
    r"aspirational|intentional|assigned|obligatory|enforceable)\b.*\b(mean|means|work|works|why|how|scale|defined?)|"
    # Dimension-count questions.
    r"(why|how many|which)\s+.{0,24}\bdimensions?\b|"
    r"\bdimensions?\b.{0,30}(do you|are used|why|not more|instead of|chosen|picked|selected)|"
    # Scoring-decision questions phrased about the verdicts themselves.
    r"how (do|does|is|are)\s+.{0,30}\b(scored|score|rated|graded|decided|determined|assessed|calculated|computed)\b|"
    r"what (makes|counts as|qualifies as)\s+.{0,24}(covered|partial|missing|binding|enforceable)|"
    # Limitations / honesty questions.
    r"(what|where)\s+.{0,20}(limitation|limitations|weakness|blind spot|cannot|can'?t you|don'?t you)\b|"
    r"(rank|ranking|compare countries|country score|overall score|single score)"
    r")",
    re.IGNORECASE,
)

_CORPUS_MARKERS = re.compile(
    r"\b("
    r"(what|which|how many)\s+.{0,30}\bframeworks?\b|"
    r"\bframeworks?\b.{0,40}(do you (use|have)|are (you )?using|in your|available|indexed|knowledge base)|"
    r"(why|why not)\s+.{0,40}\b(framework|frameworks)\b|"
    r"(add|adding|more|other|additional)\s+frameworks?|"
    r"(knowledge base|corpus|reference (set|library))"
    r")",
    re.IGNORECASE,
)


def is_method_question(message: str) -> bool:
    """Is this a question about Meridian itself rather than about policy?

    Kept lenient. A false positive costs a few hundred tokens of method
    context on a prompt that did not need it; a false negative is the
    failure this module exists to remove.
    """
    text = (message or "").strip()
    if not text:
        return False
    return bool(_METHOD_MARKERS.search(text) or _CORPUS_MARKERS.search(text))


def is_corpus_question(message: str) -> bool:
    """Narrower: does the answer need the actual framework roster?"""
    text = (message or "").strip()
    return bool(text and _CORPUS_MARKERS.search(text))


# ── The method, stated ───────────────────────────────────────────────────

def _dimension_line() -> str:
    return ", ".join(GOVERNANCE_DIMENSIONS)


def _ladder_line() -> str:
    return " → ".join(
        f"T{tier} {label}" for tier, label in sorted(TIER_LABELS.items())
    )


def _stage_line() -> str:
    ordered = sorted(MATURITY_STAGE_SCORE.items(), key=lambda kv: kv[1])
    return ", ".join(
        f"{stage.value if hasattr(stage, 'value') else stage} ({int(score)})"
        for stage, score in ordered
    )


def _mechanism_counts() -> tuple[int, str]:
    total = sum(len(m) for m in DIMENSION_MECHANISMS.values())
    per_dim = ", ".join(
        f"{dim} {len(mechs)}" for dim, mechs in DIMENSION_MECHANISMS.items()
    )
    return total, per_dim


def build_method_context() -> str:
    """The instrument's own method as prompt context.

    Written as facts the model may use and attribute to Meridian, not as a
    script to recite — the answer still has to be shaped to the question
    that was actually asked.
    """
    mech_total, mech_per_dim = _mechanism_counts()
    return "\n".join([
        "--- How Meridian Works (the instrument being used right now) ---",
        "",
        "PURPOSE. Meridian reads a national AI policy document and reports, per "
        "governance dimension, how much of the dimension the document addresses "
        "and how much normative force it carries. It is an assessment instrument, "
        "not a compliance checker and not a country league table.",
        "",
        f"THE {len(GOVERNANCE_DIMENSIONS)} DIMENSIONS: {_dimension_line()}.",
        "",
        "WHY THESE, AND WHY NOT MORE. They are the commitments that recur across "
        "the instruments in the knowledge base — UNESCO's Recommendation, the OECD "
        "AI Principles, the EU AI Act, the NIST AI RMF — so a verdict on any one of "
        "them can be grounded in more than one framework's requirements rather than "
        "one author's taxonomy. Dimensions are deliberately NOT split finer: every "
        "extra dimension divides the same document into thinner evidence, and a "
        "verdict resting on one or two sentences is exactly the kind of claim this "
        "instrument is built to avoid. Adjacent concerns are handled as mechanisms "
        "INSIDE a dimension instead — explainability under Transparency, "
        "non-discrimination under Fairness, redress under Accountability.",
        "",
        "WHAT IS NOT COVERED. The dimensions describe how a state governs AI. They "
        "say nothing about state CAPACITY to build or deploy AI — compute, skills, "
        "data infrastructure, public-sector adoption. Against UNDP's AI Landscape "
        "Assessment, Meridian speaks to the AI Regulation and Ethics pillar and "
        "parts of the ecosystem pillar; it does not assess AI for Government at all. "
        "Read it as one instrument among several, not a readiness index.",
        "",
        f"NORMATIVE-FORCE LADDER. Every finding is graded {_ladder_line()}. "
        "T0 is a value statement, T1 an intention, T2 a task given to a named body, "
        "T3 a duty someone owes, T4 a duty backed by a consequence or a supervisory "
        "power. The ladder follows the Abbott and Snidal legalization framework "
        "(obligation, precision, delegation) — this is what makes the scores "
        "arguable on their merits rather than arbitrary.",
        "",
        "THE FORCE BAR. A dimension only reads as fully covered when the document "
        "carries two binding findings, or one binding finding paired with an "
        "enforceable one. Not simply 'one binding sentence exists': the tier "
        "counters are cumulative, so a single binding sentence also lifts every "
        "weaker counter beneath it. Pairing a duty with actual enforcement is the "
        "one genuinely independent signal available.",
        "",
        f"MATURITY STAGES, with the score each is worth: {_stage_line()}. The gaps "
        "between stages are not uniform, which is why explicit stage scores replaced "
        "an earlier rank average — treating the distance from Emerging to Delegated "
        "as equal to the distance from Operationalized to Institutionalized "
        "understated strong statutes and flattered weak ones.",
        "",
        "TWO AXES, REPORTED SEPARATELY. Coverage index is the share of the "
        f"{mech_total} framework-required mechanisms the document addresses at all "
        f"({mech_per_dim}). Binding force (the maturity index) is how much duty sits "
        "behind what it addresses. Binding share bridges them: of the mechanisms "
        "present, how many are carried by an actual duty. These are kept apart on "
        "purpose. One number cannot say both 'this document addresses nearly "
        "everything' and 'it binds almost nobody', and soft-law instruments read "
        "high on the first and low on the second. The interesting cases are exactly "
        "where the two diverge.",
        "",
        "NO SINGLE COUNTRY SCORE, AND NO RANKING. Meridian does not aggregate the "
        "dimensions into one headline number for a country, and does not rank "
        "countries against each other. Comparison across countries is a comparison "
        "of what specific instruments do — not of who is 'ahead'.",
        "",
        "EVIDENCE DISCIPLINE. Every verdict cites the document. Citations are "
        "verified against the retrieved passages and the full document text, and "
        "citations that cannot be traced are surfaced rather than quietly kept. A "
        "dimension the model could not assess is excluded from scoring instead of "
        "guessed at — a wrong verdict is worse than a missing one.",
        "",
        "WHAT THE FRAMEWORKS ARE FOR. They supply the requirements a dimension is "
        "read against and the comparative narrative. They do NOT set the verdict: "
        "the verdict comes from the country document's own text through the force "
        "ladder. Framework alignment was tested as a scoring input and rejected, "
        "because it rewards a document for resembling an international instrument "
        "rather than for binding anyone.",
        "",
        "KNOWN LIMITS, STATED PLAINLY. Meridian measures enforceable normative "
        "force in the text as written. It cannot see whether a duty is enforced in "
        "practice, whether a named regulator is funded or staffed, or what case law "
        "has done to a provision since. A country with strong implementation and "
        "thin drafting will score below what its practice deserves; that is a scope "
        "choice, not an oversight.",
    ])


# ── The corpus, as it actually stands ────────────────────────────────────

# Grouping is by the job a source does in the pipeline, because that is the
# question people are really asking when they ask "why these frameworks" —
# not "which PDFs did you load" but "what is each one for".
_ROSTER_ROLES: dict[str, tuple[str, ...]] = {
    "Core normative instruments (supply the requirements each dimension is read against)": (
        "UNESCO Recommendation on the Ethics of AI",
        "OECD AI Principles",
        "EU AI Act",
        "NIST AI Risk Management Framework",
        "UN Global Digital Compact",
        "UN Roadmap for Digital Cooperation",
        "UNDP Digital Strategy",
    ),
    "Regional instruments (so the reference set is not exclusively European)": (
        "ASEAN Guide on AI Governance and Ethics",
        "African Union Continental AI Strategy",
        "Singapore Model AI Governance Framework",
        "G7 Hiroshima AI Process",
    ),
    "Dimension-specific technical sources (bias, explanation, oversight, privacy, environment)": (
        "NIST SP 1270",
        "CDEI Review into Bias",
        "ICO",
        "Model Cards",
        "CIPL",
        "UNESCO Ethical Impact Assessment",
        "Keeping an Eye on AI",
        "carbon",
        "Sustainab",
        "Environment",
        "Digital Divides",
        "Digital Inclusion",
        "Accessibility",
        "AI Verify",
        "OECD Catalogue",
        "Cybersecurity",
    ),
    "Incident and case evidence (grounds the case-intelligence matching)": (
        "AI Incident Database",
        "Robodebt",
        "Allegheny",
    ),
    "Development context (how AI governance lands in developing economies)": (
        "World Development Report",
        "Digital Progress and Trends",
    ),
}


def _role_for(name: str) -> str | None:
    for role, markers in _ROSTER_ROLES.items():
        if any(m.lower() in name.lower() for m in markers):
            return role
    return None


def build_corpus_context(vector_store: Any) -> str:
    """The live framework roster, grouped by the job each source does.

    Read from the vector store rather than listed here, so a sync that adds
    or drops a framework is reflected the next time someone asks. Returns an
    empty string on failure — a chat turn should never fail because the
    roster could not be counted.
    """
    # The frameworks config, not the vector store's metadata. A scan of chunk
    # metadata also sweeps up every uploaded country document and each name
    # variant a sync has ever written, which is how an earlier version of this
    # answered "97 sources" when the library holds 33. The config is the same
    # list the Frameworks page renders, so the two cannot disagree.
    try:
        from src.framework_library import get_framework_library

        library = get_framework_library(vector_store)
    except Exception as exc:
        logger.warning("meridian_facts_roster_failed", error=str(exc)[:200])
        return ""

    names = [f.get("name", "") for f in library if f.get("indexed") and f.get("name")]
    if not names:
        return ""

    grouped: dict[str, list[str]] = {role: [] for role in _ROSTER_ROLES}
    other: list[str] = []
    for name in sorted(names):
        role = _role_for(name)
        if role:
            grouped[role].append(name)
        else:
            other.append(name)

    lines = [
        "--- Frameworks Actually Indexed in Meridian's Knowledge Base ---",
        "",
        f"{len(names)} sources are indexed. They are not all the same kind of "
        "thing, and the mix is deliberate:",
        "",
    ]
    for role, members in grouped.items():
        if not members:
            continue
        lines.append(f"{role}:")
        for m in members:
            lines.append(f"  • {m}")
        lines.append("")
    if other:
        lines.append("Additional indexed sources:")
        for m in other:
            lines.append(f"  • {m}")
        lines.append("")
    lines.append(
        "WHY THIS SET. The core instruments are the ones national policies are "
        "actually written against, so a requirement traced to them is a "
        "requirement the drafters plausibly had in view. The regional entries "
        "are there because a reference set built only from OECD and EU sources "
        "would measure every country against a European drafting tradition. The "
        "technical sources exist because a dimension like Fairness needs a "
        "concrete mechanism vocabulary — bias testing, impact assessment — and "
        "principles documents do not supply one."
    )
    lines.append("")
    lines.append(
        "WHY NOT MORE. Adding frameworks that restate the same commitments adds "
        "retrieval competition without adding requirements: near-duplicate "
        "passages crowd out distinct ones in a fixed retrieval budget. A source "
        "earns a place by contributing a requirement, a mechanism vocabulary, or "
        "incident evidence that nothing already indexed provides."
    )
    return "\n".join(lines)


def build_self_knowledge_context(message: str, vector_store: Any = None) -> str:
    """Method brief, plus the roster when the question calls for it."""
    parts = [build_method_context()]
    if vector_store is not None and is_corpus_question(message):
        roster = build_corpus_context(vector_store)
        if roster:
            parts.append("")
            parts.append(roster)
    return "\n".join(parts)
