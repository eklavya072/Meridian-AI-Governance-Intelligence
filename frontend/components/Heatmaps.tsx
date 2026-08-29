"use client";

/**
 * Regulatory Trajectory — dimension x run heatmap for the Decision Analytics
 * section.
 *
 * The two-run pattern (guidelines, then guidelines + statute) exists
 * specifically to show what a second instrument changes — today that means
 * opening two run tabs and reading two tables from memory. This puts every
 * run's verdict for every dimension in one grid, columns labeled by the
 * actual instrument added rather than "Run 1" / "Run 2" (a workspace can
 * hold three runs, and "Run 2" says nothing about what changed). Reads
 * entirely off `governance_gaps` already stored per analysis — no re-run
 * needed for it to appear on an existing workspace.
 *
 * Shown only when the run being VIEWED is not the workspace's first — the
 * caller gates this, since a trajectory into a future run the reader hasn't
 * reached yet has nothing to compare against.
 */

import { useMemo, useRef } from "react";
import { motion } from "motion/react";
import { EASE } from "@/lib/motion";
import { useInViewOnce } from "@/lib/useInViewOnce";
import type { Analysis } from "@/lib/api";

// Same abbreviation the Dimension Radar uses for this one long name.
const SHORT_LABEL: Record<string, string> = {
  "Environmental Sustainability": "Env. Sustainability",
};

function shortLabel(dimension: string): string {
  return SHORT_LABEL[dimension] || dimension;
}

const COVERAGE_FILL: Record<string, string> = {
  Covered: "#3F7A52",
  Partial: "#C9AF7A",
  Missing: "#A8483F",
  "Insufficient Evidence": "#B07E2B",
};

function analysisDocuments(a: Analysis): string[] {
  return a.evaluated_documents?.length
    ? a.evaluated_documents
    : a.document_name
    ? [a.document_name]
    : [];
}

interface ComparisonCell {
  coverage: string;
  maturity: string;
}

interface ComparisonColumn {
  analysis: Analysis;
  /** What to put in the header: the instrument(s) actually added this run,
   *  not the cumulative list — run 1 already showed the baseline document,
   *  so run 2's header should read "+ AI Bill 2026", not repeat both names. */
  headerDocs: string[];
  isBaseline: boolean;
}

function buildComparisonMatrix(analyses: Analysis[]): {
  dimensions: string[];
  columns: ComparisonColumn[];
  cells: Map<string, ComparisonCell>; // key `${dimension}::${analysis_id}`
} {
  // Chronological, oldest first — a trajectory reads left to right the way
  // the runs actually happened.
  const sorted = [...analyses].sort(
    (a, b) => (a.created_at || "").localeCompare(b.created_at || "")
  );

  let previousDocs = new Set<string>();
  const columns: ComparisonColumn[] = sorted.map((a, i) => {
    const docs = analysisDocuments(a);
    const added = docs.filter((d) => !previousDocs.has(d));
    previousDocs = new Set(docs);
    return {
      analysis: a,
      headerDocs: i === 0 ? docs : added.length > 0 ? added : docs,
      isBaseline: i === 0,
    };
  });

  const dimensionOrder: string[] = [];
  const seen = new Set<string>();
  const cells = new Map<string, ComparisonCell>();
  for (const a of sorted) {
    for (const g of a.governance_gaps || []) {
      if (!seen.has(g.dimension)) {
        seen.add(g.dimension);
        dimensionOrder.push(g.dimension);
      }
      cells.set(`${g.dimension}::${a.analysis_id}`, {
        coverage: g.coverage,
        maturity: g.governance_maturity || "",
      });
    }
  }
  return { dimensions: dimensionOrder, columns, cells };
}

export function RunComparisonHeatmap({ analyses }: { analyses: Analysis[] }) {
  const { dimensions, columns, cells } = useMemo(
    () => buildComparisonMatrix(analyses),
    [analyses]
  );
  const ref = useRef<HTMLDivElement>(null);
  const entered = useInViewOnce(ref);

  if (columns.length < 2 || dimensions.length === 0) return null;

  return (
    <div ref={ref}>
      <div
        className="grid gap-1"
        style={{
          gridTemplateColumns: `minmax(104px, auto) repeat(${columns.length}, minmax(78px, 1fr))`,
        }}
      >
        <div />
        {columns.map((col) => (
          <div key={col.analysis.analysis_id} className="text-center px-1 pb-1">
            <p
              className="text-[9px] font-bold uppercase tracking-wide text-navy-600"
              title={analysisDocuments(col.analysis).join(" + ")}
            >
              {col.isBaseline ? "Baseline" : "Added"}
            </p>
            <p className="text-[10px] font-semibold text-navy-950 leading-tight mt-0.5 line-clamp-2">
              {col.isBaseline ? "" : "+ "}
              {col.headerDocs.join(" + ")}
            </p>
          </div>
        ))}

        {dimensions.map((dimension, ri) => (
          <RowFragment key={dimension}>
            <div className="flex items-center pr-2 border-t border-[color:var(--border)] first:border-t-0">
              <p className="text-[11px] font-medium text-navy-950">{shortLabel(dimension)}</p>
            </div>
            {columns.map((col, ci) => {
              const cell = cells.get(`${dimension}::${col.analysis.analysis_id}`);
              const fill = cell ? COVERAGE_FILL[cell.coverage] || "#8A8A8A" : "rgba(10,10,10,0.035)";
              return (
                <motion.div
                  key={col.analysis.analysis_id}
                  className="rounded-md flex flex-col items-center justify-center gap-0 py-1.5 px-1"
                  style={{ background: cell ? fill : undefined }}
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={entered ? { opacity: 1, scale: 1 } : {}}
                  transition={{ duration: 0.3, delay: ri * 0.04 + ci * 0.03, ease: EASE.out }}
                  title={cell ? `${dimension}: ${cell.coverage} — ${cell.maturity}` : "Not assessed"}
                >
                  {cell ? (
                    <>
                      <span className="text-[9px] font-bold uppercase tracking-wide leading-tight text-center text-white">
                        {cell.coverage}
                      </span>
                      <span className="text-[8px] font-medium leading-tight text-center text-white/85">
                        {cell.maturity}
                      </span>
                    </>
                  ) : (
                    <span className="text-[9px] text-navy-600">—</span>
                  )}
                </motion.div>
              );
            })}
          </RowFragment>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2.5 pt-2 border-t border-[color:var(--border)]">
        {(["Covered", "Partial", "Missing"] as const).map((c) => (
          <span key={c} className="inline-flex items-center gap-1.5 text-[11px] text-navy-600">
            <span
              className="h-2 w-2 rounded-sm shrink-0"
              style={{ background: COVERAGE_FILL[c] }}
            />
            {c}
          </span>
        ))}
      </div>
    </div>
  );
}

// Grid children must be direct children of the grid container for
// `grid-template-columns` to apply per-item — a wrapping <div> per row would
// nest a row's cells inside one grid cell instead of spanning the grid.
// Fragment keeps them as siblings while still letting a row carry one `key`.
function RowFragment({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
