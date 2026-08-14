"use client";

/**
 * RadarChart — a small dependency-free radar (spider) chart.
 *
 * The API mirrors the `@bklitui/ui/charts` reference so the usage stays a
 * drop-in for that package if it ever ships:
 *
 *   <RadarChart data={data} metrics={metrics} size={380}>
 *     <RadarGrid />
 *     <RadarAxis />
 *     <RadarLabels />
 *     <RadarArea index={0} showPoints />
 *   </RadarChart>
 *
 * The parent computes the geometry (centre, radius, per-axis angles) and
 * exposes it via context; each child renders one layer of the chart. Values
 * are 0–100 per metric; `RadarGrid` defaults to the three coverage tiers
 * (33 / 66 / 100) so vertices land exactly on a ring.
 *
 * Interaction & motion:
 *  - Creation: when the chart scrolls into view, each vertex flies out from
 *    the centre to its ring, then the outline draws itself in.
 *  - Hover: hovering a vertex grows the point, shows a soft ring + tooltip
 *    chip, darkens that axis spoke and label, and brightens the polygon.
 *    The polygon itself is hoverable too. All motion is gated on
 *    prefers-reduced-motion.
 */

import {
  createContext,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { EASE } from "@/lib/motion";
import { useInViewOnce } from "@/lib/useInViewOnce";

export interface RadarMetric {
  key: string;
  label: string;
}

export interface RadarDatum {
  label: string;
  color: string;
  values: Record<string, number>;
}

export interface RadarTooltip {
  label: string;
  color?: string;
}

interface RadarGeometry {
  cx: number;
  cy: number;
  radius: number;
  /** Angle (radians) of the axis for metric `index` — axis 0 points straight up. */
  angleFor: (index: number) => number;
  /** Point on the axis for metric `index` at `fraction` (0 = centre, 1 = outer ring). */
  pointFor: (metricIndex: number, fraction: number) => [number, number];
}

interface RadarContextValue {
  metrics: RadarMetric[];
  data: RadarDatum[];
  size: number;
  geometry: RadarGeometry;
  /** Index of the hovered metric, or -1 when the polygon itself is hovered, or null. */
  hoverIndex: number | null;
  setHoverIndex: (i: number | null) => void;
  /** True once the chart has scrolled into view — gates the creation animation. */
  entered: boolean;
}

const RadarContext = createContext<RadarContextValue | null>(null);

function useRadar(): RadarContextValue {
  const ctx = useContext(RadarContext);
  if (!ctx) {
    throw new Error("Radar child components must be rendered inside <RadarChart>.");
  }
  return ctx;
}

export function RadarChart({
  data,
  metrics,
  size = 300,
  ariaLabel = "Radar chart",
  children,
}: {
  data: RadarDatum[];
  metrics: RadarMetric[];
  size?: number;
  ariaLabel?: string;
  children?: ReactNode;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  // Creation-animation gate — shared hook (scroll/resize + poll, torn down
  // on fire; see lib/useInViewOnce.ts). Reduced-motion users get the final
  // chart immediately (useReducedMotion is `boolean | null` — coerce).
  const reduced = useReducedMotion();
  const svgRef = useRef<SVGSVGElement>(null);
  const inView = useInViewOnce(svgRef);
  const entered = reduced || inView;

  const cx = size / 2;
  const cy = size / 2;
  // ~27% of the viewBox for the polygon, the rest reserved for axis labels.
  const radius = size * 0.27;

  const geometry = useMemo<RadarGeometry>(() => {
    const count = Math.max(metrics.length, 1);
    const angleFor = (index: number) =>
      (-90 + (index * 360) / count) * (Math.PI / 180);
    const pointFor = (metricIndex: number, fraction: number): [number, number] => {
      const angle = angleFor(metricIndex);
      const f = Math.max(0, Math.min(1, fraction));
      return [
        cx + Math.cos(angle) * radius * f,
        cy + Math.sin(angle) * radius * f,
      ];
    };
    return { cx, cy, radius, angleFor, pointFor };
  }, [cx, cy, radius, metrics.length]);

  const value = useMemo<RadarContextValue>(
    () => ({ metrics, data, size, geometry, hoverIndex, setHoverIndex, entered }),
    [metrics, data, size, geometry, hoverIndex, entered]
  );

  return (
    <RadarContext.Provider value={value}>
      {/* max-w-full h-auto: the viewBox keeps the aspect ratio, so the chart
          scales down responsively on narrow screens instead of overflowing
          its card (the width/height attrs stay the *intended* size). */}
      <svg
        ref={svgRef}
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={ariaLabel}
        className="max-w-full h-auto"
      >
        {children}
      </svg>
    </RadarContext.Provider>
  );
}

/** Concentric polygon rings at the given levels (fractions of the radius). */
export function RadarGrid({ levels = [0.33, 0.66, 1] }: { levels?: number[] }) {
  const { metrics, geometry } = useRadar();
  const { pointFor } = geometry;

  // Grey ring tokens — the same values as globals.css grey-300 (#D4D4D4)
  // and teal-100 (#E5E5E5); the dark series colour comes from the datum.
  return (
    <g stroke="#D4D4D4" strokeWidth={1}>
      {levels.map((level, li) => {
        const points = metrics
          .map((_, mi) => pointFor(mi, level).map((v) => v.toFixed(2)).join(","))
          .join(" ");
        const isOuter = li === levels.length - 1;
        return (
          <polygon
            key={li}
            points={points}
            fill={isOuter ? "rgba(10, 10, 10, 0.015)" : "none"}
            strokeWidth={isOuter ? 1.25 : 1}
          />
        );
      })}
    </g>
  );
}

/** Spokes from the centre to each metric vertex. */
export function RadarAxis() {
  const { metrics, geometry, hoverIndex } = useRadar();
  const { cx, cy, pointFor } = geometry;

  return (
    <g>
      {metrics.map((m, i) => {
        const [x, y] = pointFor(i, 1);
        const isHover = hoverIndex === i;
        return (
          <line
            key={m.key}
            x1={cx}
            y1={cy}
            x2={x}
            y2={y}
            stroke={isHover ? "#0A0A0A" : "#E5E5E5"}
            strokeWidth={isHover ? 1.6 : 1}
            style={{
              transition: "stroke 150ms ease-out, stroke-width 150ms ease-out",
            }}
          />
        );
      })}
    </g>
  );
}

/** Metric labels placed just outside the outer ring, anchored per axis. */
export function RadarLabels({
  labelOffset = 26,
  fontSize = 10.5,
}: {
  labelOffset?: number;
  fontSize?: number;
}) {
  const { metrics, geometry, hoverIndex } = useRadar();
  const { cx, cy, radius, angleFor } = geometry;

  // Label grey = navy-600 (#737373) token; hovered label goes to the primary.
  return (
    <g fontSize={fontSize}>
      {metrics.map((m, i) => {
        const angle = angleFor(i);
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        const x = cx + cos * (radius + labelOffset);
        const y = cy + sin * (radius + labelOffset);
        // Anchor horizontally by the axis direction; keep the text vertically
        // centred on the axis line with dominantBaseline.
        const anchor = Math.abs(cos) < 0.35 ? "middle" : cos > 0 ? "start" : "end";
        const isHover = hoverIndex === i;
        return (
          <text
            key={m.key}
            x={x}
            y={y}
            textAnchor={anchor}
            dominantBaseline="middle"
            fill={isHover ? "#0A0A0A" : "#737373"}
            fontWeight={isHover ? 600 : 400}
            style={{
              fontFamily: "inherit",
              letterSpacing: "-0.01em",
              transition: "fill 150ms ease-out",
            }}
          >
            {m.label}
          </text>
        );
      })}
    </g>
  );
}

/** Filled polygon for one datum series, with scroll-triggered creation
 * animation and per-vertex hover feedback (grow, ring, tooltip chip). */
export function RadarArea({
  index = 0,
  showPoints = true,
  fillOpacity = 0.08,
  tooltip,
}: {
  index?: number;
  showPoints?: boolean;
  fillOpacity?: number;
  /** Optional per-vertex tooltip content: (value, metric) → { label, color? }. */
  tooltip?: (value: number, metric: RadarMetric) => RadarTooltip;
}) {
  const { metrics, data, size, geometry, hoverIndex, setHoverIndex, entered } =
    useRadar();
  const { cx, cy, pointFor, angleFor } = geometry;
  const datum = data[index];
  // The creation animation is driven by the `entered` flag from RadarChart
  // (set when the svg scrolls into view) via explicit `animate` values — not
  // variant propagation, which does not flow through the intermediate
  // per-vertex groups.
  if (!datum) return null;

  const targets = useMemo(
    () =>
      metrics.map((m, i) => {
        const raw = datum.values[m.key] ?? 0;
        const frac = Math.max(0, Math.min(100, raw)) / 100;
        const [x, y] = pointFor(i, frac);
        return { x, y, angle: angleFor(i) };
      }),
    [metrics, datum, pointFor, angleFor]
  );

  const path = useMemo(() => {
    const pts = metrics.map((m, i) => {
      const raw = datum.values[m.key] ?? 0;
      const frac = Math.max(0, Math.min(100, raw)) / 100;
      const [x, y] = pointFor(i, frac);
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    });
    return pts.join(" ") + " Z";
  }, [metrics, datum, pointFor]);

  // -1 = the polygon itself is hovered (brightens without a vertex tooltip);
  // a metric index = a vertex is hovered; null = nothing.
  const emphasized = hoverIndex !== null;

  return (
    <g>
      {/* The polygon — hoverable as a whole: onHoverStart sets -1 so the
          fill/stroke emphasis kicks in even when the pointer isn't on a
          vertex. When `entered` flips, pathLength draws the outline after a
          short beat (once the vertices have flown out). */}
      <motion.path
        d={path}
        fill={datum.color}
        stroke={datum.color}
        strokeLinejoin="round"
        initial={false}
        onHoverStart={() => setHoverIndex(-1)}
        onHoverEnd={() => setHoverIndex(null)}
        animate={{
          pathLength: entered ? 1 : 0,
          opacity: entered ? 1 : 0,
          fillOpacity: emphasized ? Math.min(0.22, fillOpacity + 0.1) : fillOpacity,
          strokeWidth: emphasized ? 2.4 : 1.8,
        }}
        transition={{
          pathLength: { delay: 0.45, duration: 0.95, ease: EASE.out },
          opacity: { duration: 0.35 },
          fillOpacity: { duration: 0.2, ease: EASE.out },
          strokeWidth: { duration: 0.2, ease: EASE.out },
        }}
      />

      {showPoints &&
        targets.map((t, i) => {
          const metric = metrics[i];
          const tip = tooltip ? tooltip(datum.values[metric.key] ?? 0, metric) : null;
          const isHover = hoverIndex === i;

          // Tooltip chip geometry — centred on the vertex, flipped below the
          // point when the vertex sits in the top half of the chart.
          const labelLen = metric.label.length;
          const tipLen = tip ? tip.label.length : 0;
          const chipW = Math.max(labelLen, tipLen) * 5.6 + 24;
          const chipH = 32;
          const chipX = Math.max(
            chipW / 2 + 4,
            Math.min(size - chipW / 2 - 4, t.x)
          );
          const showBelow = Math.sin(t.angle) >= -0.25;
          const chipY = showBelow ? t.y + 18 : t.y - 18 - chipH;

          return (
            <motion.g
              key={metric.key}
              onHoverStart={() => setHoverIndex(i)}
              onHoverEnd={() => setHoverIndex(null)}
              style={{ cursor: "pointer" }}
            >
              {/* Visible point — flies from the centre to its ring (via x/y
                  transform offsets so it lands exactly on the target), then
                  grows on hover. */}
              <motion.circle
                cx={t.x}
                cy={t.y}
                r={isHover ? 5 : 3}
                fill="#FFFFFF"
                stroke={datum.color}
                strokeWidth={1.6}
                initial={false}
                animate={{
                  x: entered ? 0 : cx - t.x,
                  y: entered ? 0 : cy - t.y,
                  opacity: entered ? 1 : 0,
                }}
                transition={{
                  x: { delay: 0.12 + i * 0.06, duration: 0.55, ease: EASE.out },
                  y: { delay: 0.12 + i * 0.06, duration: 0.55, ease: EASE.out },
                  opacity: { delay: 0.12 + i * 0.06, duration: 0.45 },
                }}
                style={{ transition: "r 150ms cubic-bezier(0.22, 1, 0.36, 1)" }}
              />
              {/* Soft ring that fades in around the hovered vertex — plain
                  CSS opacity transition (framer's attribute animation warned
                  about animating opacity from `undefined`). */}
              <circle
                cx={t.x}
                cy={t.y}
                r={9}
                fill="none"
                stroke={datum.color}
                strokeWidth={1.2}
                opacity={isHover ? 0.45 : 0}
                style={{ transition: "opacity 200ms cubic-bezier(0.22, 1, 0.36, 1)" }}
                pointerEvents="none"
              />
              {/* Invisible hit target — generous, keeps the 3px point easy
                  to hover without a steady hand. Focusable so keyboard users
                  get the same per-dimension feedback (focus drives the same
                  hoverIndex, so the ring doubles as the focus ring). */}
              <circle
                cx={t.x}
                cy={t.y}
                r={13}
                fill="transparent"
                tabIndex={0}
                role="button"
                aria-label={`${metric.label}${tip ? ` — ${tip.label}` : ""}`}
                onFocus={() => setHoverIndex(i)}
                onBlur={() => setHoverIndex(null)}
                className="focus:outline-none"
              />

              {/* Tooltip chip — dark glass pill echoing the nav pill. */}
              <AnimatePresence>
              {tip && isHover && (
                <motion.g
                  key="tooltip"
                  initial={{ opacity: 0, y: 5 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 3 }}
                  transition={{ duration: 0.15, ease: EASE.out }}
                  pointerEvents="none"
                >
                  <rect
                    x={chipX - chipW / 2}
                    y={chipY}
                    width={chipW}
                    height={chipH}
                    rx={7}
                    fill="rgba(10, 10, 10, 0.92)"
                    stroke="rgba(255, 255, 255, 0.14)"
                  />
                  <text
                    x={chipX - chipW / 2 + 12}
                    y={chipY + 14}
                    fontSize={10}
                    fontWeight={600}
                    fill="#FFFFFF"
                  >
                    {metric.label}
                  </text>
                  {tip.color ? (
                    <circle
                      cx={chipX - chipW / 2 + 14}
                      cy={chipY + 25}
                      r={2.5}
                      fill={tip.color}
                    />
                  ) : null}
                  <text
                    x={chipX - chipW / 2 + (tip.color ? 22 : 12)}
                    y={chipY + 25}
                    fontSize={9}
                    fill="rgba(255, 255, 255, 0.8)"
                  >
                    {tip.label}
                  </text>
                </motion.g>
              )}
              </AnimatePresence>
            </motion.g>
          );
        })}
    </g>
  );
}
