"use client";

/* Section 3 of a dimension: the implementation roadmap. Partial and
   Missing dimensions only. */

import { GovernanceGap } from "@/lib/api";
import HighlightedText from "@/components/HighlightedText";
import CitationAccordion from "@/components/CitationAccordion";
import palette from "@/lib/palette.json";
import { CitationRow, citationIsVisible } from "./shared";

// ── Section 3: Implementation Roadmap (Partial/Missing only) ─────────────
// Rendered ONLY when the dimension is Partial or Missing — Fully Covered
// dimensions show no Module 3 section at all (not even a header), per the
// coverage-tier design: don't dwell on what's fine, focus on what needs work.

const AGENCY_GROUNDING_DOT: Record<string, string> = {
  document_named: palette.status.green, // named in document — muted green
  document_implied: palette.analysis.amber,
  none_identified: palette.status.red, // none — muted red
};

export function Module3Panel({ gap }: { gap: GovernanceGap }) {
  const m3 = gap.module_3;
  if (!m3) return null;
  const grounding = m3.responsible_agency_grounding || "none_identified";

  // Grounding citations — collapsed "Show Sources" toggle, same pattern as
  // Module 2. Rows are visible citations; the count/verified rate are over
  // real chunk-backed citations only.
  const citations = (m3.citations || []).filter(citationIsVisible);
  const realCitations = citations.filter((c) => Boolean(c.chunk_id));
  const citationsVerified = realCitations.filter((c) => c.verified).length;

  return (
    <div className="space-y-5">
      {/* The timelines are the part a reader is most likely to distrust, and
          the part with the best answer: they are computed, not written. The
          note says where they come from so the "why 0-10 months" question is
          answered before it is asked. */}
      {m3.phases.length > 0 && (
        <p className="text-[11px] leading-[1.5] text-grey-600">
          Phase timelines are calculated from this dimension&apos;s own profile: its coverage
          tier, depth stage, how many mechanisms the document already operates, and whether it
          names a responsible agency. Each phase carries the reasoning that produced its range.
        </p>
      )}
      {m3.phases.length > 0 && (
        <div className="space-y-3">
          {m3.phases.map((ph, i) => (
            <div key={i} className="border rounded-lg p-4 bg-white/70">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <p className="text-sm font-bold text-grey-900">
                  {ph.phase || `Phase ${i + 1}`}
                </p>
                {ph.timeline && (
                  <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-grey-950 text-white">
                    {ph.timeline}
                  </span>
                )}
              </div>
              {ph.objective && (
                <p className="module-body mt-2"><HighlightedText text={ph.objective} /></p>
              )}
              {ph.steps.length > 0 && (
                <ol className="mt-3 space-y-2.5">
                  {ph.steps.map((s, j) => (
                    <li key={j} className="module-body flex gap-2.5">
                      <span className="font-bold text-grey-950 shrink-0 tabular-nums">
                        {j + 1}.
                      </span>
                      <span><HighlightedText text={s} /></span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="border rounded-lg p-4 bg-white/70">
        <p className="module-label mb-1.5">Responsible Agency</p>
        <p className="module-value">{m3.responsible_agency || "Not named"}</p>
        <div className="mt-1.5 flex items-center gap-2">
          <span className="dot-indicator !gap-1.5 !text-xs">
            <span
              className="dot !w-1.5 !h-1.5"
              style={{ background: AGENCY_GROUNDING_DOT[grounding] || palette.status.red }}
            />
            <span className="text-grey-950">
              {grounding === "document_named"
                ? "Named in document"
                : grounding === "document_implied"
                ? "Implied by document"
                : "Not specified by policy"}
            </span>
          </span>
          {grounding === "none_identified" && (
            <span className="text-[11px] font-medium text-grey-900 italic">
              No agency is invented here. Implementation responsibility is for the
              adopting government to assign.
            </span>
          )}
        </div>
      </div>

      {m3.documentation_requirements.length > 0 && (
        <div>
          <p className="module-heading mb-2">
            Documentation Requirements
          </p>
          <ul className="module-list">
            {m3.documentation_requirements.map((d, i) => (
              <li key={i}><HighlightedText text={d} /></li>
            ))}
          </ul>
        </div>
      )}

      {m3.monitoring_checklist.length > 0 && (
        <div>
          <p className="module-heading mb-2">
            Monitoring / Compliance Checklist
          </p>
          <ul className="space-y-2.5">
            {m3.monitoring_checklist.map((m, i) => (
              <li key={i} className="module-body flex items-start gap-2.5">
                <span className="font-bold text-grey-950 mt-0.5 shrink-0 text-sm leading-relaxed">☐</span>
                <span><HighlightedText text={m} /></span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {realCitations.length > 0 && (
        <CitationAccordion
          label="Sources"
          total={realCitations.length}
          summary={`${realCitations.length} implementation ${
            realCitations.length === 1 ? "source" : "sources"
          } · ${citationsVerified}/${realCitations.length} verified`}
        >
          {citations.map((c, i) => (
            <CitationRow key={`${c.chunk_id}-${i}`} citation={c} />
          ))}
        </CitationAccordion>
      )}
    </div>
  );
}
