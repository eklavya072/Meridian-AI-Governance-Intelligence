"use client";

/* Section 4 of a dimension: case intelligence, shown only when a curated
   incident genuinely matches. */

import { motion } from "motion/react";
import { GovernanceGap } from "@/lib/api";
import HighlightedText from "@/components/HighlightedText";
import CitationAccordion from "@/components/CitationAccordion";
import { EASE, DUR } from "@/lib/motion";
import { CitationRow, citationIsVisible } from "./shared";

// ── Section 4: Case Intelligence (only when a genuine match exists) ──────
// Shown inside a dimension block ONLY when module_4.matched is true — a
// Partial/Missing dimension with no relevant curated incident shows nothing.

export function Module4Panel({ gap }: { gap: GovernanceGap }) {
  const m4 = gap.module_4;
  if (!m4 || !m4.matched || m4.incident_matches.length === 0) return null;

  return (
    <div className="space-y-5">
        {/* A curated incident is shown to make a gap concrete, not to predict
            one. The lead-in says so, because a documented failure printed
            under a dimension implies a forecast unless something states the
            opposite — and this instrument reads documents, not futures. */}
        <p className="text-[11px] leading-[1.5] text-grey-600">
          These are documented incidents from the curated case library that turned on the
          governance this dimension is missing. They are shown to make the gap concrete — what
          has already gone wrong elsewhere when this control was absent — not as a prediction
          about this jurisdiction.
        </p>
        {m4.incident_matches.map((inc, i) => {
          // Source citation — collapsed "Show Sources" toggle (same pattern
          // as Module 2) when the incident has a real chunk-backed citation;
          // a citation without a chunk stays plain so it isn't hidden by a
          // zero-count accordion.
          const citation = inc.citation;
          const realCitation = Boolean(
            citation && citation.chunk_id && citationIsVisible(citation)
          );
          return (
            <motion.div
              key={i}
              whileHover={{ scale: 1.01, y: -1 }}
              transition={{ duration: DUR.fast, ease: EASE.out }}
              className="border rounded-lg p-4 bg-white/70 space-y-2.5 hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between gap-2 flex-wrap">
                <p className="text-sm font-bold text-grey-950">
                  {inc.incident_name}
                </p>
                {inc.source && (
                  <span className="module-meta">{inc.source}</span>
                )}
              </div>
              {/* Facts first. The panel used to name a case and then jump
                  straight to why it is relevant, which asks the reader to
                  take the incident on trust. */}
              {inc.what_happened && (
                <p className="module-body">
                  <span className="font-semibold">What happened: </span>
                  <HighlightedText text={inc.what_happened} />
                </p>
              )}
              {inc.dimension_relevance && (
                <p className="module-body">
                  <span className="font-semibold">Relevance: </span>
                  <HighlightedText text={inc.dimension_relevance} />
                </p>
              )}
              {inc.potential_consequence && (
                <p className="module-body">
                  <span className="font-semibold">Potential Consequence: </span>
                  <HighlightedText text={inc.potential_consequence} />
                </p>
              )}
              {inc.lessons_learned && (
                <p className="module-body">
                  <span className="font-semibold">Lessons Learned: </span>
                  <HighlightedText text={inc.lessons_learned} />
                </p>
              )}
              {inc.mitigation && (
                <p className="module-body">
                  <span className="font-semibold">Mitigation: </span>
                  <HighlightedText text={inc.mitigation} />
                </p>
              )}
              {citation &&
                (realCitation ? (
                  <CitationAccordion
                    label="Sources"
                    total={1}
                    summary={`1 source · ${citation.verified ? "1/1" : "0/1"} verified`}
                  >
                    <CitationRow citation={citation} />
                  </CitationAccordion>
                ) : (
                  <CitationRow citation={citation} />
                ))}
            </motion.div>
          );
        })}
    </div>
  );
}
