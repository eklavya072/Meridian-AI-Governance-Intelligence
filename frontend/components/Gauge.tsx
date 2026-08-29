"use client";

/**
 * Gauge — a dependency-free radial gauge matching the @bklitui/ui/charts
 * <Gauge /> API shape (that package 404s on npm, so this is the native
 * replacement; the props stay drop-in compatible).
 *
 * A single smooth 260° speedometer arc (the classic gauge style): a faint
 * full track with the value arc sweeping over it when the gauge scrolls into
 * view, and the centre number counting up with it. The value arc fills only
 * `value`% of the track — a score of 65.6 draws 65.6% of the 260° sweep,
 * not the whole gauge. Strictly monochrome to fit the muted maturity block.
 * Reduced-motion users get the final state instantly, no count-up.
 *
 *   <Gauge
 *     value={66}                 // 0-100, drives the arc fill
 *     centerValue={428_000}      // number in the middle (counts up)
 *     defaultLabel="ARR run rate"
 *     inactiveFillOpacity={0.08} // faintness of the background track
 *     useGradient
 *   />
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { animate, motion, useReducedMotion } from "motion/react";
import { EASE } from "@/lib/motion";
import { useInViewOnce } from "@/lib/useInViewOnce";

// Gauge geometry: start bottom-left (230° clockwise from top), sweep 260°
// clockwise through the top to bottom-right (130°) — the classic
// speedometer arc. 230°/130° is symmetric about 12 o'clock: the left and
// right halves each sweep 130°, so the arc reads perfectly balanced (a 225°
// start put the midpoint at 355° and made one side visibly longer).
const START = 230;
const SWEEP = 260;

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

/** Point on a circle. `deg` is clockwise from 12 o'clock (SVG y-down). */
function pointOn(cx: number, cy: number, r: number, deg: number) {
  const rad = (deg * Math.PI) / 180;
  return { x: cx + r * Math.sin(rad), y: cy - r * Math.cos(rad) };
}

/** Sampled arc path — smooth at 2° steps, works with framer's pathLength. */
function arcPath(cx: number, cy: number, r: number, startDeg: number, sweepDeg: number) {
  const step = 2;
  const n = Math.max(1, Math.ceil(sweepDeg / step));
  const pts: string[] = [];
  for (let i = 0; i <= n; i++) {
    const p = pointOn(cx, cy, r, startDeg + (sweepDeg * i) / n);
    pts.push(`${p.x.toFixed(2)} ${p.y.toFixed(2)}`);
  }
  return `M ${pts.join(" L ")}`;
}

export default function Gauge({
  value,
  centerValue,
  defaultLabel,
  size = 180,
  inactiveFillOpacity = 0.08,
  useGradient = false,
  formatOptions,
  ariaLabel = "Gauge",
}: {
  value: number;
  centerValue?: string | number;
  defaultLabel?: string;
  size?: number;
  inactiveFillOpacity?: number;
  useGradient?: boolean;
  formatOptions?: Intl.NumberFormatOptions;
  ariaLabel?: string;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const entered = useInViewOnce(svgRef);
  const reduced = useReducedMotion() ?? false;

  const v = clamp(value, 0, 100);
  const cx = size / 2;
  const cy = size / 2;
  // 14px stroke centered on the radius: outer edge (radius + 7) must stay
  // inside the viewBox (size/2), or the arc gets flat-clipped at the
  // cardinals.
  const radius = size / 2 - 12;

  // Count-up target: the numeric centerValue when given, else the raw value.
  const numericTarget = typeof centerValue === "number" ? centerValue : v;
  const [display, setDisplay] = useState(reduced ? numericTarget : 0);

  useEffect(() => {
    if (reduced) {
      setDisplay(numericTarget);
      return;
    }
    if (!entered) return;
    const controls = animate(0, numericTarget, {
      duration: 1.1,
      ease: EASE.out,
      onUpdate: (latest) => setDisplay(latest),
    });
    return () => controls.stop();
  }, [entered, numericTarget, reduced]);

  const shown = useMemo(() => {
    if (formatOptions) {
      return new Intl.NumberFormat(undefined, formatOptions).format(display);
    }
    if (typeof centerValue === "number") return display.toFixed(1);
    return String(centerValue ?? Math.round(display));
  }, [formatOptions, centerValue, display]);

  // A word ("Institutionalized") needs a different size from a number ("92.9").
  // Scaled from the rendered string rather than exposed as a prop, so a caller
  // switching a gauge from a score to a label cannot forget to resize it.
  const centerFontSize =
    shown.length > 14 ? 12 : shown.length > 11 ? 14 : shown.length > 7 ? 18 : 26;

  // The value arc spans only value% of the track — the gradient must end at
  // the value arc's actual endpoint (not the full sweep) so the dark end of
  // the ramp lands where the arc stops.
  const valueSweep = (v / 100) * SWEEP;
  const gradId = useId();
  const p0 = pointOn(cx, cy, radius, START);
  const p1 = pointOn(cx, cy, radius, START + valueSweep);

  return (
    <svg
      ref={svgRef}
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={ariaLabel}
      className="max-w-full h-auto"
    >
      <defs>
        {useGradient && (
          <linearGradient
            id={gradId}
            gradientUnits="userSpaceOnUse"
            x1={p0.x}
            y1={p0.y}
            x2={p1.x}
            y2={p1.y}
          >
            <stop offset="0%" stopColor="#737373" />
            <stop offset="100%" stopColor="#0A0A0A" />
          </linearGradient>
        )}
      </defs>

      {/* Track — the old gauge's full background arc */}
      <path
        d={arcPath(cx, cy, radius, START, SWEEP)}
        fill="none"
        stroke="#0A0A0A"
        strokeOpacity={inactiveFillOpacity}
        strokeWidth={14}
        strokeLinecap="round"
      />

      {/* Value arc — fills only value% of the track; sweeps in via pathLength
          on reveal. The path itself spans valueSweep degrees, so animating
          pathLength 0→1 draws exactly that fraction of the gauge. Hidden
          entirely when the score is 0 (a degenerate zero-length arc would
          render a stray dot from the round cap). */}
      {v > 0 && (
        <motion.path
          d={arcPath(cx, cy, radius, START, valueSweep)}
          fill="none"
          stroke={useGradient ? `url(#${gradId})` : "#262626"}
          strokeWidth={14}
          strokeLinecap="round"
          pathLength={1}
          initial={entered ? false : { pathLength: 0, opacity: 0 }}
          animate={
            entered
              ? { pathLength: 1, opacity: 1 }
              : { pathLength: 0, opacity: 0 }
          }
          transition={{
            pathLength: { delay: 0.15, duration: 0.9, ease: EASE.out },
            opacity: { duration: 0.3, ease: EASE.out },
          }}
        />
      )}

      {/* Centre readout — counts up with the arc */}
      <g pointerEvents="none">
        <text
          x={cx}
          y={cy - 2}
          textAnchor="middle"
          fontSize={centerFontSize}
          fontWeight={700}
          fill="#0A0A0A"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {shown}
        </text>
        {defaultLabel && (
          <text
            x={cx}
            y={cy + 20}
            textAnchor="middle"
            fontSize={10}
            fill="#737373"
            letterSpacing="0.04em"
            style={{ textTransform: "uppercase", fontFamily: "inherit" }}
          >
            {defaultLabel}
          </text>
        )}
      </g>
    </svg>
  );
}
