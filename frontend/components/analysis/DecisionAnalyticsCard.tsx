"use client";

/* The executive summary card at the top of an analysis: coverage and depth
   charts, the dimension radar, the weakest dimensions and the run comparison. */

import { useMemo } from "react";
import { motion } from "motion/react";
import { Analysis, GovernanceGap, DecisionAnalytics } from "@/lib/api";
import { CoverageDonut, DepthGauge, StageHistogram } from "@/components/DashboardCharts";
import { RunComparisonHeatmap, byStage } from "@/components/Heatmaps";
import {
  RadarChart,
  RadarGrid,
  RadarAxis,
  RadarLabels,
  RadarArea,
  type RadarTooltip,
} from "@/components/RadarChart";
import { staggerContainer, staggerChild } from "@/lib/motion";
import { ForceLadder } from "./ForceLadder";
import palette from "@/lib/palette.json";

// ── Dimension Radar — coverage tier → ring position ─────────────────────
// Each dimension's value is its coverage tier on a 0–100 scale, so every
// vertex lands exactly on one of the radar's three rings (33 Missing /
// 66 Partial / 100 Fully Covered). "Not assessed" dimensions (LLM failure
// or Insufficient Evidence) sit at the centre — the same grey lump the
// coverage donut treats as "Not Assessed" — and are footnoted below.
const RADAR_SCORE: Record<string, number> = {
  Covered: 100,
  Partial: 66,
  Missing: 33,
};

// Compact axis labels so long dimension names stay inside the viewBox.
const RADAR_DISPLAY: Record<string, string> = {
  "Environmental Sustainability": "Env. Sustainability",
};

const RADAR_TIER_LEGEND = [
  { label: "Missing", color: palette.status.red },
  { label: "Partially Covered", color: palette.chart.partial },
  { label: "Fully Covered", color: palette.status.green },
] as const;

// Hover tooltip on the radar — reverse-maps the 0-100 ring position back
// to the coverage tier it encodes (0 = not assessed, 33 = Missing, 66 =
// Partial, 100 = Fully Covered), in the same muted status colours as the
// legend and donut.
const radarTooltip = (value: number): RadarTooltip => {
  if (value >= 100) return { label: "Fully Covered", color: palette.status.green };
  if (value >= 66) return { label: "Partially Covered", color: palette.chart.partial };
  if (value >= 33) return { label: "Missing", color: palette.status.red };
  return { label: "Not assessed", color: palette.grey["500"] };
};

function RadarRingLegend({ label, color }: { label: string; color: string }) {
  return (
    <span className="flex items-center gap-1.5 text-sm font-medium text-grey-950">
      <span
        className="w-2.5 h-2.5 rounded-full border-2 shrink-0"
        style={{ borderColor: color }}
      />
      <span>{label}</span>
    </span>
  );
}

// ── Executive decision analytics (deterministic aggregates) ──────────────

// Weakest dimensions rule: take the lowest coverage tier present (Missing is
// weaker than Partial, Partial weaker than Covered), then keep only the
// highest-priority dimensions in that tier — Critical/High only, no Medium/
// Low. Priority is the Module 2 recommendation priority, used purely as a
// sort/filter key so the card stays factual (coverage tier is deterministic
// from the ladder). If none of the weakest tier carry Critical/High priority
// the tier is shown as-is, so the card is never empty while gaps exist.
const PRIORITY_RANK: Record<string, number> = {
  Critical: 0,
  High: 1,
  Medium: 2,
  Low: 3,
};

const WEAK_TIER: Record<string, number> = {
  Missing: 0,
  Partial: 1,
  Covered: 2,
};

export function DecisionAnalyticsCard({
  analytics,
  gaps,
  analyses,
  currentAnalysisId,
}: {
  analytics: DecisionAnalytics;
  gaps: GovernanceGap[];
  analyses: Analysis[];
  currentAnalysisId: string;
}) {
  // Every dimension's absent mechanisms, pooled and ranked across the whole
  // run. Pooling is the point: a reader wants the most consequential gaps in
  // the document, not the worst gap inside each dimension separately.
  const priorityGaps = useMemo(() => {
    const rows = gaps.flatMap((g) =>
      (g.priority_gaps || []).map((pg) => ({
        dimension: g.dimension,
        mechanism: pg.mechanism,
        expected_by: pg.expected_by,
      })),
    );
    return rows
      .filter((r) => r.expected_by > 0)
      .sort((a, b) => b.expected_by - a.expected_by)
      .slice(0, 8);
  }, [gaps]);

  const corpusSize = useMemo(
    () => Math.max(0, ...gaps.map((g) => g.framework_corpus_size || 0)),
    [gaps],
  );

  // The trajectory compares this run against what came before it — on the
  // very first run there is no "before", so it has nothing to show. Gated on
  // the run actually being VIEWED, not just on the workspace having more than
  // one run overall: opening run 1 of a two-run workspace must not show a
  // trajectory into a future run the reader hasn't gotten to yet.
  const isBaselineRun = useMemo(() => {
    if (analyses.length < 2) return true;
    return [...analyses].sort(byStage)[0]?.analysis_id === currentAnalysisId;
  }, [analyses, currentAnalysisId]);
  const radar = useMemo(() => {
    const values: Record<string, number> = {};
    let notAssessed = 0;
    for (const g of gaps) {
      const assessed =
        !g.analysis_error && g.coverage !== "Insufficient Evidence";
      if (!assessed) notAssessed += 1;
      values[g.dimension] = assessed ? RADAR_SCORE[g.coverage] ?? 0 : 0;
    }
    return { values, notAssessed };
  }, [gaps]);

  const radarMetrics = useMemo(
    () =>
      gaps.map((g) => ({
        key: g.dimension,
        label: RADAR_DISPLAY[g.dimension] || g.dimension,
      })),
    [gaps]
  );
  const radarSeries = useMemo(
    () => [{ label: "Coverage", color: palette.black, values: radar.values }],
    [radar.values]
  );

  // Weakest dimensions — see the rule above. Pairs with Strongest Dimension.
  const weakestDimensions = useMemo(() => {
    const assessed = gaps.filter(
      (g) => !g.analysis_error && g.coverage !== "Insufficient Evidence"
    );
    if (!assessed.length) return [];
    const weakestRank = Math.min(
      ...assessed.map((g) => WEAK_TIER[g.coverage] ?? 9)
    );
    // Nothing is below Covered — every dimension is fully covered, so there
    // is no weakest class to report. "None flagged" is the honest answer.
    if (weakestRank >= 2) return [];
    const weakest = assessed.filter(
      (g) => (WEAK_TIER[g.coverage] ?? 9) === weakestRank
    );
    const high = weakest.filter(
      (g) =>
        g.module_2?.priority === "Critical" || g.module_2?.priority === "High"
    );
    const list = high.length ? high : weakest;
    return list
      .slice()
      .sort(
        (a, b) =>
          (PRIORITY_RANK[a.module_2?.priority ?? ""] ?? 9) -
          (PRIORITY_RANK[b.module_2?.priority ?? ""] ?? 9)
      )
      .map((g) => g.dimension);
  }, [gaps]);

  return (
    <motion.div
      variants={staggerContainer(0.08, 0.05)}
      initial="hidden"
      animate="show"
      className="card"
    >
      <div className="flex items-center justify-between mb-4">
        <motion.h2
          variants={staggerChild}
          className="text-xl font-bold tracking-tight text-grey-950"
        >
          Decision Analytics
        </motion.h2>
      </div>

      {/* The force ladder leads: it is the idea the rest of the page grades
          by. The coverage and depth charts follow it. */}
      <motion.div variants={staggerChild} className="mb-4">
        <ForceLadder gaps={gaps} />
      </motion.div>

      {/* Row 1: the two charts side by side — coverage donut and depth
          gauge, both animating their fill on load. These are the visual
          centerpiece of the section. Panels are solid white on the card
          surface — clean, not glass. */}
      <div className="grid md:grid-cols-2 gap-4">
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4"
        >
          <p className="eyebrow mb-3">Coverage Distribution</p>
          <CoverageDonut analytics={analytics} />
        </motion.div>
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4"
        >
          <p className="eyebrow mb-3">Implementation Depth</p>
          <DepthGauge analytics={analytics} />
          <StageHistogram analytics={analytics} />
        </motion.div>
      </div>

      {/* Row 2: the dimension radar — every dimension at a glance, each
          vertex on the ring of its coverage tier, sitting right below the
          donut + gauge. Uses the reference composite API (RadarChart +
          RadarGrid/Axis/Labels/Area). */}
      {radarMetrics.length > 0 && (
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4 mt-4"
        >
          <div className="flex items-center justify-between flex-wrap gap-2 mb-1">
            <p className="eyebrow">Dimension Radar</p>
            {radar.notAssessed > 0 && (
              <p className="text-[11px] font-medium text-grey-900 italic">
                {radar.notAssessed} dimension
                {radar.notAssessed > 1 ? "s" : ""} not assessed (centre)
              </p>
            )}
          </div>
          <div className="flex flex-col items-center">
            <RadarChart
              data={radarSeries}
              metrics={radarMetrics}
              size={380}
              ariaLabel="Dimension coverage radar chart"
            >
              <RadarGrid />
              <RadarAxis />
              <RadarLabels />
              <RadarArea index={0} showPoints tooltip={radarTooltip} />
            </RadarChart>
            <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 mt-2 text-xs">
              {RADAR_TIER_LEGEND.map((tier) => (
                <RadarRingLegend key={tier.label} {...tier} />
              ))}
            </div>
            <p className="text-[11px] font-medium text-grey-900 mt-1.5 italic">
              Ring position = coverage tier
            </p>
          </div>
        </motion.div>
      )}

      {/* Row 3: the two highlight cards — weakest + strongest dimension,
          below the radar. Weakest = the lowest coverage tier present, kept
          only when it carries Critical/High priority (no Medium/Low), sorted
          by priority; the strongest is the highest-depth dimension. */}
      <div className="grid md:grid-cols-2 gap-4 mt-4">
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4"
        >
          <p className="eyebrow mb-2">Weakest Dimensions</p>
          {weakestDimensions.length ? (
            <div className="flex flex-wrap gap-2 mt-2">
              {weakestDimensions.map((d) => (
                <span key={d} className="dot-indicator">                <span
                  className="dot"
                  style={{ background: palette.status.red }}
                />
                  <span>{d}</span>
                </span>
              ))}
            </div>
          ) : (
            <p className="text-sm font-medium text-grey-950 mt-1">None flagged</p>
          )}
        </motion.div>
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4"
        >
          <p className="eyebrow mb-2">Strongest Dimension</p>
          <p className="text-lg font-semibold text-grey-950 mt-1">
            {analytics.strongest_dimension || "—"}
          </p>
        </motion.div>
      </div>

      {/* Row 4: what to fix first.

          The mechanism inventory was computed, persisted and never shown. A
          flat "4 of 6 provided" cannot answer the only question a ministry
          actually has, which is which of the absent two matters more. Ordering
          the gaps by how many reference instruments name each one answers it,
          and grounds the answer outside our own opinion.

          Deliberately NOT a score. Nothing here feeds coverage or depth; it
          decides what a reader sees at the top of a list. */}
      {priorityGaps.length > 0 && (
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4 mt-4"
        >
          <p className="eyebrow mb-1">Priority Gaps</p>
          <p className="text-[11px] text-grey-600 mb-3">
            Mechanisms with no supporting provision in the evidence scored for
            their dimension, shown only where at least half of the{" "}
            {corpusSize || 43} indexed instruments expect them. Ordered by how
            many expect each. This ranks what to look at first; it does not
            affect any score.
          </p>
          <ul className="space-y-1.5">
            {priorityGaps.map((g) => (
              <li
                key={`${g.dimension}-${g.mechanism}`}
                className="flex items-center gap-3 text-sm"
              >
                <span
                  className="h-1.5 rounded-full shrink-0"
                  style={{
                    width: `${Math.max(8, (g.expected_by / (corpusSize || 43)) * 84)}px`,
                    background: palette.status.red,
                  }}
                />
                <span className="font-medium text-grey-950">{g.mechanism}</span>
                <span className="text-grey-600 text-[11px]">{g.dimension}</span>
                <span className="ml-auto text-[11px] text-grey-600 tabular-nums">
                  expected by {g.expected_by} of {corpusSize || 43}
                </span>
              </li>
            ))}
          </ul>
        </motion.div>
      )}

      {/* Row 4: regulatory trajectory — only meaningful once a workspace
          holds more than one run. Shows what each added instrument actually
          moved, per dimension, without opening two run tabs to read two
          tables from memory. */}
      {!isBaselineRun && (
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4 mt-4"
        >
          <p className="eyebrow mb-1">Regulatory Trajectory</p>
          <p className="text-[11px] text-grey-600 mb-3">
            Coverage and depth stage per dimension, across every run in
            this workspace — what each added instrument actually moved.
          </p>
          <RunComparisonHeatmap analyses={analyses} />
        </motion.div>
      )}
    </motion.div>
  );
}
