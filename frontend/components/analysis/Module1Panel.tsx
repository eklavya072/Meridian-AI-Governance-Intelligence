"use client";

/* Section 1 of a dimension: the evaluation (coverage verdict, reasoning,
   depth and the provisions behind it). */

import { GovernanceGap } from "@/lib/api";
import HighlightedText from "@/components/HighlightedText";
import DepthBadge from "@/components/DepthBadge";
import ProvisionChecklist from "@/components/ProvisionChecklist";
import CitationAccordion from "@/components/CitationAccordion";
import {
  COVERAGE_GLOSS,
  CitationRow,
  CoverageIndicator,
  DEPTH_GLOSS,
  citationIsVisible,
} from "./shared";

// ── Section 1: Evaluation ────────────────────────────────────────────────

export function Module1Panel({ gap }: { gap: GovernanceGap }) {
  const m1 = gap.module_1;
  const depth = m1?.implementation_depth || gap.implementation_depth;
  const isCovered = gap.coverage === "Covered";

  // Evidence accordion data. "Sources" = real chunk-backed citations only
  // (honest-decline entries are rendered inside the panel but are not
  // counted as sources); the verified rate is over the real sources only.
  const docCards = (m1?.document_evidence || []).filter(citationIsVisible);
  const fwCards = (m1?.framework_evidence || []).filter(citationIsVisible);
  const realDoc = docCards.filter((c) => Boolean(c.chunk_id));
  const realFw = fwCards.filter((c) => Boolean(c.chunk_id));
  const totalSources = realDoc.length + realFw.length;
  // The sentence above states the rule; this states what THIS dimension
  // brought to it. Mechanisms carry the tier they were found at, so a count
  // of those at Obligatory or above is the number actually carried by a duty
  // — the quantity the bar is about, and the one a reader would otherwise
  // have to reconstruct from the mechanism list further down the page.
  const mechanismTally = (() => {
    const present = gap.mechanisms_present || {};
    const names = Object.keys(present);
    if (!names.length) return "";
    const total = names.length + (gap.mechanisms_absent?.length || 0);
    const bound = names.filter((k) => Number(present[k]) >= 3).length;
    return `Here, ${names.length} of ${total} expected mechanisms appear and ${bound} ${
      bound === 1 ? "is" : "are"
    } carried by a duty.`;
  })();
  const verifiedCount = [...realDoc, ...realFw].filter((c) => c.verified).length;

  return (
    <div className="space-y-5">
      {/* Label/value grid — quiet uppercase labels, dark values. The value
          is the emphasis; the label is the whisper. */}
      <div className="grid md:grid-cols-2 gap-x-6 gap-y-5">
        <div>
          <p className="module-label mb-1.5">Coverage</p>
          <CoverageIndicator coverage={gap.coverage} />
          {COVERAGE_GLOSS[gap.coverage] && (
            <p className="text-[11px] leading-[1.5] text-grey-600 mt-1.5">
              {COVERAGE_GLOSS[gap.coverage]}
              {mechanismTally && ` ${mechanismTally}`}
            </p>
          )}
        </div>
        <div>
          <p className="module-label font-bold mb-1.5">Implementation Depth</p>
          <DepthBadge level={depth} />
          {depth && DEPTH_GLOSS[depth] && (
            <p className="text-[11px] leading-[1.5] text-grey-600 mt-1.5">
              {DEPTH_GLOSS[depth]}
            </p>
          )}
        </div>
        {/* How much this particular cell is worth. Per-dimension external
            validation reaches 38% of cells; for the rest the only honest
            answer is to say what the verdict rests on, so "verify before you
            quote this" points at something specific rather than at the whole
            instrument. */}
        {gap.evidence_confidence && (
          <div>
            <p className="module-label mb-1.5">Evidence Behind This Verdict</p>
            <p className="module-value capitalize">{gap.evidence_confidence}</p>
          </div>
        )}
        <div>
          <p className="module-label mb-1.5">Gap Detected</p>
          <p className="module-value">
            {m1 ? (m1.gap_detected ? "Yes" : "No") : gap.gap_found ? "Yes" : "No"}
          </p>
        </div>
        {!isCovered && (
          <div>
            <p className="module-label mb-1.5">Reason Flagged</p>
            <p className="module-body">
              <HighlightedText text={m1?.reason_flagged || gap.reason_flagged || ""} />
            </p>
          </div>
        )}
      </div>

      <ProvisionChecklist gap={gap} />

      {/* Fully Covered tier: coverage_example (what led to the Covered
          verdict) replaces reason_flagged. When the model produced no
          coverage_example, fall back to coverage_reasoning so the verdict
          is never left unexplained. */}
      {isCovered ? (
        m1?.coverage_example ? (
          <div>
            <p className="module-heading mb-2">Coverage Examples</p>
            <p className="module-body">
              <HighlightedText text={m1.coverage_example} />
            </p>
          </div>
        ) : (
          (m1?.coverage_reasoning || gap.coverage_reasoning) && (
            <div>
              <p className="module-heading mb-2">Coverage Reasoning</p>
              <p className="module-body">
                <HighlightedText text={m1?.coverage_reasoning || gap.coverage_reasoning || ""} />
              </p>
            </div>
          )
        )
      ) : (
        (m1?.coverage_reasoning || gap.coverage_reasoning) && (
          <div>
            <p className="module-heading mb-2">Coverage Reasoning</p>
            <p className="module-body">
              <HighlightedText text={m1?.coverage_reasoning || gap.coverage_reasoning || ""} />
            </p>
          </div>
        )
      )}

      {/* Citation caveats — FABRICATED ONLY.
          A caveat is worth a reader's attention when they cannot check the
          reference themselves. Two severities are computed: fabricated (the
          number appears nowhere in the uploaded document) and unsupported
          (real and present in the document, but not in the passages retrieved
          for this dimension).
          Only the first is shown. Surfacing the second told readers to doubt
          citations they could look up and confirm — on the EU AI Act run it
          flagged "Article 10" for Fairness, which is the data-governance and
          bias-examination provision and exactly the right reference, plus a
          recital that occurs verbatim in the text. That is a retrieval-coverage
          signal about us, not a defect in the analysis, and putting it in front
          of the reader made correct work look unreliable. It is still recorded
          on the gap and logged server-side. */}
      {(gap.fabricated_citations?.length ?? 0) > 0 && (
        <div className="rounded-lg border border-status-red-line bg-status-red-tint px-3 py-2">
          <p className="module-heading mb-1 text-status-red">Citation caveat</p>
          <p className="module-body text-status-red">
            Not found anywhere in the uploaded document —{" "}
            {gap.fabricated_citations!.join(", ")}. Treat as unreliable.
          </p>
        </div>
      )}

      {m1?.depth_reasoning && (
        <div>
          <p className="module-heading mb-2">Implementation depth Reasoning</p>
          <p className="module-body"><HighlightedText text={m1.depth_reasoning} /></p>
        </div>
      )}

      {/* Evidence — one toggle, closed by default (shared CitationAccordion,
          same pattern as Module 2's Grounding Citations). The one-line
          summary shows the source split and verification rate without
          expanding. */}
      {totalSources === 0 ? (
        <p className="module-meta italic pt-1">
          No specific document or framework evidence found.
        </p>
      ) : (
        <CitationAccordion
          label="Evidence"
          total={totalSources}
          summary={`${realDoc.length} document · ${realFw.length} framework · ${verifiedCount}/${totalSources} verified`}
        >
          {docCards.length > 0 && (
            <div className="space-y-2">
              <p className="eyebrow !mb-1.5">From uploaded document</p>
              {docCards.map((c, i) => (
                <CitationRow key={`${c.chunk_id}-doc-${i}`} citation={c} />
              ))}
            </div>
          )}
          {fwCards.length > 0 && (
            <div className="space-y-2">
              <p className="eyebrow !mb-1.5">From reference frameworks</p>
              {fwCards.map((c, i) => (
                <CitationRow key={`${c.chunk_id}-fw-${i}`} citation={c} />
              ))}
            </div>
          )}
        </CitationAccordion>
      )}
    </div>
  );
}
