"""Rejoin words a PDF extractor split across a line, before anything reads them.

WHY THIS EXISTS
───────────────
Some PDFs encode text with character-level positioning and no reliable word
boundaries, so extraction produces "P osition of the European Parl iament of
13 March 2024" — every word intact in the document, shattered on the way out.
Both pypdf and PyMuPDF return byte-identical damage, so it is the file's own
encoding and not a parser choice.

Measured across the indexed corpus, counting only pairs where NEITHER token is
a word on its own but the join is (so "of the" and "in a" are not counted):

    EU AI Act (Regulation 2024/1689)   71.6 broken words per 1,000
    AI Verify Assurance Pilot          31.6
    Japan APPI 2003                     9.6
    Kenya AI Bill 2026                  7.2
    China PIPL 2021                     0.7
    UK AI Playbook                      0.0

It is essentially one document — but that document is the single most
important instrument in the corpus, serving both as a reference framework for
every country and as the EU's own assessed text. Damage there costs retrieval
recall, mechanism cue matches and duty detection on the one instrument
everything else is measured against.

WHY REPAIR RATHER THAN RE-EXTRACT
─────────────────────────────────
Re-extraction does not help; the damage is in the source encoding. Parsing
EUR-Lex HTML instead would (that was src/legal_structure.py, removed 19 Sep
because nothing ever wired it up), but that needs an HTML ingestion path this
pipeline does not have.

WHY THIS IS SAFE FOR CITATIONS
──────────────────────────────
A repair only fires when the two tokens are NOT both words on their own and
the joined result IS a dictionary word. "of the" and "to day" are left alone
because both halves are real words; "Parl iament" is rejoined because "parl"
is not. The document really does say "Parliament" — quoting "Parl iament" back
to a reader is less faithful to the source, not more.
"""

from __future__ import annotations

import gzip
import pathlib
import re
from functools import lru_cache

import structlog

logger = structlog.get_logger()

#: Domain vocabulary a general word list predates or omits.
_EXTRA = frozenset(
    {
        "deployer",
        "deployers",
        "provider",
        "providers",
        "cybersecurity",
        "biometric",
        "biometrics",
        "dataset",
        "datasets",
        "traceability",
        "interoperability",
        "algorithmic",
        "overseen",
        "stakeholder",
        "stakeholders",
        "chatbot",
        "chatbots",
        "metadata",
        "online",
    }
)

# The bundled list comes first so every environment repairs identically.
# Relying on the system list meant macOS (web2) repaired words, the Debian
# image (no list) repaired none, and the same PDF produced different chunks,
# chunk ids and possibly scores in the two. web2 is Webster's Second
# International (1934), whose copyright has lapsed; it is the list every
# stored run was indexed with.
_BUNDLED_WORD_LIST = pathlib.Path(__file__).resolve().parents[1] / "resources" / "web2.txt.gz"
_WORD_LISTS = (str(_BUNDLED_WORD_LIST), "/usr/share/dict/words", "/usr/dict/words")

#: A run of letters. Merges are decided on these and then SPLICED back into
#: the original string by index — never rebuilt from the tokens, because a
#: rebuild silently drops everything the pattern does not capture. An earlier
#: version did exactly that and turned "of 13 March 2024" into "of March".
_TOKEN_RE = re.compile(r"[A-Za-z]+")


@lru_cache(maxsize=1)
def _vocabulary() -> frozenset[str]:
    """A general English word list, or empty when the platform has none.

    An empty vocabulary disables repair entirely rather than guessing — a
    join it cannot verify is a join it must not make.
    """
    for path in _WORD_LISTS:
        p = pathlib.Path(path)
        if not p.exists():
            continue
        try:
            raw = (
                gzip.decompress(p.read_bytes()).decode(errors="ignore")
                if p.suffix == ".gz"
                else p.read_text(errors="ignore")
            )
            words = {w.strip().lower() for w in raw.splitlines() if len(w.strip()) > 1}
            if len(words) > 1000:
                return frozenset(words | _EXTRA)
        except OSError:
            continue
    logger.info("text_repair_disabled", reason="no system word list available")
    return frozenset()


def repair_split_words(text: str) -> str:
    """Rejoin PDF-split words. Returns `text` unchanged when unverifiable."""
    vocab = _vocabulary()
    if not vocab or not text:
        return text

    def _pass(s: str) -> str:
        toks = list(_TOKEN_RE.finditer(s))
        cuts: list[tuple[int, int, str]] = []
        i = 0
        while i < len(toks) - 1:
            a, b = toks[i], toks[i + 1]
            gap = s[a.end() : b.start()]
            # Only a single space can be a split word; a newline or any
            # punctuation between them means they are separate tokens.
            if gap == " " and b.group(0).islower():
                left, right = a.group(0), b.group(0)
                # BOTH halves must be non-words. Requiring only one lets
                # "in form ation" become "in formation" — a real word, a
                # different meaning, and a guess. Every genuine split seen in
                # this corpus has two non-words either side: "Parl iament",
                # "P osition", "w ould", "kno wn".
                neither_real = left.lower() not in vocab and right.lower() not in vocab
                joined = left + right
                if neither_real and joined.lower() in vocab:
                    cuts.append((a.start(), b.end(), joined))
                    i += 2
                    continue
            i += 1
        if not cuts:
            return s
        out, prev = [], 0
        for start, end, joined in cuts:
            out.append(s[prev:start])
            out.append(joined)
            prev = end
        out.append(s[prev:])
        return "".join(out)

    # A word can be split more than once ("inf or mation"), so iterate until it
    # settles — bounded, because each pass can only reduce the token count.
    for _ in range(3):
        repaired = _pass(text)
        if repaired == text:
            break
        text = repaired
    return text
