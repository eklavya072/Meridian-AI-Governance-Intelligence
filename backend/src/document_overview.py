"""Mode B — Document Overview (workspace-scoped, broad retrieval).

Answers whole-document questions ("what does this policy focus on",
"summarize this document's approach to X") that neither the unscoped general
panel (Mode A) nor the per-finding drill-down (Mode C) can answer well.

Why a different retrieval path from the dimension pipeline:
  - retrieve_module_chunks is deliberately narrow — aspect-based queries per
    governance dimension, capped at ~4 document chunks. That is the right tool
    for scoring a dimension; it is the wrong tool for "span the whole
    document".
  - Mode B instead (1) samples the document's actual STRUCTURE via
    section-stratified retrieval (one or two chunks per section boundary from
    structure-aware splitting, so the answer reflects how the document is
    really organized) and (2) fuses a broad multi-query topic sweep (sector
    applications, target populations, implementation approach, funding,
    principles) via RRF. Budget is generous but capped (~10 chunks).

Anti-fabrication (the core rule of this mode):
  - Every specific fact, number, program name, or named initiative must trace
    to a real retrieved chunk. The prompt instructs the model to cite
    [DOC-n] labels; the reply's citations are then mapped label -> real chunk
    id and verified via the same chunk-existence + quote-support path used by
    Module 1-4 (verify.verify_citation). Unverifiable claims are dropped.
  - If a plausible claim cannot be grounded, the model must say so
    ("the retrieved sections don't specify this") rather than fill the gap
    from general knowledge about what such policies "probably" contain.
"""

from __future__ import annotations

import re
import structlog
from typing import Any

from src.vectorstore import VectorStore

logger = structlog.get_logger()

# Broad topic categories for the overview sweep — deliberately NOT the 8
# governance dimensions. These are the structural themes a whole-document
# question cares about (how the document is organized, what it covers, who it
# targets), independent of any single dimension's mechanism vocabulary.
OVERVIEW_TOPIC_QUERIES: list[str] = [
    "policy objectives, priorities, and overarching vision",
    "sector applications and use cases of AI",
    "target populations and beneficiaries",
    "implementation approach and institutional arrangements",
    "funding, investment, and resource allocation",
    "principles, values, and ethical commitments",
    "research, innovation, and capacity building",
    "international cooperation and partnerships",
]

# Budget: broad but capped — larger than Mode C's per-finding context, smaller
# than a full dimension run. A "summarize this document" first question gets
# the full budget; a narrow follow-up is capped tighter by the caller.
OVERVIEW_TOP_K = int(__import__("os").getenv("OVERVIEW_TOP_K", "10"))
# Section sample: how many chunks to take per detected section before the
# similarity fusion. Sections from structure-aware splitting are usually
# multi-chunk; 2 per section balances coverage vs budget.
SECTION_SAMPLE_PER_SECTION = int(__import__("os").getenv("OVERVIEW_SECTION_SAMPLE", "2"))
# Headroom for the similarity sweep before dedup (overlapping recursive-split
# chunks need slack so dedup can still fill the budget with distinct content).
SWEEP_HEADROOM = int(__import__("os").getenv("OVERVIEW_SWEEP_HEADROOM", "3"))


def _is_preamble(text: str, page: int | None) -> bool:
    """Same front-matter filter as the Module retrieval: drop cover pages,
    TOC, copyright, and blank-page boilerplate so the overview isn't diluted
    by front matter. Conservative — a national strategy's substance often
    starts on page 2.

    ChromaDB returns numeric metadata as strings, so the page number is
    coerced defensively before comparison."""
    text_lower = (text or "").lower().strip()
    if len(text_lower) < 150:
        return True
    if page is not None:
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = None
    if (page or 0) <= 1 and len(text_lower) < 400:
        return True
    markers = (
        "intentionally left blank", "acknowledgment", "acknowledgement",
        "table of contents", "contents", "copyright", "all rights reserved",
    )
    if len(text_lower) < 400 and any(m in text_lower for m in markers):
        return True
    return False


def retrieve_document_overview(
    vector_store: VectorStore,
    workspace_id: str,
    query: str,
    top_k: int = OVERVIEW_TOP_K,
    include_section_sample: bool = True,
) -> list[dict[str, Any]]:
    """Broad, workspace-scoped retrieval across the WHOLE uploaded document.

    Two passes fused together:
      1. Section-stratified sample — pull the document's chunks, group by the
         section metadata written by structure-aware splitting, and take a
         bounded number per section. This guarantees the answer can genuinely
         span the document's actual structure, not just whatever ranks highest
         for one phrasing of the question.
      2. Topic sweep — multi-query RRF across broad OVERVIEW_TOPIC_QUERIES
         plus the user's own query, so question-specific relevance still
         shapes the final selection.

    Returns chunks with label-friendly fields (chunk_id, text, page_number,
    section_title, document_name, similarity_score) truncated to a chat-safe
    length, deduplicated, preamble-filtered, capped at top_k.
    """
    if not workspace_id:
        return []

    # ── Pass 1: section-stratified sample ─────────────────────────────
    section_picks: list[dict[str, Any]] = []
    if include_section_sample:
        try:
            data = vector_store.collection.get(
                where={"workspace_id": workspace_id},
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            logger.warning("overview_section_get_failed", error=str(exc))
            data = None
        if data and data.get("ids"):
            by_section: dict[str, list[dict[str, Any]]] = {}
            for cid, doc, md in zip(
                data["ids"], data.get("documents") or [], data.get("metadatas") or []
            ):
                md = md or {}
                text = doc or ""
                page_raw = md.get("page_number")
                try:
                    page = int(page_raw) if page_raw not in (None, "") else None
                except (TypeError, ValueError):
                    page = None
                if _is_preamble(text, page):
                    continue
                section = (md.get("section") or "").strip() or "(unsectioned)"
                by_section.setdefault(section, []).append({
                    "chunk_id": cid,
                    "text": text,
                    "page_number": page,
                    "section_title": section,
                    "document_name": (md.get("document_name") or ""),
                    "similarity_score": None,
                })
            for chunks in by_section.values():
                # One representative chunk per section when possible; two when
                # the section is long (recursive splitting produces many).
                section_picks.extend(chunks[:SECTION_SAMPLE_PER_SECTION])

    # ── Pass 2: broad topic sweep (RRF across topic queries + user q) ─
    sweep: list[dict[str, Any]] = []
    queries = list(OVERVIEW_TOPIC_QUERIES)
    if query and query.strip():
        queries.insert(0, query.strip())
    for q in queries:
        try:
            res = vector_store.retrieve(
                query=q,
                top_k=max(2, top_k // 2) * SWEEP_HEADROOM,
                workspace_filter=[workspace_id],
            )
        except Exception as exc:
            logger.warning("overview_sweep_query_failed", query=q[:60], error=str(exc))
            continue
        for r in res:
            md = r.get("metadata") or {}
            text = r.get("text", "")
            page_raw = md.get("page_number")
            try:
                page = int(page_raw) if page_raw not in (None, "") else None
            except (TypeError, ValueError):
                page = None
            if _is_preamble(text, page):
                continue
            sweep.append({
                "chunk_id": r.get("chunk_id") or r.get("id"),
                "text": text,
                "page_number": page,
                "section_title": (md.get("section") or r.get("section_title") or ""),
                "document_name": (md.get("document_name") or ""),
                "similarity_score": r.get("similarity_score") or r.get("similarity", 0.0),
            })

    # ── Fuse: interleave section picks (structural coverage) with the
    #    similarity-ranked sweep so the user's question still shapes selection.
    #    Taking section picks first would let a large document exhaust the
    #    budget before the sweep ever contributes; alternating keeps both
    #    signals in the final context.
    seen: set[str] = set()
    seen_texts: set[str] = set()
    merged: list[dict[str, Any]] = []
    section_iter = iter(section_picks)
    sweep_iter = iter(sweep)
    section_next = next(section_iter, None)
    sweep_next = next(sweep_iter, None)
    while len(merged) < top_k and (section_next is not None or sweep_next is not None):
        # Prefer the section pick on even turns (structural coverage), the
        # sweep on odd turns (question relevance). Fall back to whichever
        # iterator still has items when one is exhausted.
        if len(merged) % 2 == 0:
            candidate = section_next if section_next is not None else sweep_next
        else:
            candidate = sweep_next if sweep_next is not None else section_next
        # Advance whichever iterator was consumed.
        if candidate is section_next:
            section_next = next(section_iter, None)
        else:
            sweep_next = next(sweep_iter, None)
        cid = candidate.get("chunk_id")
        text_key = ((candidate.get("text") or "")[:220]).strip().lower()
        if not cid or cid in seen or text_key in seen_texts:
            continue
        seen.add(cid)
        seen_texts.add(text_key)
        # Truncate to a chat-safe length (prompt budget).
        merged.append({**candidate, "text": (candidate.get("text") or "")[:900]})

    # If the section sample alone filled the budget, drop lowest-similarity
    # sweep chunks? No — structural coverage is the point; keep as-is. Log.
    logger.info(
        "overview_retrieval_complete",
        workspace_id=workspace_id,
        query=query[:80],
        section_picks=len(section_picks),
        sweep_results=len(sweep),
        final_chunks=len(merged),
        sections=len({c.get("section_title") for c in merged}),
    )
    return merged


def build_overview_context(chunks: list[dict[str, Any]]) -> str:
    """Number the chunks DOC-1..DOC-n with source labels for the prompt."""
    lines = []
    for i, c in enumerate(chunks, 1):
        src = c.get("document_name") or "Uploaded Document"
        section = c.get("section_title") or ""
        page = c.get("page_number")
        label = f"[DOC-{i}] ({src}"
        if section:
            label += f", {section}"
        if page:
            label += f", p. {page}"
        label += ")"
        lines.append(label)
        lines.append(c.get("text", ""))
        lines.append("")
    return "\n".join(lines)


def build_overview_system_prompt() -> str:
    return (
        "You are the Document Analyst, an expert at reading one uploaded policy "
        "document and answering questions about what IT actually says. You work "
        "ONLY from the retrieved passages of that document — never from your "
        "general training knowledge of what such policies usually contain.\n\n"
        "HARD RULES:\n"
        "1. EVERY specific fact, number, statistic, program name, named "
        "initiative, target, or structural claim must trace to a retrieved "
        "passage. Cite it inline with the passage's label, e.g. [DOC-2].\n"
        "2. If a plausible-sounding detail is NOT in the retrieved passages, "
        "OMIT it. Never fill the gap with general knowledge about what the "
        "country's AI policy 'probably' includes.\n"
        "3. When the retrieved sections genuinely don't specify something the "
        "question asks about, say so plainly: 'The retrieved sections don't "
        "specify this — you may want to check the relevant pages directly.'\n"
        "4. Structure the answer well: group related retrieved content into "
        "labeled sections inferred from what is actually in the passages "
        "(not a fixed template), use bullet points for enumerable items, and "
        "close with an offer to drill into a specific area.\n"
        "5. Cite every factual claim — a bullet with no [DOC-n] is a red flag "
        "that it is ungrounded.\n"
        "Never invent passages, page numbers, or program names."
    )


def build_overview_prompt(
    query: str,
    context: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    parts = []
    if history:
        parts.append("--- Previous Conversation (for follow-ups only) ---")
        for msg in history[-4:]:
            role = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"  {role}: {msg['content'][:400]}")
        parts.append("")
    parts.append("--- Retrieved Passages from the Uploaded Document ---")
    parts.append(context if context.strip() else "(no passages retrieved)")
    parts.append("")
    parts.append("--- User Question ---")
    parts.append(query)
    parts.append("")
    parts.append(
        "Answer the question about the uploaded document. Cite [DOC-n] for "
        "every factual claim. If the retrieved passages don't cover the "
        "question, say so honestly. Organize your answer into sections with "
        "bullets where enumerable, and end with an offer to go deeper.\n\n"
        "Be CONCISE: keep the whole answer under ~120 words unless the user "
        "explicitly asks for detail. A short, precise answer beats a long one."
    )
    return "\n".join(parts)


# Document-specific intent markers: questions that clearly target the active
# workspace's uploaded document rather than the general knowledge base.
DOC_SPECIFIC_MARKERS = (
    "this document", "the document", "this policy", "the policy",
    "this strategy", "the strategy", "this report", "the report",
    # The uploaded file is a PDF and people say so — "does this pdf deal with
    # accountability" is as document-anchored as a question gets, and it was
    # falling through to the unscoped corpus for want of the word.
    "this pdf", "the pdf", "this file", "the file", "uploaded",
    "this guideline", "the guideline", "this act", "this bill", "this law",
    "this framework", "this paper",
    "summarize", "summarise", "overview", "main focus", "focus on",
    "what does the policy", "what does this", "what is in the",
    "does this", "does the document", "where in", "where does",
    "mentioned in", "mention", "say about", "cover", "covered in",
    "approach to", "key themes", "main themes", "priorities of",
    "what are the main", "about the document", "tell me about this",
)


# Questions the Auditor should decline and hand to the analysis pipeline.
#
# "How does this fare against the EU AI Act?", "what should it improve?",
# "what's the best implementation plan?" are all real questions with real
# answers — but the answer is a full dimension-by-dimension run, not a chat
# turn over a handful of retrieved passages. Answering them from chat would
# mean producing verdicts and recommendations outside the scored pipeline,
# ungrounded in the force ladder and unverifiable against it, which is exactly
# the second source of truth this codebase keeps eliminating.
_FULL_ANALYSIS_MARKERS = re.compile(
    r"\b("
    r"compare[ds]?|comparison|compares|contrast|benchmark|"
    r"how does (it|this|the \w+) (compare|fare|stack|measure|hold up)|"
    r"(fair|fares|stack(s)? up|measure(s)? up|hold(s)? up|line(s)? up)\s+(against|with|to)|"
    r"(against|versus|vs\.?|relative to|in line with|consistent with|aligned? with|"
    r"alignment with|fall(s)? short)\b|"
    r"international (standard|standards|practice|norms|benchmark)|"
    r"best practice|global (standard|standards|norms)|"
    r"what (should|could|would|needs? to) .{0,30}(improve|strengthen|change|add|fix|do better)|"
    r"how (should|could|can) .{0,24}(it|they|this|the \w+) (improve|strengthen|be improved)|"
    r"(gaps?|weakness(es)?|shortcoming)s?\b.{0,30}(against|compared|relative|are there|does it have)|"
    r"implementation plan|implementation roadmap|roadmap|how to implement|"
    r"(rate|score|grade|assess|evaluate) (this|it|the (document|policy|strategy))|"
    r"(is|are) (this|it|the|these)( \w+){0,2} "
    r"(good|strong|weak|adequate|sufficient|compliant|comprehensive|enough|robust)"
    r")",
    re.IGNORECASE,
)


def needs_full_analysis(message: str) -> bool:
    """Is this a question only a scored analysis run can honestly answer?

    Comparison against a framework, prescriptive improvement advice, and
    implementation planning all require the per-dimension verdicts, the
    normative-force grading and the mechanism breakdown that the analysis
    pipeline produces. Chat has none of those, so it points at the pipeline
    rather than improvising a shallow version of its output.
    """
    normalized = (message or "").strip().lower()
    return bool(normalized and _FULL_ANALYSIS_MARKERS.search(normalized))


def is_document_specific_question(message: str) -> bool:
    """Lightweight intent check: does the message target the active workspace's
    document (Mode B) rather than the unscoped corpus (Mode A)?

    Sufficient by design — not sophisticated. Document-anchored pronouns and
    summary/overview verbs are the strongest signals; a bare dimension-name
    question ("what is transparency") is NOT document-specific and stays in
    Mode A.
    """
    normalized = (message or "").strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in DOC_SPECIFIC_MARKERS)
