"use client";

/* Section 2 of a dimension: recommendations and framework alignment, or,
   for a fully covered dimension, the best practices it already meets. */

import { useContext } from "react";
import Link from "next/link";
import { GovernanceGap, Framework } from "@/lib/api";
import HighlightedText from "@/components/HighlightedText";
import CitationAccordion from "@/components/CitationAccordion";
import { resolveFrameworkLinks } from "@/lib/frameworkLinks";
import palette from "@/lib/palette.json";
import {
  CitationRow,
  FrameworkLibraryContext,
  FrameworkSynthesisBlock,
  citationIsVisible,
} from "./shared";

// ── Section 2: Recommendations & Alignment ───────────────────────────────

export const PRIORITY_DOT: Record<string, string> = {
  Critical: palette.status.red, // muted red
  High: palette.status.red, // muted red
  Medium: palette.analysis.amber,
  Low: palette.status.green, // muted forest green
};

// ── Fully Covered tier: Best Practices panel (replaces Recommendations) ─

function BestPracticesPanel({ gap }: { gap: GovernanceGap }) {
  const m2 = gap.module_2;
  const best = m2?.best_practices;
  if (!best) return null;

  // Grounding-citations accordion data (same semantics as Module 1 Evidence:
  // "sources" = real chunk-backed citations, verified rate over those).
  const stdCards = (m2?.standard_citations || []).filter(citationIsVisible);
  const realStd = stdCards.filter((c) => Boolean(c.chunk_id));
  const stdVerified = realStd.filter((c) => c.verified).length;

  return (
    <div className="space-y-5">
      <p className="module-body"><HighlightedText text={best.opening} /></p>

      {best.future_strengthening_opportunities.length > 0 && (
        <div>
          <p className="module-heading mb-2">
            Future Strengthening Opportunities
          </p>
          <ul className="module-list">
            {best.future_strengthening_opportunities.map((e, i) => (
              <li key={i}><HighlightedText text={e} /></li>
            ))}
          </ul>
        </div>
      )}

      {best.international_examples.length > 0 && (
        <div>
          <p className="module-heading mb-2">
            International Examples
          </p>
          <div className="space-y-3">
            {best.international_examples.map((ex, i) => (
              <div key={i} className="border rounded-lg p-3.5 bg-white/70 space-y-2">
                <p className="module-body"><HighlightedText text={ex.practice} /></p>
                {ex.alignment && (
                  <p className="module-body text-grey-800">
                    <span className="font-semibold">Relation to this policy: </span>
                    {ex.alignment}
                  </p>
                )}
                <div className="flex flex-wrap gap-3 module-meta">
                  {ex.country_or_source && <span>{ex.country_or_source}</span>}
                  {ex.reference && <span>Source: {ex.reference}</span>}
                </div>
                {ex.citation && <CitationRow citation={ex.citation} />}
              </div>
            ))}
          </div>
        </div>
      )}

      <FrameworkSynthesisBlock
        m2={m2}
        gap={gap}
        heading="Framework Synthesis — why this is compliant"
      />

      {realStd.length > 0 && (
        <CitationAccordion
          label="Sources"
          total={realStd.length}
          summary={`${realStd.length} practical ${
            realStd.length === 1 ? "source" : "sources"
          } · ${stdVerified}/${realStd.length} verified`}
        >
          {stdCards.map((c, i) => (
            <CitationRow key={`${c.chunk_id}-std-${i}`} citation={c} />
          ))}
        </CitationAccordion>
      )}
    </div>
  );
}

export function Module2Panel({ gap }: { gap: GovernanceGap }) {
  const m2 = gap.module_2;
  const frameworks = useContext(FrameworkLibraryContext);

  // Fully Covered tier → Best Practices panel; nothing to prioritise.
  if (gap.coverage === "Covered" && m2?.best_practices) {
    return <BestPracticesPanel gap={gap} />;
  }

  const recommendations = m2?.recommendations?.length
    ? m2.recommendations
    : gap.recommendation
    ? gap.recommendation.split("\n").filter(Boolean)
    : [];
  const priority = m2?.priority || "";

  // Clickable International Standard Reference: named sources that match a
  // Framework Library entry link to it; unmatched text stays plain.
  const referenceSegments = resolveFrameworkLinks(
    m2?.international_standard_reference || gap.un_recommendation || "",
    frameworks
  );
  // Grounding-citations accordion data (same semantics as Module 1 Evidence).
  const stdCards = (m2?.standard_citations || []).filter(citationIsVisible);
  const realStd = stdCards.filter((c) => Boolean(c.chunk_id));
  const stdVerified = realStd.filter((c) => c.verified).length;

  return (
    <div className="space-y-5">
      <div>
        <p className="module-label mb-1.5">Priority</p>
        {priority ? (
          <span className="dot-indicator">
            <span
              className="dot"
              style={{ background: PRIORITY_DOT[priority] || palette.black }}
            />
            <span>{priority}</span>
          </span>
        ) : (
          <span className="module-meta italic">—</span>
        )}
      </div>

      <div>
        <p className="module-heading mb-2">Recommendations</p>
        {/* Each recommendation is constrained twice — it must extend a
            mechanism that already exists in this document, and it must name
            the instrument that expects it. Saying so converts the list from
            advice a reader has to trust into advice they can check. */}
        {recommendations.length > 0 && (
          <p className="text-[11px] leading-[1.5] text-grey-600 mb-2">
            Each action extends something already in this document rather than proposing a new
            regime, and names the international instrument that expects it — so both ends of the
            recommendation can be checked against a source.
          </p>
        )}
        {recommendations.length ? (
          <ul className="module-list">
            {recommendations.map((r, i) => (
              <li key={i}><HighlightedText text={r} /></li>
            ))}
          </ul>
        ) : (
          <p className="module-meta italic">No recommendations.</p>
        )}
      </div>

      <div>
        <p className="module-heading mb-2">
          International Standard Reference
        </p>
        <p className="module-body">
          {referenceSegments.length
            ? referenceSegments.map((seg, i) =>
                seg.framework ? (
                  <Link
                    key={i}
                    href={`/frameworks?framework=${encodeURIComponent(
                      seg.framework.name
                    )}`}
                    // A real highlight, not just a color swap: `text-grey-950`
                    // resolves to the same near-black as ordinary body text
                    // (the palette killed blue), so underline alone read as a
                    // stray line under plain prose rather than a link. The
                    // background carries the "clickable" signal color cannot.
                    className="font-semibold text-grey-950 underline decoration-grey-950/50 underline-offset-2 bg-grey-950/[0.06] hover:bg-grey-950/[0.11] rounded px-1 py-0.5 -mx-1 transition-colors"
                    title={`Open ${seg.framework.name} in the Framework Library`}
                  >
                    {seg.text}
                  </Link>
                ) : (
                  <span key={i}>{seg.text}</span>
                )
              )
            : "—"}
        </p>
      </div>

      <FrameworkSynthesisBlock m2={m2} gap={gap} />

      {realStd.length > 0 && (
        <CitationAccordion
          label="Sources"
          total={realStd.length}
          summary={`${realStd.length} practical ${
            realStd.length === 1 ? "source" : "sources"
          } · ${stdVerified}/${realStd.length} verified`}
        >
          {stdCards.map((c, i) => (
            <CitationRow key={`${c.chunk_id}-std-${i}`} citation={c} />
          ))}
        </CitationAccordion>
      )}
    </div>
  );
}
