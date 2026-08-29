"""AI Rapporteur Chat — combines intelligent intent classification
with LLM-powered enrichment when available.

Architecture:
  1. Guardrails check (loosened for governance topics)
  2. Retrieval from vector store (document + framework chunks)
  3. AI Rapporteur generates a structured base response
  4. LLM enriches the response with retrieved context when available
  5. If LLM fails, the template response is returned directly (graceful degradation)
"""

from __future__ import annotations

import os
import re
import time
from collections import OrderedDict
from typing import Any

import structlog

from src.analysis_brief import (
    build_analysis_overview_context,
    is_analysis_overview_question,
)
from src.document_overview import (
    build_overview_context,
    build_overview_prompt,
    build_overview_system_prompt,
    is_document_specific_question,
    needs_full_analysis,
    retrieve_document_overview,
)
from src.governance_advisor import (
    Intent,
    SessionContext,
    _gap_to_finding_context,
    build_concept_response,
    build_educational_response,
    generate_response,
)
from src.guardrails import SCOPE_MESSAGE, Guardrails
from src.meridian_facts import (
    build_self_knowledge_context,
    is_method_question,
)
from src.provider_router import generate_text_with_retry, get_provider
from src.vectorstore import VectorStore
from src.verify import (
    classify_narrative_citations,
    verify_chat_citation,
    verify_citation,
)

logger = structlog.get_logger()

MAX_HISTORY_MESSAGES = 6

# Chat modes:
#   "advisor"           -> Mode A (general educational, unscoped) when no
#                          finding context; Mode C (per-finding drill-down)
#                          when finding_context is present.
#   "document_overview" -> Mode B (whole-document overview, workspace-scoped,
#                          broad section-stratified retrieval + grounding).
#   "framework_qa"      -> knowledge-base-only Framework Q&A bot.
#   "auditor"           -> The merged AI Auditor (single bot): document
#                          questions route to Mode B, general governance /
#                          framework questions route to the advisor layer with
#                          the merged system prompt. No separate bot tabs.
CHAT_MODES = ("advisor", "framework_qa", "document_overview", "auditor")


def build_framework_qa_system_prompt() -> str:
    """System prompt for the Framework Q&A bot — grounded only in the
    international governance knowledge base, never the uploaded policy."""
    return (
        "You are the AI Governance Framework Librarian, an expert guide to the "
        "international AI governance knowledge base. Ground every answer in the "
        "retrieved framework passages you are given.\n\n"
        "Guidelines:\n"
        "1. Answer conversationally and precisely, citing the framework(s) that "
        'support each point as [Framework Name]: "exact passage".\n'
        "2. Synthesize across frameworks where relevant (UNESCO Recommendation on "
        "the Ethics of AI, OECD AI Principles, EU AI Act, NIST AI RMF, UNDP Digital "
        "Strategy, UN Global Digital Compact, UN Roadmap for Digital Cooperation, "
        "ASEAN and AU guides).\n"
        "3. When frameworks differ or are silent on a question, say so explicitly — "
        "do not merge them into a false consensus.\n"
        "4. Distinguish binding regulation (e.g. the EU AI Act) from voluntary "
        "principles and recommendations.\n"
        "5. Never invent passages, provisions, or citations. If the retrieved "
        "context does not support the answer, say the knowledge base lacks that "
        "detail.\n"
        "Keep answers focused and substantive."
    )


def build_auditor_greeting() -> str:
    """Greeting for the merged AI Auditor bot — one bot, both abilities: the
    uploaded policy document AND the international governance knowledge base.
    (Guardrails block greetings by default, so this bot answers them
    directly instead.)"""
    return (
        "Hello! I'm the AI Auditor. I answer three kinds of question:\n\n"
        "**AI governance concepts** — what transparency or safety actually means, "
        "what the governance dimensions cover, how binding force differs from "
        "coverage.\n\n"
        "**The frameworks** — all 33 sources in the knowledge base, including "
        "UNESCO, the OECD AI Principles, the EU AI Act, NIST AI RMF, the G7 "
        "Hiroshima process, ASEAN and the African Union: what each says on a "
        "topic, and where they disagree.\n\n"
        "**Meridian itself** — why eight dimensions, how a verdict is decided, "
        "what the tool cannot see.\n\n"
        "Upload a policy PDF and I'll also answer what that document says, and "
        "quote it back to you.\n\nTry asking:\n"
        '• "Why eight dimensions and not more?"\n'
        '• "What does NIST AI RMF say about accountability?"\n'
        '• "How does the G7 Hiroshima process handle safety?"\n'
        '• Upload a PDF, then: "Where does this mention environmental rules?"\n\n'
        "For scoring a document — how it compares against a framework, what it "
        "should improve — run it through the Analysis section; that produces the "
        "graded verdicts a chat answer can't."
    )


def build_framework_qa_greeting() -> str:
    """Greeting for the Framework Q&A bot — guards block greetings by default,
    so this bot answers them directly instead."""
    return (
        "Hello! I'm the Framework Librarian — I answer questions grounded in the "
        "international AI governance knowledge base: the UNESCO Recommendation on "
        "the Ethics of AI, OECD AI Principles, EU AI Act, NIST AI RMF, UNDP "
        "Digital Strategy, UN Global Digital Compact, UN Roadmap for Digital "
        "Cooperation, and regional guides (ASEAN, African Union).\n\n"
        "Try asking:\n"
        "• What does the UNESCO Recommendation say about transparency?\n"
        "• How does the EU AI Act classify high-risk AI?\n"
        "• What is the difference between the OECD AI Principles and the EU AI Act?\n"
        "• What are the five NIST AI RMF functions?"
    )


def build_full_analysis_referral(has_document: bool) -> str:
    """Point a scoring question at the pipeline that can actually score.

    Deliberately not an LLM call. The answer does not depend on the question's
    wording, it returns instantly — which is the cheapest latency win
    available — and hard-coding it removes any chance of the model talking
    itself into a verdict on the way past.
    """
    if has_document:
        return (
            "That needs a full analysis rather than a chat answer — comparing a "
            "document against a framework, saying what it should improve, or "
            "laying out an implementation plan all rest on the per-dimension "
            "verdicts, and I would only be guessing at those from a handful of "
            "retrieved passages.\n\n"
            "Run it through the **Analysis** section instead. Upload the document "
            "to a workspace there and start a run: it scores all eight governance "
            "dimensions, grades each finding for normative force, and produces the "
            "gap breakdown, the recommendations and the implementation roadmap "
            "with citations back to the text. Once that run finishes, the AI "
            "Rapporteur beside the results will answer this properly.\n\n"
            "In the meantime I can tell you what this document actually says on "
            "any topic — ask me directly and I will quote it."
        )
    return (
        "That needs a full analysis rather than a chat answer, and no document is "
        "loaded here yet.\n\n"
        "Upload the policy in the **Analysis** section and start a run — it scores "
        "all eight governance dimensions, grades each finding for normative force, "
        "and returns the gaps, recommendations and roadmap with citations. The AI "
        "Rapporteur beside those results will then answer comparison and "
        "improvement questions from the real verdicts.\n\n"
        "I can still answer general governance questions, or anything about the "
        "frameworks in the knowledge base, right now."
    )


def build_context_from_retrieval(retrieved: list[dict[str, Any]], top_k: int) -> str:
    lines = []
    for i, r in enumerate(retrieved[:top_k], 1):
        meta = r.get("metadata", {})
        fw = meta.get("framework", "Uploaded Document")
        section = meta.get("section", "")
        page = meta.get("page_number", "")
        source_info = fw
        if section:
            source_info += f", {section}"
        if page:
            source_info += f" (p. {page})"
        lines.append(f"[{i}] Source: {source_info}")
        lines.append(r.get("text", ""))
        lines.append("")
    return "\n".join(lines)


def build_drill_down_context(finding_context: dict[str, Any]) -> str:
    """Full deterministic reasoning trail for Mode C (per-finding drill-down).

    The point of this context is that "why is this Partial and not Missing"
    must be answered from the ACTUAL computed reasoning — the deterministic
    ladder rules (R1/R2 trigger details embedded in coverage_reasoning), the
    maturity rule applied, the confidence GeoMean components, and the Module
    3+4 roadmap/incident evidence when present — never a vague restatement.
    """
    ctx = finding_context or {}
    lines = [
        f"Dimension: {ctx.get('dimension', 'Unknown')}",
        f"Coverage: {ctx.get('coverage', 'Unknown')}",
    ]

    # Deterministic ladder / coverage reasoning — R1/R2 triggers, floors,
    # raises are embedded here by the analyzer; pass verbatim.
    coverage_reasoning = ctx.get("coverage_reasoning") or ctx.get("reason_flagged")
    if coverage_reasoning:
        lines.append(f"Coverage reasoning (deterministic ladder rules): {coverage_reasoning}")
    # Fully Covered tier: the document-grounded examples that justified the
    # verdict — useful for "what in the doc made it Covered".
    coverage_example = ctx.get("coverage_example")
    if coverage_example:
        lines.append(f"Coverage examples (from the document): {coverage_example}")

    if ctx.get("gap_found") is not None:
        lines.append(f"Gap detected: {ctx.get('gap_found')}")

    maturity = ctx.get("governance_maturity")
    if maturity:
        lines.append(f"Governance maturity: {maturity}")
        maturity_reasoning = ctx.get("maturity_reasoning")
        if maturity_reasoning:
            lines.append(f"  Maturity rule applied: {maturity_reasoning}")

    risk = ctx.get("risk_level")
    if risk:
        lines.append(f"Risk Level: {risk}")
        if ctx.get("risk_reason"):
            lines.append(f"  Risk reason: {ctx.get('risk_reason')}")

    # Confidence GeoMean components — the calibrated confidence method string
    # carries every factor; pass it so the advisor can decompose it.
    if ctx.get("confidence_method"):
        lines.append(f"Confidence method: {ctx.get('confidence_method')}")

    recommendation = ctx.get("recommendation")
    recommendations = ctx.get("recommendations") or []
    if recommendation or recommendations:
        lines.append(f"Recommendation: {recommendation or '; '.join(recommendations)}")

    # Module 3 roadmap — phases, timelines, responsible agency.
    roadmap = ctx.get("roadmap") or {}
    phases = roadmap.get("phases") or []
    if phases:
        lines.append("Implementation roadmap:")
        for ph in phases[:2]:
            name = ph.get("phase") or "Phase"
            timeline = ph.get("timeline") or ""
            objective = ph.get("objective") or ""
            lines.append(f"  • {name}{f' ({timeline})' if timeline else ''}: {objective}")
        agency = roadmap.get("responsible_agency")
        if agency:
            lines.append(f"  Responsible agency: {agency}")

    # Module 4 case intelligence — incident match evidence.
    case_info = ctx.get("case_intelligence") or {}
    if case_info.get("matched") and case_info.get("incident_matches"):
        lines.append("Case intelligence (matched incidents):")
        for inc in case_info["incident_matches"][:2]:
            lines.append(
                f"  • {inc.get('incident_name', 'Incident')}: "
                f"{str(inc.get('potential_consequence', ''))[:200]}"
            )

    # Evidence used for this finding.
    evidence = ctx.get("evidence", [])
    lines.append("")
    lines.append("Evidence used for this finding:")
    if not evidence:
        lines.append("  (no retrieved evidence items)")
    for e in evidence:
        fw = e.get("source_framework", "Uploaded Document")
        page = f" (p. {e.get('page_number')})" if e.get("page_number") else ""
        score = (
            f" [similarity: {e.get('similarity_score', 'N/A')}]"
            if e.get("similarity_score") is not None
            else ""
        )
        lines.append(f"  • [{fw}{page}]{score}")
        lines.append(f"    {e.get('text', '')[:300]}")
    return "\n".join(lines)


def build_system_prompt() -> str:
    return (
        "You are the AI Rapporteur, an expert policy analysis assistant. "
        "Your role is to help users understand AI governance concepts, interpret "
        "policy analysis results, explore governance frameworks, and learn how "
        "governance recommendations can be implemented in practice.\n\n"
        "Guidelines:\n"
        "1. Answer conversationally and clearly — explain concepts in simple language "
        "while preserving technical accuracy.\n"
        "2. Synthesize information from multiple frameworks (UNESCO, OECD, UN, UNDP) "
        "rather than quoting a single source.\n"
        "3. When discussing the uploaded policy, prioritize the retrieved evidence "
        "and explain the reasoning behind conclusions.\n"
        "4. Distinguish clearly between evidence retrieved from the uploaded policy "
        "and general governance knowledge.\n"
        "5. If sufficient evidence is unavailable, state that clearly instead of "
        "hallucinating.\n"
        "6. For every factual claim from the retrieved context, cite the source "
        "in EXACTLY this format, on its own line: "
        '[Framework Name]: "exact text"\n\n'
        "Format:\n"
        "- Lead with the answer. No preamble, no restating the question, no "
        "closing offer of further help.\n"
        "- Short paragraphs. Use a bullet list when you are genuinely "
        "enumerating things; never bullet a single item.\n"
        "- **Bold** only load-bearing terms: a named body, an instrument, a "
        "provision reference, a verdict. Two or three per answer at most — "
        "bolding everything is the same as bolding nothing.\n"
        "- No headings unless the answer really has two or more distinct "
        "sections. Never use a heading in a short reply.\n"
        "- Plain sentences, no tables, no ASCII art.\n\n"
        "Say what is true, including when it is inconvenient: if the evidence "
        "is thin, say so in a sentence rather than padding the answer to look "
        "complete.\n\n"
        "CORRECT FALSE PREMISES BEFORE ANSWERING. A question often asserts a "
        'verdict — "why is Safety partial", "why did Privacy fail". If the '
        "stored analysis says otherwise, say so in the first sentence and then "
        "answer the corrected question. Never argue for a verdict the analysis "
        "did not reach because the question assumed it; a reader who leaves "
        "believing a dimension is Partial when it was scored Covered has been "
        "misled, and agreeing with them is the easiest way to do it."
    )


def build_llm_enrichment_prompt(
    user_message: str,
    retrieval_context: str,
    advisor_reply: str,
    intent: str,
    dimension: str | None,
    drill_down_context: str | None = None,
    history: list[dict[str, str]] | None = None,
    method_context: str | None = None,
    analysis_context: str | None = None,
) -> str:
    parts = []
    # Method and analysis context go FIRST, ahead of the advisor's template
    # reply. Both are authoritative — one is the instrument describing itself,
    # the other is what the pipeline already computed — whereas the base
    # response is a generic scaffold. Leading with the scaffold invited the
    # model to elaborate it and then contradict the figures further down.
    if method_context:
        parts.append(method_context)
        parts.append("")
    if analysis_context:
        parts.append(analysis_context)
        parts.append("")

    parts.append("--- Advisor Base Response ---")
    parts.append(advisor_reply)
    parts.append("")
    parts.append(f"--- Classified Intent: {intent} ---")
    if dimension:
        parts.append(f"--- Dimension: {dimension} ---")
    parts.append("")

    # Include conversation history for context
    if history:
        parts.append("--- Previous Conversation ---")
        for msg in history[-4:]:
            role = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"  {role}: {msg['content'][:500]}")
        parts.append("")

    if drill_down_context:
        parts.append("--- Finding Context ---")
        parts.append(drill_down_context)
        parts.append("")

    parts.append("--- Retrieved Context ---")
    if retrieval_context.strip():
        parts.append(retrieval_context)
    else:
        parts.append("No additional retrieved context.")
    parts.append("")

    parts.append("--- User Question ---")
    parts.append(user_message)
    parts.append("")

    if method_context or analysis_context or drill_down_context:
        # The base response is a generic template the advisor layer produces
        # before any of this context exists. Told to "refine" it, the model
        # padded it out and left the real figures unused, so on these two
        # paths it is explicitly demoted to tone reference only.
        source = []
        if method_context:
            source.append("the description of how Meridian works")
        if analysis_context:
            source.append("the computed verdicts of the open analysis")
        if drill_down_context:
            source.append("the finding's own reasoning trail and evidence")
        parts.append(
            f"Answer from {' and '.join(source)} above. Those sections are "
            "authoritative — prefer them over the advisor base response, which "
            "is a generic template and may be a non-answer. Never say the "
            "context lacks an evaluation or scorecard when a section above "
            "supplies one.\n\n"
            "CHECK THE QUESTION'S PREMISE FIRST. If it asserts a coverage level, "
            "stage or risk that the sections above contradict, correct it in the "
            "opening sentence and answer the corrected question. Do not "
            "reconstruct a case for a verdict the analysis did not reach.\n\n"
            "State figures exactly as given; do not round, recompute, or invent "
            "one that is absent. Where the question asks WHY, give the reasoning "
            "the sections above actually record rather than a plausible-sounding "
            "rationale of your own."
        )
    else:
        parts.append(
            "Using the advisor base response and the retrieved context above, "
            "refine and enrich your answer. Add specific evidence citations where "
            "available. Maintain the same conversational, expert tone. "
            "If the retrieved context doesn't add value, keep the base response."
        )

    parts.append("")
    parts.append(
        "Be CONCISE: answer in under ~140 words unless the user explicitly asks "
        "for detail, and include only the most relevant citations. A short, "
        "precise answer beats a long one.\n\n"
        "Keep the formatting rules from the system prompt: answer first, short "
        "paragraphs, bullets only for real lists, **bold** on two or three "
        "load-bearing terms at most. Do not restate the question, and do not "
        "end with an offer of further help."
    )
    return "\n".join(parts)


_PROSE_SOURCE_PREFIXES = (
    "as noted in guidance from the",
    "as highlighted in the",
    "as stated in the",
    "as described in the",
    "as noted in the",
    "as defined in the",
    "as set out in the",
    "as outlined in the",
    "guidance from the",
    "as noted in",
    "as highlighted in",
    "as stated in",
    "as described in",
    "as defined in",
    "as set out in",
    "as outlined in",
    "highlighted in the",
    "stated in the",
    "noted in the",
    "described in the",
    "defined in the",
    "according to the",
    "per the",
    "under the",
    "in the",
    "the",
)


def _clean_prose_source(raw: str) -> str:
    """Trim filler from a prose-extracted source name.

    Models write 'As highlighted in the Model AI Governance Framework: "..."'
    and the regex captures the phrase before the colon. This strips leading
    connective words so the result is a usable framework name for the
    framework-filtered verification lookup.
    """
    name = (raw or "").strip()
    lowered = name.lower()
    for prefix in sorted(_PROSE_SOURCE_PREFIXES, key=len, reverse=True):
        if lowered.startswith(prefix):
            name = name[len(prefix) :].strip()
            lowered = name.lower()
    # Also drop any remaining leading lowercase words (e.g. 'the u.s. national
    # institute ...' variants the prefix list doesn't cover).
    while name and (name[0].islower() or name[0].isdigit()):
        idx = name.find(" ")
        if idx == -1:
            return ""
        name = name[idx + 1 :].strip()
    return name


_known_source_cache: tuple[float, list[str]] | None = None


def _known_framework_names(vector_store) -> list[str]:
    """Names of frameworks + uploaded workspace documents actually present in
    the vector store, so prose citations can be gated to real sources before
    verification. Both are legitimate citation targets: Mode A/C cite the
    framework knowledge base, Mode C can also cite the workspace document.

    Keyed on the collection size rather than a 5-minute clock. The old TTL
    meant that every five minutes some unlucky message paid for TWO full
    paged scans of the store — 37k chunks, ~1000 rows a page, once for
    framework names and again for document names — inside the request. The set
    only changes when something is ingested or purged, and both move the total,
    so the size is both a correct and a much cheaper invalidation signal.

    The two scans are also now one pass: they read the same metadata."""
    global _known_source_cache
    try:
        size = vector_store.collection.count()
    except Exception:
        return []
    if _known_source_cache and _known_source_cache[0] == size:
        return _known_source_cache[1]
    try:
        frameworks: set[str] = set()
        documents: set[str] = set()
        offset = 0
        while True:
            rows = vector_store.collection.get(include=["metadatas"], limit=5000, offset=offset)
            metadatas = rows.get("metadatas") or []
            if not metadatas:
                break
            for m in metadatas:
                fw = (m or {}).get("framework") or ""
                if fw:
                    frameworks.add(fw)
                dn = (m or {}).get("document_name") or ""
                if dn:
                    documents.add(dn)
            offset += len(metadatas)
        names = sorted(frameworks) + sorted(documents)
        _known_source_cache = (size, names)
        logger.info("known_source_names_cached", collection_size=size, names=len(names))
        return names
    except Exception:
        return []


_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _source_matches_known_framework(source: str, known: list[str]) -> str | None:
    """Resolve a claimed source to a known framework/document name, or None.

    Fuzzy substring match on both directions, with punctuation/dashes
    stripped so the model's "Model AI Governance Framework for Agentic AI"
    matches the stored "Model-AI-Governance-Framework-for-Agentic-AI.pdf".
    When the claimed string merely CONTAINS a stored name (a mid-sentence
    mention like "For instance, the UNESCO Recommendation on the Ethics of
    AI"), the canonical stored name is returned so the citation carries a
    clean source label and a correct framework filter for verification.

    Returns None for garbage (e.g. "Accountability requires evaluating the
    governance structure") and for too-short generic claims ("Risk", "Data")
    that could substring-match real names by accident.
    """
    claimed = _NON_ALNUM.sub("", (source or "").lower().strip())
    if not claimed or len(claimed) < 8:
        return None
    for name in known:
        stored = _NON_ALNUM.sub("", (name or "").lower().strip())
        if not stored or len(stored) < 4:
            continue
        if claimed in stored:
            return name
        if stored in claimed:
            return name
    return None


def extract_citations(text: str) -> list[dict[str, str]]:
    citations = []
    lines = text.split("\n")
    for line in lines:
        if "[" in line and "]" in line and ":" in line:
            idx = line.find("[")
            if idx >= 0:
                end = line.find("]", idx)
                if end > idx:
                    source = line[idx + 1 : end]
                    rest = line[end + 1 :].strip()
                    if rest.startswith(":") or rest.startswith(","):
                        rest = rest[1:].strip()
                    quote = rest.strip('"').strip("'").strip()
                    if quote and len(quote) > 10:
                        citations.append({"source": source, "quote": quote[:300]})
        # Prose fallback: models sometimes write 'Source Name: "exact quote"'
        # without brackets. Over-matching here is safe — every quote still
        # passes through verify_chat_citation, which rejects anything that
        # isn't genuinely in the knowledge base.
        elif ":" in line and '"' in line:
            m = re.search(
                r'(?:the\s+|of\s+the\s+|in\s+the\s+)?([A-Z][A-Za-z0-9 &.,()\'-]{3,}?)\s*:\s*\*?\*?"?([^"\n]{15,}?)"?\*?\*?$',
                line,
            )
            if m:
                source = _clean_prose_source(m.group(1))
                quote = m.group(2).strip().rstrip('"').strip()
                if source and len(quote) > 15:
                    citations.append({"source": source, "quote": quote[:300]})
    return citations


def verify_document_overview_citations(
    reply: str,
    chunks: list[dict[str, Any]],
    vector_store: VectorStore,
) -> tuple[list[dict[str, str]], int, int]:
    """Verify every [DOC-n] citation in a Mode B reply against its real chunk.

    The model cites [DOC-1]..[DOC-n] matching the numbered overview context;
    map each label back to the real chunk id and run the same
    chunk-exists + quote-supports-claim verification used by Module 1-4
    (verify.verify_citation). Citations whose chunk cannot be resolved or
    whose quote fails verification are dropped from the visible list (they are
    unverified, never shown as if real).

    Returns (verified_citations, pass_count, fail_count).
    """
    label_to_chunk: dict[str, dict[str, Any]] = {}
    for i, c in enumerate(chunks, 1):
        if c.get("chunk_id"):
            # Keys match match.group(0) verbatim, brackets included.
            label_to_chunk[f"[DOC-{i}]"] = c

    # Matches both single labels [DOC-2] and compound ones [DOC-1, DOC-4]
    # (each inner label verified against its own chunk).
    pattern = re.compile(r"\[DOC-\d+(?:\s*,\s*DOC-\d+)*\]")
    citations: list[dict[str, str]] = []
    cit_pass = 0
    cit_fail = 0

    # Extract each [DOC-n] with the surrounding sentence as the claimed quote.
    for match in pattern.finditer(reply):
        group = match.group(0)  # e.g. [DOC-2] or [DOC-1, DOC-4]
        labels = re.findall(r"\[DOC-\d+\]", group)
        for label in labels:
            chunk = label_to_chunk.get(label)
            if not chunk:
                cit_fail += 1
                continue
            # Claimed quote: the sentence containing the citation marker.
            start = reply.rfind(".", 0, match.start()) + 1
            end = reply.find(".", match.end())
            if end == -1:
                end = len(reply)
            claim = reply[start:end].strip().strip("[]").strip()
            if not claim or len(claim) < 8:
                cit_fail += 1
                continue

            try:
                page_raw = chunk.get("page_number")
                try:
                    page = int(page_raw) if page_raw not in (None, "") else None
                except (TypeError, ValueError):
                    page = None
                result = verify_citation(
                    chunk_id=chunk["chunk_id"],
                    claim_text=claim[:300],
                    page_number=page,
                    source_framework=(chunk.get("document_name") or "Uploaded Document"),
                    vector_store=vector_store,
                )
            except Exception as exc:
                logger.warning("overview_citation_verify_failed", label=label, error=str(exc))
                cit_fail += 1
                continue

            if result.passed:
                cit_pass += 1
                citations.append(
                    {
                        "source": chunk.get("document_name") or "Uploaded Document",
                        "quote": claim[:300],
                        "verified": True,
                        "verification_method": result.verification_method,
                        "verification_confidence": getattr(result, "verification_confidence", 0.0),
                    }
                )
            else:
                cit_fail += 1
    return citations, cit_pass, cit_fail


# In-process conversational state (active dimension, last intent, recent
# turns). The DURABLE record of a conversation is the chat_sessions /
# chat_messages tables; this only carries the working state that resolves
# follow-up questions, and is expected to be lost on restart.
#
# Bounded because it never was: entries were created per session id and never
# removed, so a long-lived process accumulated one SessionContext for every
# conversation it had ever seen, each holding up to six messages plus a
# finding context. That is a slow leak in a server designed to stay up.
_SESSION_CONTEXT_LIMIT = int(os.getenv("CHAT_SESSION_CONTEXT_LIMIT", "500"))
_session_contexts: OrderedDict[str, SessionContext] = OrderedDict()


def _get_session(session_id: str) -> SessionContext:
    """Working state for a session, evicting least-recently-used entries.

    Eviction only discards in-memory follow-up context; the conversation
    itself is persisted, so an evicted session resumes with a fresh context
    rather than losing history.
    """
    existing = _session_contexts.get(session_id)
    if existing is not None:
        _session_contexts.move_to_end(session_id)
        return existing
    ctx = SessionContext()
    _session_contexts[session_id] = ctx
    while len(_session_contexts) > _SESSION_CONTEXT_LIMIT:
        evicted, _ = _session_contexts.popitem(last=False)
        logger.info("chat_session_context_evicted", session_id=evicted)
    return ctx


def chat(
    workspace_id: str,
    user_message: str,
    vector_store: VectorStore,
    guardrails: Guardrails,
    finding_context: dict[str, Any] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    frameworks: list[str] | None = None,
    analysis_results: dict[str, Any] | None = None,
    session_id: str | None = None,
    mode: str = "advisor",
) -> dict[str, Any]:
    """Three-mode chat:

    - Mode A ("advisor" without finding context): general educational,
      unscoped across the full corpus (no workspace filter).
    - Mode B ("document_overview", or advisor + workspace + document-specific
      question): whole-document overview, workspace-scoped, broad
      section-stratified retrieval, per-claim [DOC-n] grounding.
    - Mode C ("advisor" + finding context): per-finding drill-down using the
      already-computed deterministic reasoning trail.
    - "framework_qa": knowledge-base-only Framework Q&A bot (unchanged).
    """
    start_time = time.time()
    mode = mode if mode in CHAT_MODES else "advisor"
    is_qa = mode == "framework_qa"
    is_overview = mode == "document_overview"
    is_auditor = mode == "auditor"
    has_finding = bool(finding_context)
    # Auto-route: advisor/auditor mode + a workspace + a document-specific
    # question goes to Mode B rather than the unscoped corpus. This is what
    # makes the AI Auditor ONE merged bot: the question itself decides whether
    # it reads the uploaded document (Mode B) or answers from the governance
    # knowledge base (advisor layer) — the user never picks a bot.
    # A question about Meridian's own method is never a document question,
    # even when it is phrased with "this" — "how does this tool decide
    # Partial?" was matching the document markers and being answered from the
    # uploaded PDF, which of course says nothing about Meridian.
    asks_about_method = is_method_question(user_message)
    # Comparison against a framework, improvement advice, implementation
    # planning: real questions, but the honest answer is a scored run, not a
    # chat turn. The Auditor hands them to the analysis pipeline rather than
    # improvising verdicts outside it. The Rapporteur does NOT — it already
    # has a completed analysis and answers them from those verdicts.
    wants_full_analysis = (
        needs_full_analysis(user_message) and not asks_about_method and not analysis_results
    )
    # "What are the main gaps in this analysis?" reads as document-specific by
    # the marker list ("what are the main", "in the") and was being answered
    # from the PDF's own passages, which of course do not discuss the analysis.
    # When a completed run is in hand, a question about the RUN beats a
    # question about the document.
    asks_about_analysis = bool(analysis_results) and is_analysis_overview_question(user_message)
    routed_overview = (
        not is_qa
        and not is_overview
        and not has_finding
        and not asks_about_method
        and not asks_about_analysis
        and bool(workspace_id)
        and is_document_specific_question(user_message)
    )
    effective_mode = (
        "document_overview"
        if (is_overview or routed_overview)
        else "framework_qa"
        if is_qa
        else "auditor"
        if is_auditor
        else "advisor"
    )
    mode = effective_mode
    is_overview = mode == "document_overview"

    result: dict[str, Any] = {
        "reply": "",
        "citations": [],
        "blocked": False,
        "reason": None,
        "retrieval_count": 0,
        "citation_pass_count": 0,
        "citation_fail_count": 0,
        "llm_latency": 0.0,
        "total_processing_time": 0.0,
        "intent": "unknown",
        "mode": mode,
    }

    # ── 1. Guardrails ────────────────────────────────────────────────────
    # Mode A and framework_qa query the whole knowledge base — no workspace
    # filter. Modes B/C are workspace-scoped.
    guardrail_ws = None
    if is_overview or (mode in ("advisor", "auditor") and (has_finding or workspace_id)):
        guardrail_ws = [workspace_id] if workspace_id else None
    guardrail_result = guardrails.check_query(
        user_message,
        workspace_filter=guardrail_ws,
        strict=False,
    )
    if not guardrail_result.passed:
        # The Framework Q&A and AI Auditor bots answer greetings directly
        # rather than blocking.
        if (is_qa or is_auditor) and guardrail_result.reason == "greeting_detected":
            result["reply"] = build_framework_qa_greeting() if is_qa else build_auditor_greeting()
            result["blocked"] = False
            result["intent"] = "greeting"
            result["total_processing_time"] = time.time() - start_time
            return result
        result["reply"] = guardrail_result.scope_message or SCOPE_MESSAGE
        result["blocked"] = True
        result["reason"] = guardrail_result.reason
        result["total_processing_time"] = time.time() - start_time
        return result

    # ── 1b. Questions that belong to the analysis pipeline ───────────────
    # Returned before retrieval and before the LLM: nothing retrieved could
    # change the answer, and the reply is the same either way.
    if wants_full_analysis and not is_qa:
        result["reply"] = build_full_analysis_referral(has_document=bool(workspace_id))
        result["intent"] = "refer_to_analysis"
        result["provider"] = "template"
        result["total_processing_time"] = time.time() - start_time
        logger.info(
            "chat_referred_to_analysis",
            workspace_id=workspace_id,
            mode=mode,
            seconds=round(result["total_processing_time"], 2),
        )
        return result

    # ── 2. Retrieve Context (per-mode) ──────────────────────────────────
    merged: list[dict[str, Any]] = []
    retrieval_context = ""
    overview_chunks: list[dict[str, Any]] = []

    if is_overview:
        # ── Mode B: whole-document, section-stratified + topic sweep ──
        if workspace_id:
            overview_chunks = retrieve_document_overview(
                vector_store=vector_store,
                workspace_id=workspace_id,
                query=user_message,
                top_k=10,
            )
            retrieval_context = build_overview_context(overview_chunks)
            merged = overview_chunks
        # If no workspace, fall through to Mode A style unscoped retrieval.

    if is_qa:
        # Framework Q&A: full knowledge base — no workspace filter.
        merged = vector_store.retrieve(query=user_message, top_k=8)
        retrieval_context = build_context_from_retrieval(merged, top_k=8)

    if mode in ("advisor", "auditor") and not is_overview:
        # ── Mode A (unscoped) / Mode C (finding-scoped) / auditor general ─
        retrieved_fw: list[dict[str, Any]] = []
        retrieved_doc: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        if has_finding:
            # Mode C: retrieval scope is the finding's own evidence. Only a
            # narrow supplementary sweep is run (workspace-scoped) so new
            # context can be added for genuinely uncovered questions — the
            # finding's evidence + reasoning is the primary context passed
            # as drill_down_context to the LLM.
            if frameworks:
                retrieved_fw = vector_store.retrieve(
                    query=user_message,
                    top_k=4,
                    framework_filter=frameworks,
                )
            if workspace_id:
                retrieved_doc = vector_store.retrieve(
                    query=user_message,
                    top_k=4,
                    workspace_filter=[workspace_id],
                )
        else:
            # Mode A: unscoped across the full corpus. Frameworks list is
            # empty (picker removed) so no framework_filter — retrieve
            # broadly, plus any uploaded documents via workspace filter only
            # if a workspace happens to be loaded.
            retrieved_fw = vector_store.retrieve(query=user_message, top_k=8)
            if workspace_id:
                retrieved_doc = vector_store.retrieve(
                    query=user_message,
                    top_k=4,
                    workspace_filter=[workspace_id],
                )
        for r in retrieved_fw + retrieved_doc:
            cid = r.get("chunk_id")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                merged.append(r)
        merged.sort(key=lambda r: -(r.get("similarity_score") or 0))
        merged = merged[:10]
        retrieval_context = build_context_from_retrieval(merged, top_k=8)

    # ── 3. Response generation ─────────────────────────────────────────
    session_key = f"{workspace_id}:{mode}:{session_id or 'default'}"
    session = _get_session(session_key)
    if finding_context and not is_qa:
        session.set_finding_context(finding_context)

    llm_latency = 0.0
    provider_label = "template"
    intent = "unknown"
    dimension = None
    final_reply = ""
    verified_citations: list[dict[str, str]] = []
    cit_pass = 0
    cit_fail = 0

    if is_overview:
        # ── Mode B: direct grounded LLM answer (no template layer — the
        #    template generators are dimension/finding-oriented and would
        #    fight the overview structure). Graceful degradation to an
        #    honest non-answer when the LLM is unavailable.
        intent = "document_overview"
        provider = get_provider()
        overview_prompt = build_overview_prompt(
            query=user_message,
            context=retrieval_context,
            history=conversation_history,
        )
        try:
            llm_start = time.time()
            enrichment = generate_text_with_retry(
                provider=provider,
                prompt=overview_prompt,
                system_prompt=build_overview_system_prompt(),
                operation=f"mode_b_overview_{session_id or 'default'}",
            )
            llm_latency = time.time() - llm_start
            final_reply = enrichment
            provider_label = "llm"
            # Per-claim [DOC-n] verification against real chunks.
            verified_citations, cit_pass, cit_fail = verify_document_overview_citations(
                reply=final_reply,
                chunks=overview_chunks,
                vector_store=vector_store,
            )
        except Exception as exc:
            logger.info(
                "chat_mode_b_llm_failed",
                error=str(exc)[:200],
                workspace_id=workspace_id,
            )
            if overview_chunks:
                final_reply = (
                    "I couldn't generate a full answer just now, but here is "
                    "the document material most relevant to your question:\n\n"
                    + build_overview_context(overview_chunks)
                )
            else:
                final_reply = (
                    "I don't see that addressed in the retrieved sections of "
                    "the uploaded document — you may want to check the "
                    "relevant pages directly."
                )

    else:
        # ── Modes A / C / framework_qa via the advisor layer ──────────
        advisor_result = generate_response(
            message=user_message,
            session=session,
            finding_context=None if is_qa else finding_context,
            analysis_results=None if is_qa else analysis_results,
        )
        advisor_reply = advisor_result["reply"]
        intent = advisor_result["intent"]
        dimension = advisor_result["dimension"]

        if is_qa:
            # Analysis/recommendation intents don't apply to a knowledge-base
            # bot — reclassify as concept/educational about the dimension so
            # the user still gets a useful grounded answer.
            if intent in ("analysis_explanation", "recommendation_explanation"):
                if dimension:
                    intent = "concept_explanation"
                    advisor_reply = build_concept_response(dimension)
                else:
                    intent = "educational"
                    advisor_reply = build_educational_response(user_message, None)
                session.last_intent = Intent(intent)

        # ── LLM Enrichment (quota-routed; graceful degradation) ──────
        enrichment = None
        # A method question that classified as unknown must still reach the
        # LLM — the whole point is that the advisor templates have no answer
        # for it and the method context does.
        if intent not in ("greeting", "unknown") or (asks_about_method and not is_qa):
            try:
                provider = get_provider()

                drill_down_context = None
                if not is_qa:
                    ctx = finding_context or session.finding_context
                    if not ctx and dimension and analysis_results:
                        # Typing "why is Fairness Partial" deserves the same
                        # reasoning trail as clicking "Ask about this finding".
                        # Only the button path built one, so a typed question —
                        # the far more common one, and the one that asks "what
                        # proof do you have" — reached the model with the
                        # verdict but none of the evidence behind it.
                        gap = (analysis_results.get("gaps") or {}).get(dimension)
                        if isinstance(gap, dict):
                            ctx = _gap_to_finding_context(gap)
                    if ctx:
                        # Mode C: the FULL deterministic reasoning trail.
                        drill_down_context = build_drill_down_context(ctx)

                # Self-knowledge: the corpus holds no document describing
                # Meridian, so a question about the instrument had nothing to
                # retrieve and came back as a refusal. Not applicable to the
                # Framework Librarian, which is scoped to the knowledge base.
                method_context = (
                    build_self_knowledge_context(user_message, vector_store)
                    if asks_about_method and not is_qa
                    else None
                )
                # Cross-dimension questions need the whole run in view. The
                # per-dimension generators already handle a single verdict, so
                # this is attached only when the question actually spans them.
                analysis_context = (
                    build_analysis_overview_context(analysis_results)
                    if not is_qa and asks_about_analysis
                    else None
                )

                llm_prompt = build_llm_enrichment_prompt(
                    user_message=user_message,
                    retrieval_context=retrieval_context,
                    advisor_reply=advisor_reply,
                    intent=intent,
                    dimension=dimension,
                    drill_down_context=drill_down_context,
                    history=conversation_history,
                    method_context=method_context,
                    analysis_context=analysis_context,
                )
                # Both can be attached — "which dimension is strongest" is a
                # question about the run that happens to name the method's
                # vocabulary. The run is the more specific of the two, so it
                # names the intent.
                if analysis_context:
                    intent = "analysis_overview"
                elif method_context:
                    intent = "method_explanation"

                llm_start = time.time()
                # Quota discipline: chat calls go through the same RPD/RPM
                # throttle + key rotation + Groq fallback as analysis calls.
                enrichment = generate_text_with_retry(
                    provider=provider,
                    prompt=llm_prompt,
                    system_prompt=build_framework_qa_system_prompt()
                    if is_qa
                    else build_system_prompt(),
                    operation=f"chat_{mode}_{intent}_{session_id or 'default'}",
                )
                llm_latency = time.time() - llm_start
            except Exception as exc:
                logger.info(
                    "chat_llm_enrichment_failed",
                    error=str(exc)[:200],
                    intent=intent,
                    dimension=dimension,
                    mode=mode,
                )
                enrichment = None

        final_reply = enrichment if enrichment else advisor_reply
        provider_label = "llm" if enrichment else "template"

        # ── Citation Extraction & Verification (Modes A/C/framework_qa) ─
        if enrichment:
            known_frameworks = _known_framework_names(vector_store)
            raw_citations = extract_citations(final_reply)
            for cit in raw_citations:
                # Gate: only verify citations whose claimed source resolves to a
                # framework actually in the knowledge base. Prose extraction can
                # over-capture mid-sentence fragments; verify_chat_citation
                # would then broaden to the whole store and could let a garbage
                # fragment pass semantic verification. If the source name is
                # nonsense, the citation is dropped outright (never shown).
                source_known = _source_matches_known_framework(cit["source"], known_frameworks)
                if not source_known:
                    cit_fail += 1
                    continue
                v_result = verify_chat_citation(
                    source_framework=source_known,
                    quote_text=cit["quote"],
                    vector_store=vector_store,
                )
                verified = getattr(v_result, "passed", False)
                if verified:
                    cit_pass += 1
                    # Only verified citations are shown — the user-facing rule is
                    # never surface an unverified source.
                    verified_citations.append(
                        {
                            "source": source_known,
                            "quote": cit["quote"],
                            "verified": True,
                            "verification_method": getattr(v_result, "verification_method", ""),
                            "verification_confidence": getattr(
                                v_result, "verification_confidence", 0.0
                            ),
                        }
                    )
                else:
                    cit_fail += 1

    # ── Narrative citation numbers ───────────────────────────────────
    # The block above verifies QUOTED sources. It says nothing about the
    # article and recital NUMBERS the model writes into prose, and those are
    # the most common residual error: a live gap-analysis run produced four
    # such citations, one of which pointed at an article of an entirely
    # different regulation. The gap-analysis path has checked them since;
    # chat had no equivalent guard at all, so a reply could assert "Article 54
    # requires..." with nothing testing whether that article exists.
    #
    # Same helper, same OCR-tolerant matcher, same two severities — a check
    # that only runs on one surface is not a property of the system.
    narrative_citation_flags: dict[str, list[str]] = {"fabricated": [], "unsupported": []}
    try:
        retrieved_text = " ".join(
            (c.get("text") or "") for c in (merged or []) if isinstance(c, dict)
        )
        if retrieved_text and final_reply:
            # Lazy: the whole-document fetch only happens when the cheap regex
            # pass has actually flagged something. Most replies cite nothing
            # numbered, and pulling every chunk of a 1,700-chunk regulation on
            # every chat turn to confirm that would be absurd.
            from src.verify import find_unverifiable_citations

            if find_unverifiable_citations([final_reply], retrieved_text):
                document_text = ""
                if workspace_id:
                    try:
                        res = vector_store.collection.get(
                            where={"workspace_id": workspace_id},
                            include=["documents"],
                        )
                        document_text = " \n".join(res.get("documents", []) or [])
                    except Exception:
                        # No document to compare against means "unsupported",
                        # never "invented" — see classify_narrative_citations.
                        document_text = ""
                narrative_citation_flags = classify_narrative_citations(
                    [final_reply], retrieved_text, document_text
                )
            if narrative_citation_flags["fabricated"]:
                logger.error(
                    "chat_narrative_citations_fabricated",
                    workspace_id=workspace_id,
                    citations=narrative_citation_flags["fabricated"],
                )
            elif narrative_citation_flags["unsupported"]:
                logger.warning(
                    "chat_narrative_citations_unsupported",
                    workspace_id=workspace_id,
                    citations=narrative_citation_flags["unsupported"],
                )
    except Exception as exc:
        logger.warning("chat_narrative_citation_check_failed", error=str(exc))

    result["reply"] = final_reply
    result["citations"] = verified_citations
    result["fabricated_citations"] = narrative_citation_flags["fabricated"]
    result["unverifiable_citations"] = narrative_citation_flags["unsupported"]
    result["retrieval_count"] = len(merged)
    result["citation_pass_count"] = cit_pass
    result["citation_fail_count"] = cit_fail
    result["llm_latency"] = llm_latency
    result["intent"] = intent
    result["dimension"] = dimension
    result["provider"] = provider_label
    result["total_processing_time"] = time.time() - start_time

    logger.info(
        "chat_completed",
        workspace_id=workspace_id,
        intent=intent,
        dimension=dimension,
        provider=provider_label,
        mode=mode,
        routed_mode=effective_mode,
        retrieval_count=len(merged),
        llm_latency_seconds=round(llm_latency, 2),
        total_seconds=round(result["total_processing_time"], 2),
        blocked=result["blocked"],
    )

    return result
