"use client";

/* Pieces the analysis page's panels share: the coverage vocabulary, its
   colours and glosses, and the citation row. */

import { createContext } from "react";
import { motion } from "motion/react";
import {
  GovernanceGap,
  ModuleCitation,
  Module2Recommendation,
  Framework,
} from "@/lib/api";
import HighlightedText from "@/components/HighlightedText";
import { verifiedSnap } from "@/lib/motion";
import palette from "@/lib/palette.json";

// Framework Library entries, loaded once on the analysis page. Module 2's
// International Standard Reference uses them to render clickable links to the
// Framework Library page; an empty list simply leaves the reference as text.
export const FrameworkLibraryContext = createContext<Framework[]>([]);

const COVERAGE_LABEL: Record<string, string> = {
  Covered: "Fully Covered",
  Partial: "Partially Covered",
  Missing: "Missing",
};

// Coverage tier accent colors — exact muted chart tokens. These carry the
// Covered/Partial/Missing semantic. Partial is a soft gold rather than amber:
// it softens the red-vs-green contrast at the tier that sits between them,
// for a calmer, more elegant read than the harsher stock traffic-light amber.
const TIER_DOT: Record<string, string> = {
  Covered: palette.status.green, // --chart-covered (muted forest green)
  Partial: palette.chart.partial, // --chart-partial (soft gold)
  Missing: palette.status.red, // --chart-missing (muted red)
  "Insufficient Evidence": palette.status.amber, // cannot tell — caution amber
};

// WHAT THE WORD MEANS, AND WHY THIS CELL EARNED IT.
//
// "Covered" and "Operationalized" are terms of art in this instrument and
// they do not mean what a reader assumes. Covered is a statement about legal
// FORCE — it says the provisions clear a duty bar — while a reader hearing
// "fully covered" naturally hears "this topic is well handled", which is a
// claim about breadth the verdict never made. A ministry quoting the word
// without the definition quotes something we did not say.
//
// Two lines, not a paragraph: the rule that produced the verdict, then the
// counts from THIS dimension that satisfied it. The second line is what
// makes it an explanation rather than a glossary — the same sentence under
// every cell would be documentation, not evidence.
export const COVERAGE_GLOSS: Record<string, string> = {
  Covered:
    "The provisions for this dimension clear the binding-force bar: two or more impose a duty, " +
    "or one duty is backed by enforcement. This is a finding about legal force, not about how " +
    "much the document says on the subject.",
  Partial:
    "Provisions for this dimension exist and were read, but they fall short of a governed " +
    "regime: commitments are stated without a duty, a single duty stands alone, or the duties " +
    "reach too few of the mechanisms this dimension calls for. The subject is addressed; it is " +
    "not yet fully obliged.",
  Missing:
    "Every provision of the supplied documents was read, and this dimension appears only in " +
    "passing: no duty, no named owner, no commitment to act. It describes the supplied text, " +
    "not the country's wider governance, which may sit in instruments not provided.",
  "Insufficient Evidence":
    "Nothing relevant to this dimension could be retrieved from the supplied documents or the " +
    "reference frameworks, so no verdict was formed. It is withheld rather than guessed.",
};

export const DEPTH_GLOSS: Record<string, string> = {
  Unaddressed: "No provision for this dimension was scored, so there is no regime to describe.",
  Emerging:
    "Intent is on the record, since the document states what it wants for this dimension, but " +
    "nothing yet assigns the work or requires it of anyone.",
  Delegated:
    "Responsibility has landed somewhere: an owner is named or a duty is stated, but the " +
    "machinery that would make it operate is not yet in the text.",
  Operationalized:
    "Binding requirements exist and carry mechanisms this dimension expects, but without the " +
    "audit, enforcement or redress machinery that would make the regime self-sustaining.",
  Institutionalized:
    "Binding requirements are paired with the enforcement, oversight or redress machinery that " +
    "makes them answerable. It is the highest stage this instrument recognises.",
};

export function CoverageIndicator({ coverage }: { coverage: string }) {
  return (
    <span className="dot-indicator">
      <span
        className="dot"
        style={{ background: TIER_DOT[coverage] || palette.black }}
      />
      <span>{COVERAGE_LABEL[coverage] || coverage}</span>
    </span>
  );
}

// ── Module citation row with verification badge ──────────────────────────

// ── Structured framework synthesis (Consensus / Differences / Overall) ───
// The backend now emits framework_synthesis as three labeled parts. Rendered
// as distinct blocks; falls back to the composed legacy string when the
// structured fields are absent (e.g. older saved analyses).

export function FrameworkSynthesisBlock({
  m2,
  gap,
  heading = "Framework Synthesis",
}: {
  m2?: Module2Recommendation | null;
  gap: GovernanceGap;
  heading?: string;
}) {
  const consensus = m2?.framework_synthesis_consensus?.trim();
  const differences = m2?.framework_synthesis_differences?.trim();
  const overall = m2?.framework_synthesis_overall_assessment?.trim();

  return (
    <div>
      <p className="module-heading mb-2">{heading}</p>
      {consensus || differences || overall ? (
        <div className="space-y-3">
          {consensus && (
            <div>
              <p className="module-label font-bold mb-1">Consensus</p>
              <p className="module-body"><HighlightedText text={consensus} /></p>
            </div>
          )}
          {differences && (
            <div>
              <p className="module-label font-bold mb-1">Differences</p>
              <p className="module-body"><HighlightedText text={differences} /></p>
            </div>
          )}
          {overall && (
            <div>
              <p className="module-label font-bold mb-1">Overall Assessment</p>
              <p className="module-body"><HighlightedText text={overall} /></p>
            </div>
          )}
        </div>
      ) : (
        <p className="module-body">
          <HighlightedText text={m2?.framework_synthesis || gap.framework_synthesis || "—"} />
        </p>
      )}
    </div>
  );
}

// Anti-fabrication display rule: a citation that cannot be attributed to a
// real named source ("Unknown" / empty) is HIDDEN entirely, never shown to
// users — either it is verified against a real source or it does not appear.
export function citationIsVisible(citation: ModuleCitation): boolean {
  if (citation.no_citation === true) return true; // honest decline, shown
  return Boolean(citation.source && citation.source !== "Unknown");
}

// Verified badge: "snaps into place" with a controlled spring — a deliberate
// micro-interaction. It reinforces the project's core trust mechanic (a
// citation is confirmed against a real chunk), so the settle is meaningful.
function VerifiedBadge() {
  return (
    <motion.span {...verifiedSnap} className="dot-indicator shrink-0 !text-xs">
      <motion.span
        className="dot !w-1.5 !h-1.5"
        style={{ background: palette.status.green }}
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ delay: 0.08, duration: 0.2 }}
        aria-hidden
      />
      <span className="text-grey-950">Verified</span>
    </motion.span>
  );
}

export function CitationRow({ citation }: { citation: ModuleCitation }) {
  const verified = citation.verified;
  const noCitation = citation.no_citation === true;

  // Anti-fabrication display rule: a citation that cannot be attributed to a
  // real named source ("Unknown" / empty) is HIDDEN entirely, never shown to
  // users — either it is verified against a real source or it does not appear.
  if (!citationIsVisible(citation)) {
    return null;
  }

  // Explicit "model declined to fabricate" state — NOT a failed verification.
  if (noCitation) {
    return (
      <div className="border rounded-lg p-3 bg-grey-50/70">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-grey-900 italic">
            No supporting passage was found in the retrieved context, so the
            model declined to fabricate a citation.
          </p>
          <span className="shrink-0 text-xs font-bold px-2 py-0.5 rounded bg-grey-950 text-white">
            No citation
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="border rounded-lg p-3 space-y-1.5 bg-grey-50/70">
      {/* The claim first, then the passage under it. A quote alone makes the
          reader reverse-engineer what it was offered to prove; naming the
          finding turns the card into an argument they can disagree with.
          line-clamp was 3 — a clause — which cut the operative passage off
          before the duty-bearer or the consequence. Provisions carry their
          force at the end, so the clamp is now generous enough to show one
          whole provision and only bites on a genuinely long extract. */}
      {citation.claim && (
        <p className="text-[13px] font-medium leading-snug text-grey-950">
          {citation.claim}
        </p>
      )}
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-grey-900 line-clamp-[8] flex-1 italic">
          “{citation.quote}”
        </p>
        {verified ? (
          <VerifiedBadge />
        ) : (
          <span className="dot-indicator shrink-0 !text-xs">
            <span className="dot !w-1.5 !h-1.5" style={{ background: palette.status.red }} />
            <span className="text-grey-950">Unverified</span>
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-3 text-xs font-medium text-grey-900">
        {citation.document_name ? (
          <span className="text-grey-950 underline underline-offset-2">
            Document: {citation.document_name}
          </span>
        ) : (
          citation.source && <span>Source: {citation.source}</span>
        )}
        {citation.page_number && <span>Page {citation.page_number}</span>}
      </div>
      {citation.verification && !verified && (
        <p className="text-xs font-medium text-grey-900 italic">
          {String(
            (citation.verification as Record<string, unknown>)?.failure_reason || ""
          )}
        </p>
      )}
    </div>
  );
}
