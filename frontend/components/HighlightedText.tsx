import { Fragment } from "react";

/**
 * Bolds the 2-4 most load-bearing terms in a paragraph — a legal reference
 * (Article 12, Recital 27, Section 4), a named governance body (Ministry of
 * X, National AI Council), or a named policy/instrument (in quotes, or Title
 * Case multi-word phrase ending in Act/Policy/Guidelines/Framework/Strategy)
 * — instead of every match, which would turn a dense paragraph into clutter.
 *
 * The division list must track the vocabulary documents actually use. It
 * originally stopped at Article/Section/Chapter/Annex, so every "Recital 27"
 * in the EU analyses rendered flat — the single most-cited division type in
 * the corpus was the one form that could never be highlighted.
 *
 * The budget scales with paragraph length. A flat cap of 2 left a 900-char
 * evaluation with the same emphasis as a one-line note, so the long panels
 * read as undifferentiated grey.
 *
 * Deliberately conservative: if nothing matches, the paragraph renders
 * exactly as plain text, unchanged.
 */

// Mirrors the backend's DIVISION_KINDS (src/verify.py): the citation checker
// and the highlighter must recognise the same vocabulary, or a citation can
// verify against the source yet render unemphasised.
const DIVISION_KINDS =
  "Article|Recital|Section|Chapter|Annex|Part|Clause|Paragraph|Principle|Rule|Schedule";

const BODY_SUFFIXES =
  "Ministry|Council|Board|Authority|Commission|Committee|Agency|Institute|Office|Department|Centre|Center|Bureau|Corporation|Regulator|Regulatory Authority";
const INSTRUMENT_SUFFIXES =
  "Act|Policy|Guidelines|Framework|Strategy|Regulation|Directive|Standard|Rules|Bill";

// Priority order: legal reference > named body > named instrument. Matched
// against the RAW text (not case-insensitively) since these are proper
// nouns / formal references by construction.
const PATTERNS: RegExp[] = [
  // "Article 12", "Section 4(2)", "Chapter III" — legal/document references.
  new RegExp(
    `\\b(?:${DIVISION_KINDS})\\s+[0-9IVXLC]+[A-Za-z]?(?:\\([0-9a-zA-Z]+\\))?`,
    "g"
  ),
  // "Ministry of Digital Affairs", "Department of ICT and Innovation" —
  // suffix word FIRST, qualifier after "of/for". Tried before the reverse
  // pattern below since "Ministry of X" would otherwise match as a bare
  // "Ministry" (the qualifier sits after the suffix here, not before it).
  new RegExp(
    `\\b(?:${BODY_SUFFIXES})\\s+(?:of|for)\\s+(?:[A-Z][a-zA-Z'-]*\\s*(?:and|&|of)?\\s*){1,5}`,
    "g"
  ),
  // "National AI Ethics Board", "Data Protection Commission" — 1-4
  // capitalized words BEFORE a body suffix.
  new RegExp(
    `\\b(?:[A-Z][a-zA-Z'-]*\\s+){0,4}(?:${BODY_SUFFIXES})\\b`,
    "g"
  ),
  // A quoted policy/instrument name, or an unquoted Title Case phrase ending
  // in Act/Policy/Guidelines/etc.
  new RegExp(
    `"[^"]{4,80}"|\\b(?:[A-Z][a-zA-Z'-]*\\s+){1,6}(?:${INSTRUMENT_SUFFIXES})\\b`,
    "g"
  ),
];

// Fallback tiers. The proper-noun patterns above only fire on paragraphs that
// happen to name a provision, a body or an instrument — plenty of real
// analysis prose names none of them and rendered completely flat, so emphasis
// appeared or vanished according to the sentence's grammar rather than its
// importance. These run only after the patterns above are exhausted, so a
// named provision always outranks a generic term.
//
// A curated governance lexicon rather than "longest words": an automatic
// picker bolds whatever is longest, which in policy prose is reliably a piece
// of throat-clearing ("notwithstanding", "implementation").
const GOVERNANCE_TERMS = [
  // Force — the distinction the whole instrument turns on.
  "legally binding", "binding obligation", "binding duty", "binding requirement",
  "enforceable right", "statutory duty", "mandatory requirement", "legal obligation",
  "enforcement action", "administrative fine", "penalties", "sanctions", "liability",
  "voluntary", "non-binding", "aspirational", "best practice",
  // Institutions and process.
  "supervisory authority", "competent authority", "oversight body", "regulatory oversight",
  "conformity assessment", "impact assessment", "risk assessment", "audit trail",
  "certification", "accreditation", "incident reporting", "post-market monitoring",
  // Rights and safeguards.
  "human oversight", "human-in-the-loop", "right to explanation", "right to human review",
  "data subject rights", "informed consent", "data minimisation", "purpose limitation",
  "redress", "grievance", "remedy", "due process",
  // Cross-cutting dimension language.
  "high-risk", "prohibited practices", "bias testing", "non-discrimination",
  "algorithmic transparency", "explainability", "traceability", "accountability",
  "digital divide", "accessibility", "energy consumption", "carbon footprint",
];

const GOVERNANCE_PATTERN = new RegExp(
  `\\b(?:${GOVERNANCE_TERMS.slice()
    .sort((a, b) => b.length - a.length)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|")})\\b`,
  "gi"
);

// Last resort: a Title Case run of 2-4 words (a named thing the patterns above
// did not classify). Never a single word — one capitalised word at the start
// of a sentence is not a name.
const TITLE_CASE_PHRASE = /\b(?:[A-Z][a-zA-Z'-]+\s+){1,3}[A-Z][a-zA-Z'-]+\b/g;

const FALLBACK_PATTERNS: RegExp[] = [GOVERNANCE_PATTERN, TITLE_CASE_PHRASE];

// At least 2 highlights per paragraph, up to 5 for a long one. The floor is
// deliberate: a reader scanning a column of dimension cards should be able to
// find the load-bearing phrase in every one, not only the ones that cite an
// Article.
function highlightBudget(length: number): number {
  if (length < 320) return 2;
  if (length < 600) return 3;
  if (length < 900) return 4;
  return 5;
}

export default function HighlightedText({ text }: { text: string }) {
  if (!text) return null;

  const MAX_HIGHLIGHTS = highlightBudget(text.length);

  type Match = { start: number; end: number };
  const matches: Match[] = [];

  for (const pattern of PATTERNS) {
    if (matches.length >= MAX_HIGHLIGHTS) break;
    pattern.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = pattern.exec(text)) !== null && matches.length < MAX_HIGHLIGHTS) {
      const start = m.index;
      // Trim trailing whitespace the "of/for ... {1,5}" capture can leave
      // dangling (e.g. a match ending right before a comma or period).
      const trimmedLen = m[0].replace(/\s+$/, "").length;
      const end = start + trimmedLen;
      // Skip if this overlaps an already-chosen match (higher-priority
      // pattern already claimed this span).
      const overlaps = matches.some((mm) => start < mm.end && end > mm.start);
      if (!overlaps && trimmedLen > 2) {
        matches.push({ start, end });
      }
    }
  }

  // Top up to the floor from the fallback tiers before giving up on emphasis.
  if (matches.length < MAX_HIGHLIGHTS) {
    for (const pattern of FALLBACK_PATTERNS) {
      if (matches.length >= MAX_HIGHLIGHTS) break;
      pattern.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = pattern.exec(text)) !== null && matches.length < MAX_HIGHLIGHTS) {
        const start = m.index;
        const trimmedLen = m[0].replace(/\s+$/, "").length;
        const end = start + trimmedLen;
        const overlaps = matches.some((mm) => start < mm.end && end > mm.start);
        if (!overlaps && trimmedLen > 3) {
          matches.push({ start, end });
        }
      }
    }
  }

  if (matches.length === 0) return <>{text}</>;

  matches.sort((a, b) => a.start - b.start);

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  matches.forEach((m, i) => {
    if (m.start > cursor) parts.push(text.slice(cursor, m.start));
    parts.push(
      <strong key={i} className="font-semibold text-navy-950">
        {text.slice(m.start, m.end)}
      </strong>
    );
    cursor = m.end;
  });
  if (cursor < text.length) parts.push(text.slice(cursor));

  return (
    <>
      {parts.map((p, i) => (
        <Fragment key={i}>{p}</Fragment>
      ))}
    </>
  );
}
