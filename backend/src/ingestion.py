from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel

from src.validation import (
    MAX_FRAMEWORK_FILE_SIZE_BYTES,
    validate_file_path,
)

logger = structlog.get_logger()


class Chunk(BaseModel):
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    page_number: int | None = None
    section_title: str | None = None
    framework_name: str | None = None
    workspace_id: str | None = None


def parse_pdf(file_path: Path) -> list[dict[str, Any]]:
    import io

    from pypdf import PdfReader

    from src.text_repair import repair_split_words

    parser_name = "pypdf.PdfReader"
    file_bytes = file_path.read_bytes()
    reader = PdfReader(io.BytesIO(file_bytes))

    total_pages = len(reader.pages)
    pages: list[dict[str, Any]] = []
    empty_pages = 0
    page_text_lengths = []

    for i, page in enumerate(reader.pages):
        # NUL carries no text, and Postgres jsonb refuses it: one inside a
        # quoted provision would fail the dimension cache write mid-run.
        # None of the 2,000+ chunks indexed when this was added contained one,
        # so no chunk id moved.
        text = (page.extract_text() or "").replace("\x00", "")
        # Some PDFs encode text with no reliable word boundaries, so the
        # extractor returns "P osition of the European Parl iament". Repaired
        # here, before chunking, so retrieval, cue matching and citations all
        # see the document as it reads. See src/text_repair.
        text = repair_split_words(text)
        char_count = len(text.strip())
        page_text_lengths.append(char_count)
        if char_count == 0:
            empty_pages += 1
        pages.append(
            {
                "page_number": i + 1,
                "text": text,
            }
        )

    logger.info(
        "stage_2_document_parsed",
        file=str(file_path),
        parser=parser_name,
        total_pages=total_pages,
        empty_pages=empty_pages,
        total_chars=sum(page_text_lengths),
        avg_chars_per_page=round(sum(page_text_lengths) / max(total_pages, 1), 1),
        page_text_lengths=page_text_lengths[:20],
        truncated=total_pages > 20,
    )
    return pages


# What a reader can look up: a numbered division — "Article 13", "CHAPTER III",
# "Part 2 Society to aim for with AI". Case-sensitive, and deliberately blind
# to lines merely set in capitals: a ministerial signature ("RT HON MICHELLE
# DONELAN MP") or a gazette banner ("SPECIAL ISSUE") is indistinguishable from
# a heading by its shape, and a label carried forward from one mislabels every
# chunk until the next real division. A document with no numbered divisions
# gets no titles, and its citations are located by page alone.
_HEADING_RE = re.compile(
    r"^(?P<division>(?:Article|Section|Chapter|Part|Title|Annex|Schedule|Appendix|Principle|"
    r"ARTICLE|SECTION|CHAPTER|PART|TITLE|ANNEX|SCHEDULE|APPENDIX)\s+[0-9IVXLC]+[A-Za-z]?)"
    r"(?:\s*[-–:]?\s+[A-Z][^.;]*)?\s*$"
)
# Past this length, or once it has a verb, the "title" is the provision's own
# first sentence running on from the division number, as APPI lays its
# articles out ("Article 81 If non-disclosure information is supposed to be
# disclosed by merely"). A heading names a subject; it does not assert anything.
_HEADING_MAX_CHARS = 80
_SENTENCE_VERB_RE = re.compile(r"\b(?:shall|must|may|is|are|be|will|should)\b")
# A contents page names every division in the document, so a heading carried
# forward from one mislabels the body that follows: the UK white paper's last
# contents entry, "Annex C: How to respond to this consultation 83", titled 105
# of its 112 chunks. Recognised by lines ending in a page number.
_CONTENTS_ENTRY_RE = re.compile(r"\S\s*\.*\s+\d{1,3}\s*$")
_CONTENTS_MIN_ENTRIES = 5


def _heading_label(line: str) -> str | None:
    match = _HEADING_RE.match(line)
    if not match:
        return None
    line = " ".join(line.split())
    if len(line) > _HEADING_MAX_CHARS or _SENTENCE_VERB_RE.search(line):
        return match.group("division")
    return line


def structure_aware_split(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current_section: str | None = None
    current_text: list[str] = []
    current_pages: set[int] = set()
    last_heading: str | None = None

    # A BOUNDARY heuristic, not a heading detector, whatever it looks like.
    # Under IGNORECASE the capitals branch matches any line that opens with a
    # three-letter word; the small-section merge below glues those back into
    # ~3k-character blocks. Changing it would re-chunk every document and move
    # every stored result, so it only splits and names nothing. Titles come
    # from _HEADING_RE, carried forward from the last real heading, and are
    # left empty when a document has none.
    SECTION_PATTERNS = re.compile(
        r"^(#{1,3}\s+|(?:\d+\.)+\s+|[A-Z][A-Z\s\-]{2,50}|"
        r"(?:Article|Section|Clause|Chapter|Annex|Appendix)\s+\d+|"
        r"(?:Executive\s+Summary|Introduction|Background|Conclusion|Recommendations|Annexure)\s*:?\s*$)",
        re.IGNORECASE | re.MULTILINE,
    )

    def flush_section():
        if current_text:
            text = "\n".join(current_text).strip()
            if text:
                sections.append(
                    {
                        "section_title": current_section,
                        "text": text,
                        "pages": sorted(current_pages),
                        "start_page": min(current_pages) if current_pages else None,
                    }
                )

    for page in pages:
        lines = page["text"].split("\n")
        contents_page = (
            sum(1 for line in lines if _CONTENTS_ENTRY_RE.search(line)) >= _CONTENTS_MIN_ENTRIES
        )
        for line in lines:
            stripped = line.strip()
            if not contents_page:
                last_heading = _heading_label(stripped) or last_heading
            if SECTION_PATTERNS.match(stripped):
                flush_section()
                current_section = last_heading
                current_text = []
                current_pages = set()
            current_text.append(line)
            current_pages.add(page["page_number"])
    flush_section()

    if not sections:
        logger.warning("stage_3_chunking_no_structure_detected", pages=len(pages))
        for page in pages:
            sections.append(
                {
                    "section_title": None,
                    "text": page["text"],
                    "pages": [page["page_number"]],
                    "start_page": page["page_number"],
                }
            )

    MIN_SECTION_CHARS = 250
    merged: list[dict[str, Any]] = []
    merged_count = 0
    for sec in sections:
        if merged and len(sec["text"]) < MIN_SECTION_CHARS:
            prev = merged[-1]
            prev["text"] += "\n" + sec["text"]
            prev["pages"] = sorted(set(prev["pages"] + sec["pages"]))
            prev["start_page"] = prev["pages"][0]
            merged_count += 1
        else:
            merged.append(dict(sec))
    sections = merged

    logger.info(
        "stage_3_chunking_sections",
        raw_sections=len(sections) + merged_count,
        merged_small_sections=merged_count,
        final_sections=len(sections),
        section_titles=[s.get("section_title") for s in sections[:10]],
    )
    return sections


#: Part of every stored chunk's ingest key. Bump it whenever parsing, split-word
#: repair, chunking or titling changes, so documents indexed under the old
#: rules are read again rather than reused.
INGESTION_VERSION = "2026-09-28"


def ingest_key(file_path: Path) -> str:
    """Identifies one exact file read under one version of the ingestion rules.

    A run re-reads every document in its workspace, and parsing plus embedding
    is the largest fixed cost of a run. Chunk ids are derived from the
    document and the chunk text, so an unchanged file under unchanged rules
    produces exactly the chunks that are already stored.
    """
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()[:24]
    return f"{digest}:{INGESTION_VERSION}"


TOKEN_ESTIMATE_CHARS_PER_TOKEN = 4
TARGET_CHUNK_TOKENS = 700
MAX_CHUNK_CHARS = TARGET_CHUNK_TOKENS * TOKEN_ESTIMATE_CHARS_PER_TOKEN
SENTENCE_BOUNDARY_PATTERNS = re.compile(r"(?<=[.!?])\s+")

# ── Non-English chunk filter (reference-framework documents only) ────────
# Some framework PDFs (e.g. the OECD Catalogue) embed a short translated
# (French/Spanish/German) abstract or intro section inside an otherwise-
# English document. Those chunks surface as untranslated foreign quotes in
# an English-language report. We drop chunks that are *predominantly*
# non-English at ingestion for framework documents. User-uploaded policy
# documents are never filtered (they may legitimately be in any language).

_EN_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "of",
    "to",
    "in",
    "for",
    "on",
    "with",
    "is",
    "are",
    "that",
    "this",
    "these",
    "those",
    "as",
    "at",
    "by",
    "from",
    "or",
    "be",
    "it",
    "its",
    "not",
    "but",
    "which",
    "will",
    "can",
    "their",
    "has",
    "have",
    "had",
    "was",
    "were",
    "about",
}

_FOREIGN_STOPWORDS: dict[str, set[str]] = {
    "fr": {
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "et",
        "en",
        "au",
        "aux",
        "du",
        "de",
        "ce",
        "cette",
        "ces",
        "sur",
        "pour",
        "par",
        "dans",
        "avec",
        "est",
        "sont",
        "que",
        "qui",
        "plus",
        "pas",
        "nous",
        "vous",
        "ils",
        "elles",
        "à",
        "l'ia",
        "d'une",
        "d'un",
    },
    "es": {
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "de",
        "del",
        "y",
        "en",
        "con",
        "por",
        "para",
        "que",
        "es",
        "son",
        "se",
        "su",
        "sus",
        "como",
        "más",
        "pero",
    },
    "de": {
        "der",
        "die",
        "das",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einer",
        "eines",
        "und",
        "oder",
        "mit",
        "von",
        "für",
        "ist",
        "sind",
        "auf",
        "zu",
        "nicht",
        "auch",
        "als",
        "im",
        "in",
    },
    "it": {
        "il",
        "lo",
        "la",
        "i",
        "gli",
        "le",
        "un",
        "una",
        "di",
        "del",
        "e",
        "con",
        "per",
        "che",
        "è",
        "sono",
        "su",
        "da",
        "non",
    },
}


def _is_predominantly_non_english(text: str) -> bool:
    """Conservative stopword-dominance check. Only chunks where a foreign
    language's stopwords clearly outweigh English's are flagged, so ordinary
    English text with a few foreign words survives."""
    words = re.findall(r"[a-zA-ZÀ-ÿ'’-]+", text.lower())
    if len(words) < 15:
        return False
    en_hits = sum(1 for w in words if w in _EN_STOPWORDS)
    for stops in _FOREIGN_STOPWORDS.values():
        hits = sum(1 for w in words if w in stops)
        if hits >= 4 and hits > en_hits:
            return True
    return False


def _estimate_chunk_page(
    chunk_start: int,
    total_len: int,
    section_pages: list[int],
) -> int | None:
    if not section_pages:
        return None
    if len(section_pages) == 1:
        return section_pages[0]
    ratio = chunk_start / max(total_len, 1)
    page_range = max(section_pages) - min(section_pages)
    # round(), not int(). Truncation biases every estimate DOWNWARD and makes
    # the section's last page unreachable: a chunk 99% of the way through a
    # section spanning pages 4-6 gives int(0.99 * 2) == 1, so page 5 — page 6
    # is only ever reached at ratio exactly 1.0, which no chunk start hits.
    # Page numbers feed verify_citation's page check, so a systematic
    # off-by-one there turns correct citations into page mismatches.
    return min(section_pages) + round(ratio * page_range)


def _find_sentence_boundary(text: str, start: int, max_end: int) -> int:
    search_region = text[start:max_end]
    matches = list(SENTENCE_BOUNDARY_PATTERNS.finditer(search_region))
    if matches:
        last_match = matches[-1]
        boundary = start + last_match.end()
        if boundary > start + 100:
            return boundary
    paragraph_break = text.rfind("\n\n", start, max_end)
    if paragraph_break > start:
        return paragraph_break + 1
    line_break = text.rfind("\n", start, max_end)
    if line_break > start:
        return line_break + 1
    sentence_end = text.rfind(". ", start, max_end)
    if sentence_end > start:
        return sentence_end + 2
    return max_end


def recursive_character_split(
    text: str,
    metadata_base: dict[str, Any],
    section_title: str | None,
    page_number: int | None,
    framework_name: str | None,
    section_pages: list[int] | None = None,
) -> list[Chunk]:
    if len(text) <= MAX_CHUNK_CHARS:
        pg = _estimate_chunk_page(0, len(text), section_pages) if section_pages else page_number
        return [
            Chunk(
                chunk_id=str(uuid.uuid4()),
                text=text.strip(),
                metadata={**metadata_base, "section": section_title, "framework": framework_name},
                page_number=pg,
                section_title=section_title,
                framework_name=framework_name,
            )
        ]

    chunks: list[Chunk] = []
    start = 0

    while start < len(text):
        end = min(start + MAX_CHUNK_CHARS, len(text))

        if end < len(text):
            boundary = _find_sentence_boundary(text, start, end)
            end = boundary

        chunk_text = text[start:end].strip()
        if chunk_text:
            pg = (
                _estimate_chunk_page(start, len(text), section_pages)
                if section_pages
                else page_number
            )
            chunks.append(
                Chunk(
                    chunk_id=str(uuid.uuid4()),
                    text=chunk_text,
                    metadata={
                        **metadata_base,
                        "section": section_title,
                        "framework": framework_name,
                    },
                    page_number=pg,
                    section_title=section_title,
                    framework_name=framework_name,
                )
            )

        if end >= len(text):
            break

        # 25% overlap, measured against the chunk actually emitted rather than
        # the maximum: a sentence boundary can land close to `start`, and a
        # flat overlap would then put the next window BEHIND `start`, crawling
        # forward a character at a time and re-emitting the same passage. The
        # overlap keeps cross-boundary context without flooding the index with
        # duplicates.
        overlap_chars = min(MAX_CHUNK_CHARS // 4, (end - start) // 4)
        carry_start = max(end - overlap_chars, start + 1)
        # Snap the next window to a paragraph break only INSIDE the overlap,
        # never past `end`, or the text in between would never be indexed.
        next_para = text.find("\n\n", carry_start, end)
        start = next_para if next_para != -1 else carry_start

    return chunks


# Chunk ids are derived from the document plus the chunk's own text rather than
# minted fresh on every ingestion. Re-running an analysis re-ingests every
# document in the workspace; stable ids keep evidence carried over from a
# cached dimension pointing at chunks that exist. Same bytes in, same ids out.
_CHUNK_ID_NAMESPACE = uuid.UUID("b8f2c1a4-6d3e-4f27-9a5b-0c7e1d8a3f64")


def _deterministic_chunk_id(doc_key: str, ordinal: int, text: str) -> str:
    # Ordinal alone is not enough (re-chunking can shift boundaries) and text
    # alone is not enough (statutes repeat identical sentences); together they
    # are stable for an unchanged file and distinct for a changed one.
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return str(uuid.uuid5(_CHUNK_ID_NAMESPACE, f"{doc_key}|{ordinal}|{digest}"))


def ingest_document(
    file_path: Path,
    framework_name: str | None = None,
    doc_id: str | None = None,
    workspace_id: str | None = None,
    roles: list[str] | None = None,
    source_type: str | None = None,
    max_file_size: int | None = None,
    document_name: str | None = None,
) -> list[Chunk]:
    # Framework/reference PDFs (e.g. the 31MB AI Verify Assurance Pilot
    # report) use a larger size cap than user uploads (25MB). When called
    # from the framework-sync path, the caller passes the larger cap; user
    # uploads keep the strict cap (no override).
    if max_file_size is None and framework_name is not None:
        max_file_size = MAX_FRAMEWORK_FILE_SIZE_BYTES
    validation = validate_file_path(file_path, max_file_size=max_file_size)
    if not validation.valid:
        logger.error("ingestion_validation_failed", error=validation.error_message)
        raise ValueError(f"Validation failed: {validation.error_message}")
    if validation.ocr_warning:
        logger.warning("ocr_may_be_needed", file=str(file_path))

    pages = parse_pdf(file_path)
    sections = structure_aware_split(pages)

    doc_base = {
        "doc_id": doc_id or str(uuid.uuid4()),
        "source_file": file_path.name,
        "document_name": document_name or file_path.name,
        "framework": framework_name,
        "workspace_id": workspace_id,
        "roles": ",".join(roles) if roles else "",
        "source_type": source_type
        or ("incident_record" if roles and "module_4_incident" in roles else "framework"),
    }

    all_chunks: list[Chunk] = []
    empty_chunks = 0
    chunk_lengths = []
    for section in sections:
        section_title = section.get("section_title")
        start_page = section.get("start_page")
        section_pages = section.get("pages")
        chunks = recursive_character_split(
            text=section["text"],
            metadata_base=doc_base,
            section_title=section_title,
            page_number=start_page,
            framework_name=framework_name,
            section_pages=section_pages,
        )
        for c in chunks:
            c.workspace_id = workspace_id
            if not c.text.strip():
                empty_chunks += 1
            else:
                chunk_lengths.append(len(c.text))
        all_chunks.extend(chunks)

    # Assigned before the non-English filter below, so dropping a chunk never
    # renumbers the ones that survive.
    doc_key = "|".join((workspace_id or "", framework_name or "", file_path.name))
    for ordinal, chunk in enumerate(all_chunks):
        chunk.chunk_id = _deterministic_chunk_id(doc_key, ordinal, chunk.text)

    if framework_name is not None:
        kept: list[Chunk] = []
        for c in all_chunks:
            if _is_predominantly_non_english(c.text):
                continue
            kept.append(c)
        if len(kept) < len(all_chunks):
            logger.warning(
                "stage_3_chunking_non_english_filtered",
                framework=framework_name,
                dropped=len(all_chunks) - len(kept),
                kept=len(kept),
            )
        all_chunks = kept

    avg_len = round(sum(chunk_lengths) / max(len(chunk_lengths), 1), 1) if chunk_lengths else 0.0
    total_doc_chars = sum(len(s.get("text", "")) for s in sections)

    logger.info(
        "stage_3_chunking_complete",
        file=str(file_path),
        workspace_id=workspace_id,
        total_chunks=len(all_chunks),
        average_chunk_length=avg_len,
        empty_chunks=empty_chunks,
        total_document_chars=total_doc_chars,
        min_chunk_length=min(chunk_lengths) if chunk_lengths else 0,
        max_chunk_length=max(chunk_lengths) if chunk_lengths else 0,
    )
    return all_chunks
