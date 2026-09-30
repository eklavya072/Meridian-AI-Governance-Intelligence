"""Executive Brief synthesis — reads the ALREADY-COMPUTED, citation-verified
analysis results stored for a workspace and compresses them into a 1-2 page
decision-maker brief. This is a synthesis task, not a re-analysis: exactly one
LLM call (the narrative sections), and every number / statistic in the brief is
assembled deterministically in code so the model can never invent one.

Sections split:
  - LLM-written (one call): executive summary, key findings (strengths /
    attention areas), priority recommendations.
  - Deterministic (code, from stored data): header, dimension assessment,
    implementation roadmap, evidence base, relevant precedent (from Module 4
    matches), scope & methodology (reuses the stored scope disclaimer
    verbatim).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, Field

from src.provider_router import generate_with_retry, get_provider

logger = structlog.get_logger()


# ── LLM-written narrative schema ──────────────────────────────────────────


class BriefPriorityRecommendation(BaseModel):
    """One selected recommendation with a one-line rationale. Both fields are
    drawn ONLY from the digest — the model compresses, never invents."""

    recommendation: str = Field(..., description="One sentence, from the digest only")
    rationale: str = Field(..., description="One line, from the digest only")


class BriefSynthesis(BaseModel):
    """The ONLY LLM-generated part of the brief.

    Fields are deliberately permissive (lists may be empty) so a validation
    failure can never force a retry loop — empties are rendered honestly
    ("None identified") by the assembly code.
    """

    executive_summary: str = Field(
        ..., description="4-6 sentences, max 160 words, synthesizing the digest"
    )
    areas_of_strength: list[str] = Field(
        default_factory=list, description="2-4 bullets, each max 50 words"
    )
    areas_requiring_attention: list[str] = Field(
        default_factory=list,
        description="Up to 5 bullets, each max 50 words. Empty when every dimension is fully covered.",
    )
    priority_recommendations: list[BriefPriorityRecommendation] = Field(
        default_factory=list,
        description="3-6 items from the highest-priority gapped dimensions only. Empty when no gaps.",
    )


BRIEF_SYSTEM_PROMPT = (
    "You are an executive brief writer for AI governance assessments. You are "
    "given the already-computed, citation-verified results of a governance gap "
    "analysis. Your ONLY job is to synthesize and compress that material into a "
    "decision-maker-ready narrative.\n\n"
    "STRICT RULES (anti-fabrication — the same discipline as the rest of this project):\n"
    "1. You may only restate, compress, and re-order information present in the DIGEST.\n"
    "2. You must NOT introduce: new numbers, new dimensions, new framework names, new "
    "recommendations, or new claims of any kind.\n"
    "3. If a section has little material (e.g. no Partial/Missing dimensions), write it "
    "honestly short. Never pad with generic filler to hit a length target.\n"
    "4. Do not copy recommendation text verbatim — compress it into your own words while "
    "keeping every substantive element.\n"
    "5. Tone: precise, neutral, decision-maker oriented. No marketing language.\n\n"
    "PER-SECTION WORD BUDGETS (enforce exactly):\n"
    "- executive_summary: 4-6 sentences, max 160 words total. State the overall "
    "posture, name the strongest and weakest dimensions, and say what kind of "
    "instrument this is (binding, soft law, strategy) — that framing is what a "
    "decision-maker reads first.\n"
    "- areas_of_strength: 2-4 bullets, each max 50 words, one per finding.\n"
    "- areas_requiring_attention: up to 5 bullets, each max 50 words. If every dimension "
    "is fully covered, return an empty list.\n"
    "- priority_recommendations: 3-6 items total, selected from the highest-priority "
    "gapped dimensions only. Each recommendation is one sentence; each rationale is one "
    "line drawn from the digest. If there are no gapped dimensions, return an empty list."
)


# ── Digest builders (compact, prompt-budget-friendly) ─────────────────────


def build_dimension_digest(gaps: list[dict[str, Any]]) -> str:
    """Compress each dimension's stored verdict into a few lines. The LLM's
    only allowed source of facts — every claim here was already computed and
    citation-verified during the analysis run."""
    lines: list[str] = []
    for g in gaps:
        dim = g.get("dimension") or "Unknown"
        coverage = g.get("coverage") or "Unknown"
        lines.append(f"- {dim}: Coverage {coverage}")
        m1 = g.get("module_1") or {}
        if m1.get("implementation_depth"):
            lines.append(f"  Implementation depth: {m1['implementation_depth']}")
        # What the verdict rests on, and what is missing, so the summary can
        # say what kind of instrument this is from counts rather than guess.
        # Stored runs carry the counts sentence; newer ones state the same
        # counts in risk_basis.
        evidence = g.get("evidence_confidence_reason") or g.get("risk_basis")
        if evidence:
            lines.append(f"  Evidence: {evidence}")
        missing = _absent_mechanisms(g)[:3]
        if missing:
            lines.append("  Mechanisms not established: " + "; ".join(missing))
        m2 = g.get("module_2") or {}
        if m2.get("priority"):
            lines.append(f"  Priority: {m2['priority']}")
        recs = [r for r in (m2.get("recommendations") or []) if r]
        if recs:
            lines.append("  Recommendations (from the analysis):")
            for r in recs[:3]:
                lines.append(f"    - {r}")
        elif coverage == "Covered":
            bp = m2.get("best_practices") or {}
            opps = [o for o in (bp.get("future_strengthening_opportunities") or []) if o]
            if opps:
                lines.append("  Fully covered — future strengthening opportunities:")
                for o in opps[:2]:
                    lines.append(f"    - {o}")
        if g.get("analysis_error"):
            # Never the provider's error: the model restates this digest, and
            # "API keys exhausted" has no business in a ministry's brief.
            lines.append("  [Not assessed on this run — no finding either way]")
    return "\n".join(lines) if lines else "(no dimension results available)"


def build_brief_prompt(
    digest: str,
    decision: dict[str, Any] | None,
    num_dimensions: int,
) -> str:
    parts: list[str] = []
    parts.append("=== GOVERNANCE ANALYSIS DIGEST (the ONLY allowed source of facts) ===")
    parts.append(digest)
    parts.append("")
    parts.append("=== EXECUTIVE AGGREGATES (computed by the analysis — use them as-is) ===")
    if decision:
        parts.append(f"Assessed dimensions: {decision.get('assessed_dimensions', num_dimensions)}")
        parts.append(
            f"Coverage distribution: {decision.get('covered', 0)} Covered, "
            f"{decision.get('partial', 0)} Partial, "
            f"{decision.get('missing', 0)} Missing"
        )
        if decision.get("implementation_depth_index") is not None:
            parts.append(
                f"Implementation depth index (force, 0-100): "
                f"{decision['implementation_depth_index']}"
            )
        if decision.get("mechanisms_total"):
            parts.append(
                f"Mechanism breadth: {decision.get('mechanisms_met', 0)} of "
                f"{decision['mechanisms_total']} expected mechanisms present; "
                f"{decision.get('mechanisms_binding', 0)} of those carried by a binding duty"
            )
        strongest = decision.get("strongest_dimension")
        if strongest:
            parts.append(f"Strongest dimension: {strongest}")
        prio = decision.get("highest_priority_dimensions") or []
        if prio:
            parts.append(f"Highest-priority dimensions: {', '.join(prio)}")
    else:
        parts.append(f"Assessed dimensions: {num_dimensions}")
    parts.append("")
    parts.append("Write the executive brief now. Return ONLY the JSON object matching the schema.")
    return "\n".join(parts)


# ── Deterministic sections (code-computed, never LLM) ─────────────────────


def build_relevant_precedent(gaps: list[dict[str, Any]]) -> str | None:
    """The one-sentence lead for the precedent section; the incidents
    themselves are listed by build_precedents. Deterministic: reads the
    already-verified incident matches."""
    incident_names: list[str] = []
    for g in gaps:
        m4 = g.get("module_4") or {}
        for inc in m4.get("incident_matches") or []:
            name = (inc.get("incident_name") or "").strip()
            if name and name not in incident_names:
                incident_names.append(name)
    if not incident_names:
        return None
    if len(incident_names) == 1:
        return (
            "The analysis matched one real-world incident that shows where a gap "
            "like this can lead. It is context for the verdict, not a finding "
            "about the document."
        )
    return (
        f"The analysis matched {len(incident_names)} real-world incidents that "
        "show where gaps like these can lead. They are context for the verdicts, "
        "not findings about the document."
    )


def _first_sentences(text: str, limit: int = 260) -> str:
    """The opening sentence or two of a passage, within `limit` characters."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind(". ")
    if end >= 80:
        return cut[: end + 1]
    return cut[: cut.rfind(" ")].rstrip(",;:") + "\u2026"


def build_precedents(gaps: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    """The matched incidents themselves: what happened, which dimensions it
    bears on, and the lesson, each in a sentence or two, with its source.

    Everything here is already stored with the match; nothing is written for
    the brief.
    """
    order: list[str] = []
    found: dict[str, dict[str, Any]] = {}
    for g in gaps:
        m4 = g.get("module_4") or {}
        for inc in m4.get("incident_matches") or []:
            name = (inc.get("incident_name") or "").strip()
            if not name:
                continue
            dim = g.get("dimension") or ""
            if name in found:
                if dim and dim not in found[name]["dimensions"]:
                    found[name]["dimensions"].append(dim)
                continue
            order.append(name)
            found[name] = {
                "incident": name,
                "dimensions": [dim] if dim else [],
                "what_happened": _first_sentences(inc.get("what_happened") or ""),
                "lesson": _first_sentences(inc.get("lessons_learned") or ""),
                "source": (inc.get("source") or "").strip(),
            }
    return [found[n] for n in order[:limit]]


def build_dimension_assessment(
    gaps: list[dict[str, Any]], documents: list[str] | None = None
) -> list[dict[str, Any]]:
    """Per-dimension detail: what was actually found for each dimension.

    Everything here is already computed and already
    verified: the coverage tier, the depth stage, the evidence-derived risk
    basis, and which of the mechanisms the dimension calls for are absent.

    Two reference lines give a minister something to check or cite: the
    bodies and instruments the document names for the dimension, and one of
    its own provisions, quoted with its page.

    Deterministic by construction — no LLM involvement in the brief, so
    extending it this way adds length without adding a single new place for
    the model to invent something.
    """
    rows: list[dict[str, Any]] = []
    provisions = _assign_key_provisions(gaps, documents)
    for g, provision in zip(gaps, provisions, strict=True):
        if g.get("analysis_error"):
            rows.append(
                {
                    "dimension": g.get("dimension", ""),
                    "coverage": "Not assessed",
                    "depth": "",
                    "basis": "This dimension could not be assessed on this run. "
                    "It is not a finding about the document.",
                    "absent_mechanisms": [],
                    "in_place": [],
                    "key_provision": None,
                }
            )
            continue
        rows.append(
            {
                "dimension": g.get("dimension", ""),
                "coverage": g.get("coverage", ""),
                "depth": g.get("implementation_depth", "") or "",
                # risk_basis states what the document contains and what it lacks;
                # coverage_reasoning is the fuller narrative and is the fallback.
                # The trailing "Not addressed: ..." clause is stripped because the
                # absent mechanisms are rendered as their own structured line —
                # leaving it in printed the same list twice in consecutive lines.
                "basis": _ABSENT_RE.sub(
                    "", (g.get("risk_basis") or g.get("coverage_reasoning") or "")
                ).strip(),
                "absent_mechanisms": _absent_mechanisms(g),
                "in_place": _named_mechanisms(g),
                "key_provision": provision,
            }
        )
    return rows


def _named_mechanisms(gap: dict[str, Any], limit: int = 4) -> list[str]:
    """The bodies and instruments the document names for this dimension, as
    the evaluation recorded them ("Artificial Intelligence Commissioner (named
    body)"), in the order it listed them."""
    m1 = gap.get("module_1") or {}
    out: list[str] = []
    for item in m1.get("operational_mechanisms") or []:
        text = " ".join(str(item).split())
        if text and text not in out:
            out.append(text)
    return out[:limit]


# A provision that states a rule reads as the document's commitment; a
# preamble sentence around it does not.
_NORM_RE = re.compile(
    r"\b(shall|must|is required to|are required to|has the right|have the right|"
    r"is prohibited|are prohibited|may not|shall not)\b",
    re.IGNORECASE,
)
_QUOTE_LIMIT = 260


def _is_document_evidence(e: dict[str, Any], evaluated: set[str]) -> bool:
    """Whether a piece of evidence is the assessed document's own text.

    A dimension's evidence also holds the framework passages it was compared
    against, and printing one of those unlabelled under a country's
    dimension presented a UNESCO sentence as that country's own text. The
    run's list of evaluated documents is the test whenever it exists; only a
    record without one falls back to "the source is its own file".
    """
    name = e.get("document_name") or ""
    if evaluated:
        return name in evaluated
    return bool(name) and name == e.get("source_framework")


_TERMINAL = (".", ";", ":", "!", "?", ")", "\u201d", '"')
# Checkbox and bullet glyphs from forms and slide decks. NFKC also folds the
# typographic ligatures PDFs carry ("proﬁling" -> "profiling").
_SCORING_GRID_RE = re.compile(r"(?:\d\s*[\u2610\u2611\u2612]\s*)+(?:\d{1,3}\.\s)?")
# A word broken across a line ("high- impact"), and a list item's number.
_LINE_HYPHEN_RE = re.compile(r"(\w)- (\w)")
_ITEM_NUMBER_RE = re.compile(r"^\d{1,3}\.\s+")
_FORM_GLYPH_RE = re.compile(r"[\u2610\u2611\u2612\u25a0\u25a1\u25aa\u25cf]")
# A sentence boundary a quote can start from when its passage opens mid-way.
_SENTENCE_START_RE = re.compile(r"[.;:]\s+(?=[A-Z(\u201c\"])")


def _clean_start(text: str) -> tuple[str, bool]:
    """A passage cut out of the middle of a sentence ("qual access, gender
    equality...") starts at its next sentence if one begins early enough;
    otherwise it is marked as an excerpt. Returns the text and whether it
    now opens on a sentence."""
    if text[:1].isupper() or text[:1].isdigit() or text[:1] in '(\u201c"':
        return text, True
    m = _SENTENCE_START_RE.search(text[:160])
    if m and len(text) - m.end() >= 80:
        return text[m.end() :], True
    return "\u2026" + text.split(" ", 1)[-1], False


def _trim_quote(text: str) -> str:
    """At most _QUOTE_LIMIT characters, opening on a sentence where it can
    and ending on one where one fits, otherwise on a whole word marked with
    an ellipsis. Passages are chunks of the document, so either end may fall
    mid-word ("...any interested s")."""
    text = unicodedata.normalize("NFKC", text)
    text = _SCORING_GRID_RE.sub(" ", text)  # "2 ☐ 1 ☐ 0 ☐ 29. " between items
    text = _FORM_GLYPH_RE.sub(" ", text)
    text = _LINE_HYPHEN_RE.sub(r"\1-\2", " ".join(text.split()))
    text = _ITEM_NUMBER_RE.sub("", text)
    text, _ = _clean_start(text)
    if len(text) > _QUOTE_LIMIT:
        cut = text[:_QUOTE_LIMIT]
        end = max(cut.rfind(". "), cut.rfind("; "))
        if end >= 120:
            return cut[: end + 1]
        text = cut
    elif text.endswith(_TERMINAL):
        return text
    # The last token may be a fragment of a word, so it goes.
    return text.rsplit(" ", 1)[0].rstrip(",;:\u2014-") + "\u2026"


def _provision_candidates(gap: dict[str, Any], evaluated: set[str]) -> list[dict[str, Any]]:
    if gap.get("analysis_error"):
        return []
    return [
        e
        for e in gap.get("evidence") or []
        if e.get("verified")
        and _is_document_evidence(e, evaluated)
        and len((e.get("text") or e.get("quote") or "").strip()) > 60
    ]


def _assign_key_provisions(
    gaps: list[dict[str, Any]], documents: list[str] | None = None
) -> list[dict[str, str] | None]:
    """One verified provision from the assessed document per dimension, in
    the order of `gaps`.

    Per dimension: a passage that has not been quoted under another dimension
    of this brief, then one free of form glyphs (checkbox scoring grids),
    then one that states a rule, then one that opens on a sentence, then the
    closest match. Dimensions with the fewest passages choose first, so a
    dimension's only provision is not spent on another dimension first. A
    passage is reused only when a dimension has nothing else.
    """
    evaluated = set(documents or [])
    pools = [_provision_candidates(g, evaluated) for g in gaps]
    chosen: list[dict[str, str] | None] = [None] * len(gaps)
    quoted: set[str] = set()
    for idx in sorted(range(len(gaps)), key=lambda k: len(pools[k])):
        if not pools[idx]:
            continue

        def rank(e: dict[str, Any]) -> tuple[bool, bool, bool, bool, float]:
            text = " ".join((e.get("text") or e.get("quote") or "").split())
            return (
                _trim_quote(text) not in quoted,
                not _FORM_GLYPH_RE.search(text),
                bool(_NORM_RE.search(text)),
                _clean_start(text)[1],
                e.get("similarity_score") or 0.0,
            )

        best = max(pools[idx], key=rank)
        quote = _trim_quote(best.get("text") or best.get("quote") or "")
        quoted.add(quote)
        chosen[idx] = {"quote": quote, "source": _evidence_source(best)}
    return chosen


# Stripped from the basis prose because the same list is rendered as its own
# line. Three wordings, one per generation of the mechanism summary.
_ABSENT_RE = re.compile(
    r"(?:[Nn]ot addressed|[Nn]ot established|Absent mechanisms include):\s*([^.]+)\."
)


def _absent_mechanisms(gap: dict[str, Any]) -> list[str]:
    """The mechanisms the dimension lacks, most widely expected first.

    Read from the structured fields the analysis stores, not parsed back out
    of prose. The prose parser matched "Not addressed:", which the mechanism
    summary stopped writing when it moved to naming each gap with how many
    reference instruments expect it — after which the brief showed absent
    mechanisms for 20 of the 42 dimensions that had them. Japan's Privacy,
    missing data minimisation, purpose limitation and data subject rights,
    printed nothing.

    Every absent mechanism is listed, because each is a fact about the
    document. The count is attached only where the instruments broadly agree
    (framework_salience.PRIORITY_FLOOR), for the reason given there: "expected
    by 4 of 43" beside a real gap reads as an argument against fixing it.
    """
    absent = list(gap.get("mechanisms_absent") or [])
    if not absent:
        for field in ("risk_basis", "coverage_reasoning"):
            m = _ABSENT_RE.search(str(gap.get(field) or ""))
            if m:
                return [x.strip() for x in m.group(1).split(",") if x.strip()]
        return []

    # priority_gaps holds exactly the consensus mechanisms, already ranked and
    # counted when the analysis ran, so the brief needs no corpus access of
    # its own: those lead with their count, the rest follow as stored.
    corpus = gap.get("framework_corpus_size") or 0
    ranked = [
        (r["mechanism"], r.get("expected_by", 0))
        for r in gap.get("priority_gaps") or []
        if r.get("mechanism") in absent
    ]
    counted = {name for name, _ in ranked}
    out = [
        f"{name} (expected by {n} of {corpus} reference instruments)" if corpus and n else name
        for name, n in ranked
    ]
    return out + [name for name in absent if name not in counted]


def build_implementation_roadmap(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sequenced actions for the gapped dimensions, from Module 3.

    Module 3 already produces phased, timeline-reasoned plans with a
    document-grounded responsible agency, and none of it reached the brief —
    a decision-maker got recommendations with no indication of ordering,
    duration or ownership. Ordered by coverage severity so Missing dimensions
    lead.
    """
    severity = {"Missing": 0, "Partial": 1, "Covered": 2}
    ordered = sorted(
        (
            g
            for g in gaps
            if not g.get("analysis_error") and (g.get("module_3") or {}).get("phases")
        ),
        key=lambda g: severity.get(g.get("coverage", ""), 3),
    )
    out: list[dict[str, Any]] = []
    for g in ordered:
        m3 = g.get("module_3") or {}
        phases = []
        for ph in m3.get("phases") or []:
            steps = [str(x).strip() for x in (ph.get("steps") or []) if str(x).strip()]
            if not steps:
                continue
            phases.append(
                {
                    "phase": (ph.get("phase") or "").strip(),
                    "timeline": (ph.get("timeline") or "").strip(),
                    "objective": (ph.get("objective") or "").strip(),
                    "steps": steps[:4],
                }
            )
        if not phases:
            continue
        out.append(
            {
                "dimension": g.get("dimension", ""),
                "coverage": g.get("coverage", ""),
                "responsible_agency": (m3.get("responsible_agency") or "").strip(),
                "phases": phases,
                "monitoring": [
                    str(x).strip() for x in (m3.get("monitoring_checklist") or []) if str(x).strip()
                ][:3],
            }
        )
    return out


# Download debris in an uploaded file's name: a random id before it
# ("117ojp1ilnxmmvseo01-Egypt National...") or a browser's copy counter after
# it ("Artificial_Intelligence_Policy__1_").
_DOWNLOAD_ID_RE = re.compile(r"^(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{12,}-")
_COPY_SUFFIX_RE = re.compile(r"(?:__\d+_|\s\(\d+\))$")


def document_label(file_name: str) -> str:
    """A document's name as a reader should see it: no extension, no
    download debris, spaces for underscores."""
    name = re.sub(r"\.pdf$", "", file_name or "", flags=re.IGNORECASE)
    name = _COPY_SUFFIX_RE.sub("", _DOWNLOAD_ID_RE.sub("", name))
    return " ".join(name.replace("_", " ").split())


def _evidence_source(e: dict[str, Any]) -> str:
    """ "<document>, p. N" for a quote, so a reader can find it."""
    name = document_label(str(e.get("document_name") or ""))
    page = str(e.get("page_number") or "").strip()
    return f"{name}, p. {page}" if name and page and page != "None" else name


def precedent_lines(p: dict[str, Any]) -> list[str]:
    """One precedent as lines of text, identical in every rendering."""
    head = p["incident"]
    if p.get("dimensions"):
        head += f" ({', '.join(p['dimensions'])})"
    out = [head]
    if p.get("what_happened"):
        out.append(f"What happened: {p['what_happened']}")
    if p.get("lesson"):
        out.append(f"Lesson: {p['lesson']}")
    if p.get("source"):
        out.append(f"Source: {p['source']}")
    return out


def key_provision_line(k: dict[str, str]) -> str:
    """A dimension's quoted provision, identical in every rendering."""
    source = f" ({k['source']})" if k.get("source") else ""
    return f"Key provision: \u201c{k['quote']}\u201d{source}"


def format_evidence_quote(q: dict[str, str]) -> str:
    """One evidence-base line, identical in every rendering of the brief."""
    source = f" ({q['source']})" if q.get("source") else ""
    return f"{q['dimension']} — \u201c{q['quote']}\u201d{source}"


def build_evidence_base(
    gaps: list[dict[str, Any]],
    documents: list[str] | None = None,
    shown: set[str] | None = None,
) -> dict[str, Any]:
    """What the assessment actually rests on.

    A brief that reports verdicts without showing the evidence asks to be
    taken on trust. These counts and quotes come from citations that already
    passed verification against their source chunk, so nothing here is a new
    claim — it is the existing evidence chain, surfaced.

    Quotes are drawn from the assessed document(s) only, each with its page
    (_is_document_evidence). `shown` holds the passages the dimension
    assessment already quotes, so the same sentence is not printed twice.
    """
    evaluated = set(documents or [])
    shown = shown or set()

    total = verified = 0
    quotes: list[dict[str, str]] = []
    for g in gaps:
        for e in g.get("evidence") or []:
            total += 1
            if e.get("verified"):
                verified += 1
        # One representative verified quote per gapped dimension, longest
        # first (the longest verified passage is reliably the most
        # substantive, and short fragments read as filler in a brief).
        if g.get("coverage") in ("Partial", "Missing") and not g.get("analysis_error"):
            candidates = [
                e
                for e in (g.get("evidence") or [])
                if e.get("verified")
                and _is_document_evidence(e, evaluated)
                and len((e.get("text") or e.get("quote") or "").strip()) > 80
                and _evidence_source(e) + _trim_quote(e.get("text") or e.get("quote") or "")
                not in shown
            ]
            if candidates:
                best = max(candidates, key=lambda e: len(e.get("text") or e.get("quote") or ""))
                quotes.append(
                    {
                        "dimension": g.get("dimension", ""),
                        "quote": " ".join((best.get("text") or best.get("quote") or "").split())[
                            :320
                        ],
                        "source": _evidence_source(best),
                    }
                )
    return {
        "citations_total": total,
        "citations_verified": verified,
        "representative_quotes": quotes[:4],
    }


def build_scope_and_methodology(
    scope_disclaimer: str,
    frameworks_used: list[str],
    documents: list[str],
    num_dimensions: int,
) -> str:
    """Scope & Methodology in a few lines: the stored scope disclaimer
    verbatim (never regenerated), then one sentence on how the verdicts were
    reached. The reference instruments are counted, not listed; listing all
    43 made this the longest section of a two-page brief."""
    source = "document" if len(documents) == 1 else "documents"
    against = (
        f"{len(frameworks_used)} international reference instruments"
        if frameworks_used
        else "the core international reference instruments"
    )
    method = (
        f"Method: each of the {num_dimensions} governance dimensions was scored "
        f"by code from the provisions found in the {source}, graded from a "
        f"stated aspiration to an enforceable duty, and compared against "
        f"{against}. Every quotation here was checked against its source page."
    )
    return f"{scope_disclaimer}\n\n{method}"


# ── Assembly + orchestration ──────────────────────────────────────────────


def assemble_brief(
    *,
    workspace_id: str,
    country: str,
    policy_title: str,
    document_name: str,
    documents: list[str],
    frameworks_used: list[str],
    scope_disclaimer: str,
    gaps: list[dict[str, Any]],
    synthesis: BriefSynthesis,
    decision_analytics: dict[str, Any] | None,
    generated_at: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the full structured brief from LLM narrative + deterministic
    sections. This exact dict is what gets persisted (reports.meta) and what
    both exporters (DOCX/PDF) and the frontend render from."""
    if not generated_at:
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    coverage_summary = {
        "covered": sum(1 for g in gaps if g.get("coverage") == "Covered"),
        "partial": sum(1 for g in gaps if g.get("coverage") == "Partial"),
        "missing": sum(1 for g in gaps if g.get("coverage") == "Missing"),
        # A dimension that FAILED to analyse carries coverage "Insufficient
        # Evidence" AND analysis_error, so counting both unguarded double-counts
        # it and the five buckets stop summing to the dimension total. Genuine
        # insufficient-evidence (assessed, but nothing found to judge on) is a
        # real verdict; a provider/quota failure is not. Mirrors the same guard
        # already applied in GapAnalyzer._generate_summary.
        "insufficient_evidence": sum(
            1
            for g in gaps
            if g.get("coverage") == "Insufficient Evidence" and not g.get("analysis_error")
        ),
        "analysis_failed": sum(1 for g in gaps if g.get("analysis_error")),
    }
    precedent = build_relevant_precedent(gaps)
    precedents = build_precedents(gaps)
    dimension_assessment = build_dimension_assessment(gaps, documents)
    implementation_roadmap = build_implementation_roadmap(gaps)
    evidence_base = build_evidence_base(
        gaps,
        documents,
        shown={
            r["key_provision"]["source"] + r["key_provision"]["quote"]
            for r in dimension_assessment
            if r.get("key_provision")
        },
    )
    scope_and_methodology = build_scope_and_methodology(
        scope_disclaimer=scope_disclaimer,
        frameworks_used=frameworks_used,
        documents=documents,
        num_dimensions=len(gaps),
    )

    return {
        "workspace_id": workspace_id,
        "country": country,
        "policy_title": policy_title,
        "document_name": document_name,
        "documents": documents,
        "generated_at": generated_at,
        "num_dimensions": len(gaps),
        "frameworks_used": frameworks_used,
        "scope_disclaimer": scope_disclaimer,
        "coverage_summary": coverage_summary,
        "sections": {
            "executive_summary": (synthesis.executive_summary or "").strip(),
            "areas_of_strength": [s.strip() for s in synthesis.areas_of_strength if s.strip()],
            "areas_requiring_attention": [
                s.strip() for s in synthesis.areas_requiring_attention if s.strip()
            ],
            "priority_recommendations": [
                {
                    "recommendation": r.recommendation.strip(),
                    "rationale": r.rationale.strip(),
                }
                for r in synthesis.priority_recommendations
                if r.recommendation.strip()
            ],
            # Deterministic depth: per-dimension detail, the sequenced Module 3
            # roadmap, and the verified evidence the verdicts rest on. All read
            # from stored analysis, so the brief gets longer without the model
            # getting more room to invent.
            "dimension_assessment": dimension_assessment,
            "implementation_roadmap": implementation_roadmap,
            "evidence_base": evidence_base,
            "relevant_precedent": precedent,
            "precedents": precedents,
            "scope_and_methodology": scope_and_methodology,
        },
        # Deterministic analytics for dashboards / research (same shape as
        # decision_analytics so downstream consumers can reuse it).
        "decision_analytics": decision_analytics or {},
        # What produced the analysis this brief summarises, plus the model
        # that wrote the brief's narrative. Rendered in both exports.
        "provenance": provenance or {},
    }


def generate_brief(
    *,
    workspace_id: str,
    country: str,
    policy_title: str,
    document_name: str,
    documents: list[str],
    frameworks_used: list[str],
    scope_disclaimer: str,
    gaps: list[dict[str, Any]],
    decision_analytics: dict[str, Any] | None = None,
    analysis_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the ONE synthesis call and assemble the brief.

    Routes through the shared provider abstraction (Gemini primary with key
    rotation, RPD/RPM throttling) exactly like analysis calls —
    this call is never a separate, unguarded path.
    """
    provider = get_provider()
    digest = build_dimension_digest(gaps)
    prompt = build_brief_prompt(
        digest=digest,
        decision=decision_analytics,
        num_dimensions=len(gaps),
    )
    synthesis = generate_with_retry(
        provider=provider,
        prompt=prompt,
        schema=BriefSynthesis,
        system_prompt=BRIEF_SYSTEM_PROMPT,
        operation="brief_synthesis",
    )

    brief = assemble_brief(
        workspace_id=workspace_id,
        country=country,
        policy_title=policy_title,
        document_name=document_name,
        documents=documents,
        frameworks_used=frameworks_used,
        scope_disclaimer=scope_disclaimer,
        gaps=gaps,
        synthesis=synthesis,
        decision_analytics=decision_analytics,
        provenance={**(analysis_provenance or {}), "brief_llm_model": provider.model_name},
    )

    logger.info(
        "brief_synthesis_complete",
        workspace_id=workspace_id,
        document_name=document_name,
        num_dimensions=len(gaps),
        summary_chars=len(brief["sections"]["executive_summary"]),
        strengths=len(brief["sections"]["areas_of_strength"]),
        attention=len(brief["sections"]["areas_requiring_attention"]),
        recommendations=len(brief["sections"]["priority_recommendations"]),
        precedent=bool(brief["sections"]["relevant_precedent"]),
        provider=provider.model_name,
    )
    return brief


def render_brief_markdown(brief: dict[str, Any]) -> str:
    """Plain-text/markdown rendering of the structured brief — stored in
    reports.content as a readable fallback (the DOCX/PDF exporters build from
    the structured dict, not this string)."""
    s = brief["sections"]
    lines: list[str] = []
    lines.append(f"# {brief['country']} — {brief['policy_title']}")
    lines.append("AI Governance Assessment Brief")
    lines.append(
        f"Generated {brief['generated_at']} · Based on analysis of "
        f"{brief['num_dimensions']} governance dimensions"
    )
    lines.append("")
    lines.append("## EXECUTIVE SUMMARY")
    lines.append(s["executive_summary"])
    lines.append("")
    lines.append("## KEY FINDINGS")
    lines.append("### Areas of Strength")
    if s["areas_of_strength"]:
        lines.extend(f"- {b}" for b in s["areas_of_strength"])
    else:
        lines.append("- None identified.")
    lines.append("### Areas Requiring Attention")
    if s["areas_requiring_attention"]:
        lines.extend(f"- {b}" for b in s["areas_requiring_attention"])
    else:
        lines.append("- None identified.")
    lines.append("")
    rows = s.get("dimension_assessment") or []
    if rows:
        lines.append("## DIMENSION ASSESSMENT")
        for r in rows:
            head = f"### {r['dimension']} — {r['coverage']}"
            if r.get("depth"):
                head += f" · {r['depth']}"
            lines.append(head)
            if r.get("basis"):
                lines.append(r["basis"])
            if r.get("in_place"):
                lines.append("Named in the document: " + "; ".join(r["in_place"]) + ".")
            if r.get("absent_mechanisms"):
                lines.append("Mechanisms not addressed: " + ", ".join(r["absent_mechanisms"]) + ".")
            if r.get("key_provision"):
                lines.append(key_provision_line(r["key_provision"]))
            lines.append("")
    lines.append("## PRIORITY RECOMMENDATIONS")
    recs = s["priority_recommendations"]
    if recs:
        for i, r in enumerate(recs, 1):
            lines.append(f"{i}. **{r['recommendation']}** — {r['rationale']}")
    else:
        lines.append("No critical gaps identified — no priority actions required.")
    roadmap = s.get("implementation_roadmap") or []
    if roadmap:
        lines.append("")
        lines.append("## IMPLEMENTATION ROADMAP")
        for item in roadmap:
            lines.append(f"### {item['dimension']} ({item['coverage']})")
            if item.get("responsible_agency"):
                lines.append(f"Responsible body: {item['responsible_agency']}")
            for ph in item["phases"]:
                label = ph["phase"] or "Phase"
                if ph.get("timeline"):
                    label += f" · {ph['timeline']}"
                lines.append(f"**{label}** — {ph.get('objective', '')}")
                lines.extend(f"- {st}" for st in ph["steps"])
            if item.get("monitoring"):
                lines.append("Monitoring:")
                lines.extend(f"- {mc}" for mc in item["monitoring"])
            lines.append("")

    ev = s.get("evidence_base") or {}
    if ev.get("citations_total"):
        lines.append("")
        lines.append("## EVIDENCE BASE")
        lines.append(
            f"{ev['citations_verified']} of {ev['citations_total']} citations "
            "were verified against their source passage."
        )
        for q in ev.get("representative_quotes") or []:
            lines.append(f"- {format_evidence_quote(q)}")

    if s.get("relevant_precedent"):
        lines.append("")
        lines.append("## RELEVANT PRECEDENT")
        lines.append(s["relevant_precedent"])
        for p in s.get("precedents") or []:
            lines.append("")
            lines.extend(precedent_lines(p))
    lines.append("")
    lines.append("## SCOPE & METHODOLOGY")
    lines.append(s["scope_and_methodology"])
    lines.append("")
    return "\n".join(lines)
