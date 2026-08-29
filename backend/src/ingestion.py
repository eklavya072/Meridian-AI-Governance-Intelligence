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

    parser_name = "pypdf.PdfReader"
    file_bytes = file_path.read_bytes()
    reader = PdfReader(io.BytesIO(file_bytes))

    total_pages = len(reader.pages)
    pages: list[dict[str, Any]] = []
    empty_pages = 0
    page_text_lengths = []

    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
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


def structure_aware_split(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current_section: str | None = None
    current_text: list[str] = []
    current_pages: set[int] = set()

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
        for line in lines:
            if SECTION_PATTERNS.match(line.strip()):
                flush_section()
                current_section = line.strip()[:200]
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


TOKEN_ESTIMATE_CHARS_PER_TOKEN = 4
TARGET_CHUNK_TOKENS = 700
MAX_CHUNK_CHARS = TARGET_CHUNK_TOKENS * TOKEN_ESTIMATE_CHARS_PER_TOKEN
SENTENCE_BOUNDARY_PATTERNS = re.compile(r"(?<=[.!?])\s+")
OVERLAP_SENTENCES = 2

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
    return min(section_pages) + int(ratio * page_range)


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

        # 25% overlap (was 50%): the previous MAX_CHUNK_CHARS // 2 produced a
        # 51.7% exact-text duplicate rate across the collection (measured on
        # 21,744 live chunks) — each 2800-char window re-emitted 1400 chars of
        # the previous one. 700 chars of overlap keeps cross-boundary context
        # while roughly halving redundant index weight and duplicate chunks.
        # Measured against the chunk actually emitted, not the maximum. A
        # sentence boundary can land as little as 101 chars past `start`, and
        # a flat 700-char overlap then put `end - overlap_chars` BEHIND
        # `start`: the `start + 1` floor took over and the window crawled
        # forward one character at a time, re-emitting the same passage on
        # every pass. The EU AI Act carried runs of chunks 695, 692, 689 chars
        # long — each a three-character shift of the last — and 514 of its
        # 1,707 chunks sat in a duplicate set. Taking the quarter from
        # `end - start` keeps the stride at 75% of whatever was emitted, so
        # progress is always proportional to the chunk.
        overlap_chars = min(MAX_CHUNK_CHARS // 4, (end - start) // 4)
        carry_start = max(end - overlap_chars, start + 1)
        next_para = text.find("\n\n", carry_start)
        if next_para != -1 and next_para < end + MAX_CHUNK_CHARS:
            start = next_para
        else:
            start = carry_start

    return chunks


# Chunk ids are derived from the document plus the chunk's own text rather than
# minted fresh on every ingestion. Re-running an analysis re-ingests every
# document in the workspace, and a uuid4 per chunk meant an unchanged file came
# back under an entirely new set of ids: evidence carried over from a cached
# dimension then pointed at chunks that no longer existed, and every one of its
# citations failed the identity check while the dimension itself was fine. Same
# bytes in, same ids out.
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
        section.get("text", "")
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
