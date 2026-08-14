"use client";

/**
 * Dashboard charts for the Decision Analytics section.
 *
 * Recharts with animated fill on load. Colors come ONLY from the muted
 * chart tokens in globals.css (--chart-covered/partial/missing/neutral) —
 * never Recharts' own saturated default palette, which is what made the
 * dashboard read like a stock demo. These exact values are the same ones
 * used by the dot status indicators so charts and badges speak one language.
 */

import { useMemo, useState } from "react";
import { DecisionAnalytics } from "@/lib/api";
import {
  PieChart,
  PieSlice,
  PieCenter,
  PieLegend,
} from "@/components/PieChart";
import Gauge from "@/components/Gauge";

// ── Coverage donut ──────────────────────────────────────────────────────

// Muted chart tokens — the exact values from globals.css. The coverage
// distribution is the one chart that carries the Covered/Partial/Missing
// semantic, so it uses the muted status colors; everything else is grey.
const CHART_COVERED = "#3F7A52"; // muted forest green
const CHART_PARTIAL = "#B07E2B"; // muted amber
const CHART_MISSING = "#A8483F"; // muted red
const CHART_NEUTRAL = "#8A8A8A"; // grey — not assessed
const CHART_EMPTY = "rgba(10, 10, 10, 0.08)"; // --border, for zero-state slice

export function CoverageDonut({
  analytics,
}: {
  analytics: DecisionAnalytics;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const slices = useMemo(
    () => [
      { label: "Fully Covered", value: analytics.covered, color: CHART_COVERED },
      { label: "Partially Covered", value: analytics.partial, color: CHART_PARTIAL },
      { label: "Missing", value: analytics.missing, color: CHART_MISSING },
      {
        label: "Not Assessed",
        value: analytics.insufficient_evidence + analytics.analysis_failed,
        color: CHART_NEUTRAL,
      },
    ],
    [analytics]
  );

  const zeroSlices = slices.every((s) => s.value === 0);
  const chartData = zeroSlices
    ? [{ label: "Not Assessed", value: 1, color: CHART_EMPTY }]
    : slices;

  return (
    <div className="flex flex-col items-center">
      <div className="relative">
        {/* Native interactive donut (see components/PieChart.tsx) — hovering a
            slice pops it out and swaps the centre readout; the legend below
            stays in sync both ways via the shared hoveredIndex. */}
        <PieChart
          data={chartData}
          hoveredIndex={hoveredIndex}
          onHoverChange={setHoveredIndex}
          innerRadius={56}
          size={180}
          ariaLabel="Coverage distribution donut chart"
        >
          {chartData.map((_, i) => (
            <PieSlice key={i} index={i} />
          ))}
          <PieCenter
            defaultValue={analytics.assessed_dimensions || 8}
            defaultLabel="dimensions"
          />
        </PieChart>
      </div>

      <PieLegend
        items={slices}
        hoveredIndex={hoveredIndex}
        onHoverChange={setHoveredIndex}
      />
    </div>
  );
}

// ── Maturity gauge ──────────────────────────────────────────────────────

// Native Gauge (see components/Gauge.tsx) in the old gauge's layout — a
// single smooth 260° arc with "65.6 / 100" in the centre, the stage in a
// dot-indicator below, and the caption under that. The arc sweeps in and the
// number counts up when the chart scrolls into view.

export function MaturityGauge({
  analytics,
}: {
  analytics: DecisionAnalytics;
}) {
  const index = Math.max(0, Math.min(100, analytics.maturity_index || 0));
  const stage = analytics.overall_governance_maturity || "—";

  return (
    <div className="flex flex-col items-center">
      <Gauge
        value={index}
        centerValue={index}
        defaultLabel="/ 100"
        size={180}
        inactiveFillOpacity={0.08}
        useGradient
        ariaLabel={`Governance maturity gauge: ${index.toFixed(1)} of 100`}
      />
      <div className="mt-3 text-center">
        <span className="dot-indicator">
          <span className="dot" style={{ background: CHART_COVERED }} />
          <span className="text-sm text-navy-800">{stage}</span>
        </span>
      </div>
    </div>
  );
}

// Fully greyscale ramp for the stage histogram — dark-grey steps, no
// semantic color: the maturity block stays strictly monochrome.
const GAUGE_COLORS = ["#8A8A8A", "#595959", "#262626", "#0A0A0A"];

// ── Mini stage histogram (kept from the original card) ─────────────────
// The gauge replaces the segmented bar, but the per-stage distribution is
// still valuable — rendered as a compact, animated strip below the gauge.

const STAGE_ORDER = ["Ad Hoc", "Developing", "Defined", "Managed", "Optimized"];

export function StageHistogram({
  analytics,
}: {
  analytics: DecisionAnalytics;
}) {
  const counts = STAGE_ORDER.map((stage) => ({
    stage,
    count: analytics.maturity_distribution?.[stage] || 0,
  }));
  const max = Math.max(...counts.map((c) => c.count), 1);

  return (
    <div className="mt-2 w-full">
      <div className="flex items-end gap-[3px] h-12">
        {counts.map((c, i) => (
          <div key={c.stage} className="flex-1 flex flex-col items-center gap-1">
            <span className="text-[10px] font-semibold text-navy-800">
              {c.count}
            </span>
            <div className="w-full rounded-t-sm overflow-hidden flex items-end flex-1">
              <div
                className="w-full rounded-t-sm"
                style={{
                  height: `${Math.max((c.count / max) * 100, c.count > 0 ? 8 : 2)}%`,
                  background: GAUGE_COLORS[i % GAUGE_COLORS.length],
                  opacity: c.count > 0 ? 1 : 0.15,
                }}
                title={`${c.stage}: ${c.count}`}
              />
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-[3px] mt-1">
        {counts.map((c) => (
          <span
            key={c.stage}
            className="flex-1 text-center text-[9px] text-navy-600 leading-tight"
          >
            {c.stage}
          </span>
        ))}
      </div>
    </div>
  );
}
