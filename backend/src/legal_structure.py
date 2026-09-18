"""Read legislation as the structure it is, instead of guessing at it from a PDF.

Everything v2-v5 does to recover legal structure — finding recitals by page
number, re-attaching list items by enumeration marker, spotting headings by
length — is reconstruction of information the publisher already encodes and
we threw away by ingesting a PDF.

The EU publishes the Official Journal as HTML carrying the OJ's own
structural markup. For Regulation (EU) 2024/1689 that is 180 elements with
id="rct_N" (recitals), 113 with id="art_N" (articles) and 13 annexes —
exactly the instrument's real composition. Parsing those ids is not a
heuristic: an element either is a recital or it is not.

What this deletes rather than improves:

  recital detection      an id, not a page-number guess
  list-item severance    a paragraph is one element, lists included
  heading detection      titles are their own elements
  the definitions article Article 3 is identifiable by number and title
  cross-references       "in accordance with Article 10" resolves to art_10

Scope, stated plainly: this works for instruments published in OJ HTML or
Akoma Ntoso (OASIS LegalDocML). Most of the corpus — Kenya's strategy, India's
guidelines, Egypt's guidance — exists only as PDF and keeps the v5 path. So
this improves the jurisdictions we already measure best. It is still worth
having, because the EU is the reference point every other score is read
against, and it was the instrument the PDF path damaged most.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class LegalUnit:
    """One addressable division of an instrument."""

    kind: str  # recital | article | annex | preamble
    number: str  # "10", "178", "III"
    title: str = ""
    text: str = ""
    path: str = ""  # "Article 10", "Recital 178"
    operative: bool = True

    @property
    def is_definitions(self) -> bool:
        return "definition" in (self.title or "").lower()


_TAG_RE = re.compile(r"<[^>]+>")
# The OJ wraps every division in <div class="eli-subdivision" id="...">.
# The body of a division runs to the NEXT top-level division. Sub-divisions
# ("art_10.tit_1", the article's own title element) must not terminate it —
# an earlier version let them, and every article came back empty.
_DIV_RE = re.compile(
    r'<div[^>]*\bid="(?P<id>(?:rct|art|anx)_[A-Za-z0-9]+)"[^>]*>'
    r"(?P<body>.*?)"
    # \Z so the LAST division is not lost when the markup is truncated or
    # has no closing body tag.
    r'(?=<div[^>]*\bid="(?:rct|art|anx)_[A-Za-z0-9]+"|</body|\Z)',
    re.DOTALL | re.IGNORECASE,
)


def _text_of(fragment: str) -> str:
    """Visible text of an HTML fragment, with table cells kept apart."""
    s = re.sub(r"</(td|th|tr|p|div|li)>", " ", fragment, flags=re.IGNORECASE)
    s = _TAG_RE.sub(" ", s)
    s = _html.unescape(s)
    # Collapse ALL whitespace, newlines included. Inside one division a line
    # break is layout, not meaning — and the OJ puts a list marker "(f)" in
    # its own table cell, so keeping the break severed every marker from the
    # text it introduces and defeated the list repair downstream.
    return re.sub(r"\s+", " ", s).strip()


def parse_oj_html(markup: str) -> list[LegalUnit]:
    """Structured units from an EUR-Lex Official Journal HTML document.

    Returns [] for anything that is not OJ HTML, so a caller can fall back to
    the PDF path without a special case.
    """
    if not markup or 'id="rct_' not in markup and 'id="art_' not in markup:
        return []

    units: list[LegalUnit] = []
    for m in _DIV_RE.finditer(markup):
        div_id = m.group("id")
        body = m.group("body")
        # "art_10.tit_1" is the TITLE of article 10, not a separate division.
        if ".tit_" in div_id or ".sti_" in div_id:
            continue
        kind_key, _, number = div_id.partition("_")
        kind = {"rct": "recital", "art": "article", "anx": "annex"}.get(kind_key)
        if not kind:
            continue
        text = _text_of(body)
        if not text:
            continue
        title = ""
        if kind == "article":
            # The OJ puts the article's subject in its own styled element.
            t = re.search(r'class="oj-sti-art"[^>]*>(.*?)</p>', body, re.DOTALL | re.IGNORECASE)
            if t:
                title = _text_of(t.group(1))
            text = re.sub(rf"^\s*Article\s+{re.escape(number)}\s*", "", text)
            if title:
                text = re.sub(rf"^\s*{re.escape(title)}\s*", "", text)
        label = {"recital": "Recital", "article": "Article", "annex": "Annex"}[kind]
        units.append(
            LegalUnit(
                kind=kind,
                number=number,
                title=title,
                text=text.strip(),
                path=f"{label} {number}",
                # RECITALS ARE NOT OPERATIVE. Under EU law they aid
                # interpretation and create no obligation. This is the single
                # largest correction available: 60% of the AI Act's "binding"
                # sentences were coming from here.
                operative=(kind != "recital"),
            )
        )
    logger.info(
        "oj_html_parsed",
        recitals=sum(1 for u in units if u.kind == "recital"),
        articles=sum(1 for u in units if u.kind == "article"),
        annexes=sum(1 for u in units if u.kind == "annex"),
    )
    return units


# A numbered paragraph inside an article: "1.   High-risk AI systems shall..."
# Whitespace inside a division is collapsed (see _text_of), so paragraph
# markers cannot be anchored to line starts. "   1.   High-risk AI systems"
# becomes " 1. High-risk AI systems" and is matched positionally instead.
_PARA_RE = re.compile(r"(?:(?<=\s)|^)(\d{1,2})\.\s(?=[A-Z(])")


def article_paragraphs(unit: LegalUnit) -> list[tuple[str, str]]:
    """Split an article into its numbered paragraphs, keeping each one whole.

    A paragraph is the unit a duty is written in, lists and all, so the
    enumerated points inside it never get severed from the stem that carries
    their subject and modal.
    """
    if unit.kind != "article" or not unit.text:
        return []
    marks = list(_PARA_RE.finditer(unit.text))
    if not marks:
        return [(unit.path, unit.text)]
    out: list[tuple[str, str]] = []
    for i, mk in enumerate(marks):
        start = mk.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(unit.text)
        body = unit.text[start:end].strip()
        if body:
            out.append((f"{unit.path}({mk.group(1)})", body))
    return out


def operative_text(units: list[LegalUnit], include_annexes: bool = True) -> list[tuple[str, str]]:
    """(citation path, text) for every operative division. Recitals excluded."""
    out: list[tuple[str, str]] = []
    for u in units:
        if not u.operative:
            continue
        if u.kind == "annex" and not include_annexes:
            continue
        if u.is_definitions:
            # An article that defines terms imposes nothing.
            continue
        if u.kind == "article":
            out.extend(article_paragraphs(u))
        else:
            out.append((u.path, u.text))
    return out
