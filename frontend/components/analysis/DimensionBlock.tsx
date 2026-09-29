"use client";

/* One governance dimension on the analysis page: its header row and, when
   opened, the four sections. */

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Analysis, GovernanceGap } from "@/lib/api";
import CitationCard from "@/components/CitationCard";
import DepthBadge from "@/components/DepthBadge";
import ModuleStack, { type ModuleStackItem } from "@/components/ModuleStack";
import { EASE, DUR, staggerChild } from "@/lib/motion";
import palette from "@/lib/palette.json";
import { CoverageIndicator } from "./shared";
import { Module1Panel } from "./Module1Panel";
import { Module2Panel, PRIORITY_DOT } from "./Module2Panel";
import { Module3Panel } from "./Module3Panel";
import { Module4Panel } from "./Module4Panel";

// ── Per-dimension block ──────────────────────────────────────────────────

// ── Dimension analysis-failure state (LLM quota/provider error) ──────────

function AnalysisFailedPanel({ gap }: { gap: GovernanceGap }) {
  return (
    <div className="rounded-xl border border-[color:var(--border)] bg-white p-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="dot-indicator !gap-1.5 !text-xs">
          <span className="dot !w-1.5 !h-1.5" style={{ background: palette.status.red }} />
          <span className="font-semibold text-grey-950">Analysis failed</span>
        </span>
        <span className="text-xs font-bold text-grey-950">
          This dimension was NOT assessed — no coverage verdict exists.
        </span>
      </div>
      <p className="text-sm font-medium text-grey-950">
        The analysis service did not return a result for this dimension on
        this run, so nothing here is a finding about the document.
      </p>
      <p className="text-xs font-medium text-grey-900 italic">
        Use Re-run above to assess it. Dimensions that completed are kept, so
        only this one is redone.
      </p>
    </div>
  );
}

export function DimensionBlock({ gap, index }: { gap: GovernanceGap; index: number }) {
  const [open, setOpen] = useState(false);
  const depth = gap.module_1?.implementation_depth || gap.implementation_depth;
  const failed = Boolean(gap.analysis_error);

  // Skiper16-style scroll deck: one sticky card per module, in order
  // (Evaluation → Recommendations/Best Practices → Roadmap → Case). The deck
  // card provides the module name + status meta, so panels are content-only.
  // Items are conditional per the coverage tier — Fully Covered shows Best
  // Practices (no roadmap), Partial/Missing show Recommendations + Roadmap,
  // and Case Intelligence only when a genuine curated incident match exists.
  const isBestPractices =
    gap.coverage === "Covered" && Boolean(gap.module_2?.best_practices);
  const hasRoadmap =
    gap.coverage !== "Covered" && Boolean(gap.module_3);
  const m4 = gap.module_4;
  const hasCase = Boolean(
    m4 && m4.matched && m4.incident_matches.length > 0
  );

  const moduleItems: ModuleStackItem[] = [
    {
      id: "evaluation",
      title: "Evaluation",
      content: <Module1Panel gap={gap} />,
    },
    {
      id: "alignment",
      title: isBestPractices
        ? "Best Practices & Alignment"
        : "Recommendations & Alignment",
      meta: isBestPractices ? (
        <span className="dot-indicator !gap-1.5 !text-xs">
          <span className="dot !w-1.5 !h-1.5" style={{ background: palette.status.green }} />
          <span className="text-grey-950">No critical gaps</span>
        </span>
      ) : gap.module_2?.priority ? (
        <span className="dot-indicator !gap-1.5 !text-xs">
          <span
            className="dot !w-1.5 !h-1.5"
            style={{
              background: PRIORITY_DOT[gap.module_2.priority] || palette.black,
            }}
          />
          <span className="text-grey-950">{gap.module_2.priority}</span>
        </span>
      ) : undefined,
      content: <Module2Panel gap={gap} />,
    },
    ...(hasRoadmap
      ? [
          {
            id: "roadmap",
            title: "Implementation Roadmap",
            content: <Module3Panel gap={gap} />,
          },
        ]
      : []),
    ...(hasCase
      ? [
          {
            id: "case",
            title: "Case Intelligence",
            meta: (
              <span className="dot-indicator !gap-1.5 !text-xs">
                <span className="dot !w-1.5 !h-1.5" style={{ background: palette.black }} />
                <span className="text-grey-950">Curated incident match</span>
              </span>
            ),
            content: <Module4Panel gap={gap} />,
          },
        ]
      : []),
  ];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      // Once per card, a little into the viewport — the reveal a reader
      // scrolling down the dimension list used to see. `once: true` so an
      // opened-then-scrolled-past card never re-plays the entrance.
      viewport={{ once: true, amount: 0.2 }}
      className={`bg-white rounded-xl shadow-sm border ${
        failed ? "border-status-red-line" : "border-[color:var(--border)]"
      }`}
      transition={{
        layout: { duration: DUR.slow, ease: EASE.outSoft },
        opacity: { duration: DUR.base, ease: EASE.out, delay: Math.min(index * 0.05, 0.25) },
        y: { duration: DUR.base, ease: EASE.out, delay: Math.min(index * 0.05, 0.25) },
      }}
    >
      {/* Header — owns its own corner rounding now that the card no longer
          clips with overflow-hidden (which would break the sticky deck). */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={`pressable w-full flex items-center justify-between gap-3 px-5 py-4 text-left transition-colors ${
          open ? "rounded-t-xl" : "rounded-xl"
        } ${failed ? "hover:bg-status-red-tint/60" : "hover:bg-grey-50/70"}`}
      >
        <div className="flex items-center gap-3 flex-wrap">
          <h3 className="font-bold text-lg text-grey-950">{gap.dimension}</h3>
          {failed ? (
            <span className="dot-indicator">
              <span className="dot" style={{ background: palette.status.red }} />
              <span>Analysis failed</span>
            </span>
          ) : (
            <motion.span
              initial={{ scale: 0.7, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{
                type: "spring",
                stiffness: 520,
                damping: 30,
                mass: 0.6,
                delay: 0,
              }}
              className="inline-flex"
            >
              <CoverageIndicator coverage={gap.coverage} />
            </motion.span>
          )}
          {/* An un-assessed dimension has no depth — a stage badge beside
              'Analysis failed' or 'Insufficient Evidence' would describe a
              regime nobody assessed. Risk labels (Low/Medium/High) were removed from the
              UI; risk_level stays in the data for backend priority logic. */}
          {!failed && gap.coverage !== "Insufficient Evidence" && (
            <motion.span
              initial={{ scale: 0.7, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{
                type: "spring",
                stiffness: 520,
                damping: 30,
                mass: 0.6,
                delay: 0.05,
              }}
              className="inline-flex"
            >
              <DepthBadge level={depth} />
            </motion.span>
          )}
        </div>
        {/* Chevron: rotation communicates the open/closed state — transform
            only, no layout jump. */}
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: DUR.fast, ease: EASE.out }}
          className="text-grey-950 text-sm shrink-0 inline-block"
          aria-hidden
        >
          ▼
        </motion.span>
      </button>

      {/* Expand/collapse: content fades in; the card's own layout animation
          handles the height growth (no overflow-hidden, so the sticky deck
          cards keep sticking to the viewport while scrolling). */}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="dim-content"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: DUR.base, ease: EASE.out }}
            className="px-5 pb-5 space-y-4"
          >
            <motion.div variants={staggerChild}>
              {failed ? (
                <AnalysisFailedPanel gap={gap} />
              ) : (
                <ModuleStack items={moduleItems} />
              )}
            </motion.div>

              {gap.evidence.length > 0 && (
                <motion.details variants={staggerChild} className="border-t pt-3">
                  <summary className="text-sm font-semibold text-grey-950 cursor-pointer hover:opacity-70 transition-opacity">
                    Retrieved passages ({gap.evidence.length})
                  </summary>
                  <div className="mt-3 space-y-3">
                    {gap.evidence.map((ev) => (
                      <CitationCard key={ev.chunk_id} evidence={ev} />
                    ))}
                  </div>
                </motion.details>
              )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
