"use client";

/**
 * PieChart — a small dependency-free donut chart with linked hover.
 *
 * API follows the interactive-pie reference (hoveredIndex lifted to the
 * caller, children react to it), generalised for this app:
 *
 *   const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
 *
 *   <PieChart
 *     data={slices}
 *     hoveredIndex={hoveredIndex}
 *     onHoverChange={setHoveredIndex}
 *     innerRadius={56}
 *     size={180}
 *   >
 *     {slices.map((_, i) => <PieSlice key={i} index={i} />)}
 *     <PieCenter defaultValue={8} defaultLabel="dimensions" />
 *   </PieChart>
 *   <PieLegend
 *     items={legendItems}
 *     hoveredIndex={hoveredIndex}
 *     onHoverChange={setHoveredIndex}
 *   />
 *
 * Hovering a slice pops it out and swaps the centre readout; hovering a
 * legend row highlights the matching slice and vice versa. The reveal (slices
 * blooming in) fires when the chart scrolls into view.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AnimatePresence, motion } from "motion/react";
import { EASE } from "@/lib/motion";
import { useInViewOnce } from "@/lib/useInViewOnce";

export interface PieDatum {
  label: string;
  value: number;
  color: string;
}

export interface PieLegendItem {
  label: string;
  color: string;
  value: number;
}

interface PieGeometry {
  cx: number;
  cy: number;
  outerRadius: number;
  innerRadius: number;
  /** Angle (radians) at the start of slice `i` — 0 = top, clockwise. */
  startAngleFor: (i: number) => number;
  endAngleFor: (i: number) => number;
  midAngleFor: (i: number) => number;
  /** Full donut-annulus path for slice `i`; `expand` widens the outer radius. */
  pathFor: (i: number, expand: boolean) => string;
}

interface PieContextValue {
  data: PieDatum[];
  size: number;
  hoveredIndex: number | null;
  setHoveredIndex: (i: number | null) => void;
  g: PieGeometry;
  entered: boolean;
}

const PieContext = createContext<PieContextValue | null>(null);

function usePie(): PieContextValue {
  const ctx = useContext(PieContext);
  if (!ctx) {
    throw new Error("PieChart children must be rendered inside <PieChart>.");
  }
  return ctx;
}

// ~2° gap between slices (0 when there's a single ring, e.g. the empty state).
const PAD = 0.035;

function f(n: number): string {
  return n.toFixed(2);
}

export function PieChart({
  data,
  hoveredIndex,
  onHoverChange,
  innerRadius = 52,
  size = 180,
  ariaLabel = "Pie chart",
  children,
}: {
  data: PieDatum[];
  hoveredIndex: number | null;
  onHoverChange: (i: number | null) => void;
  innerRadius?: number;
  size?: number;
  ariaLabel?: string;
  children?: ReactNode;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const entered = useInViewOnce(svgRef);
  const cx = size / 2;
  const cy = size / 2;
  const outerRadius = size / 2 - 10;
  const total = data.reduce((sum, d) => sum + Math.max(0, d.value), 0);

  const g = useMemo<PieGeometry>(() => {
    const count = data.length;
    const pad = count <= 1 ? 0 : PAD;
    const sweep = (value: number) =>
      total > 0 ? (Math.max(0, value) / total) * Math.PI * 2 : 0;

    const startAngleFor = (i: number) => {
      let a = -Math.PI / 2; // 0 = top, angles increase clockwise
      for (let k = 0; k < i; k++) a += sweep(data[k].value);
      return a + pad / 2;
    };
    const endAngleFor = (i: number) =>
      startAngleFor(i) + Math.max(sweep(data[i].value) - pad, 0.0001);
    const midAngleFor = (i: number) =>
      (startAngleFor(i) + endAngleFor(i)) / 2;

    const pathFor = (i: number, expand: boolean): string => {
      const a0 = startAngleFor(i);
      const a1 = endAngleFor(i);
      const R = outerRadius * (expand ? 1.06 : 1);
      const r = innerRadius;
      // Full ring when this slice alone accounts for the whole circle — the
      // zero-state placeholder, or a single tier holding every dimension even
      // when the data array has zero-valued siblings.
      const full =
        sweep(data[i].value) >= Math.PI * 2 - 1e-6 &&
        data.every((d, k) => k === i || d.value <= 0);
      if (full) {
        // A single slice spans the whole circle. A 2π arc from a point to
        // itself is degenerate (SVG renders nothing), so draw each radius as
        // two half-circle arcs — outer clockwise, inner counter-clockwise —
        // which punches the hole under the nonzero fill rule. This is the
        // zero-state "no data" ring path.
        return [
          `M ${f(cx)} ${f(cy - R)}`,
          `A ${R} ${R} 0 1 1 ${f(cx)} ${f(cy + R)}`,
          `A ${R} ${R} 0 1 1 ${f(cx)} ${f(cy - R)}`,
          `M ${f(cx)} ${f(cy - r)}`,
          `A ${r} ${r} 0 1 0 ${f(cx)} ${f(cy + r)}`,
          `A ${r} ${r} 0 1 0 ${f(cx)} ${f(cy - r)}`,
          "Z",
        ].join(" ");
      }
      // One continuous subpath: outer arc clockwise, a radial line inward to
      // the inner radius, the inner arc back counter-clockwise, then Z. A
      // single subpath is critical — emitting a stray M between the arcs
      // splits the path, and the SVG fill rule implicitly closes each open
      // piece with a chord, which fills the whole circle (covering the hole
      // and making the centre hit-test to a slice). Under the nonzero fill
      // rule, the opposed windings (outer clockwise, inner counter-clockwise)
      // punch out the donut hole.
      const pO0 = [cx + R * Math.sin(a0), cy - R * Math.cos(a0)];
      const pO1 = [cx + R * Math.sin(a1), cy - R * Math.cos(a1)];
      const pI1 = [cx + r * Math.sin(a1), cy - r * Math.cos(a1)];
      const pI0 = [cx + r * Math.sin(a0), cy - r * Math.cos(a0)];
      const large = a1 - a0 > Math.PI ? 1 : 0;
      return (
        `M ${f(pO0[0])} ${f(pO0[1])} ` +
        `A ${R} ${R} 0 ${large} 1 ${f(pO1[0])} ${f(pO1[1])} ` +
        `L ${f(pI1[0])} ${f(pI1[1])} ` +
        `A ${r} ${r} 0 ${large} 0 ${f(pI0[0])} ${f(pI0[1])} Z`
      );
    };

    return { cx, cy, outerRadius, innerRadius, startAngleFor, endAngleFor, midAngleFor, pathFor };
  }, [data, total, cx, cy, outerRadius, innerRadius]);

  const value = useMemo<PieContextValue>(
    () => ({ data, size, hoveredIndex, setHoveredIndex: onHoverChange, g, entered }),
    [data, size, hoveredIndex, onHoverChange, g, entered]
  );

  return (
    <PieContext.Provider value={value}>
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
    </PieContext.Provider>
  );
}

/** One donut slice. Pops out + brightens on hover/focus; renders nothing for
 * zero-valued slices. */
export function PieSlice({ index }: { index: number }) {
  const { data, hoveredIndex, setHoveredIndex, g, entered } = usePie();
  const datum = data[index];
  const isHover = hoveredIndex === index;
  const dimmed = hoveredIndex !== null && !isHover;
  if (!datum || datum.value <= 0) return null;

  const mid = g.midAngleFor(index);
  // Pop-out: nudge along the slice's mid-angle.
  const dx = 3.5 * Math.sin(mid);
  const dy = -3.5 * Math.cos(mid);

  return (
    <motion.path
      d={g.pathFor(index, isHover)}
      fill={datum.color}
      stroke="rgba(255, 255, 255, 0.65)"
      strokeWidth={1}
      tabIndex={0}
      role="button"
      aria-label={`${datum.label}: ${datum.value}`}
      onHoverStart={() => setHoveredIndex(index)}
      onHoverEnd={() => setHoveredIndex(null)}
      onFocus={() => setHoveredIndex(index)}
      onBlur={() => setHoveredIndex(null)}
      initial={entered ? false : { opacity: 0, scale: 0.85 }}
      animate={{
        opacity: dimmed ? 0.4 : 1,
        scale: entered ? 1 : 0.85,
        x: isHover ? dx : 0,
        y: isHover ? dy : 0,
      }}
      transition={{
        opacity: { duration: 0.2, ease: EASE.out },
        scale: { delay: index * 0.07, duration: 0.5, ease: EASE.out },
        x: { duration: 0.2, ease: EASE.out },
        y: { duration: 0.2, ease: EASE.out },
      }}
      style={{
        transformBox: "fill-box",
        transformOrigin: "center",
        cursor: "pointer",
      }}
    />
  );
}

/** Centre readout — the hovered slice's value + label, else the default.
 *
 * The centre is a clean white plate (with a hairline ring so it reads as a
 * deliberate element even on a white card). When the value changes — e.g.
 * 8 dimensions → the 4 Fully Covered on hover — the number ticks down (or
 * up) through the integers very fast, like an odometer.
 */
export function PieCenter({
  defaultValue = 0,
  defaultLabel = "",
}: {
  defaultValue?: number;
  defaultLabel?: string;
}) {
  const { data, hoveredIndex, g } = usePie();
  const hovered = hoveredIndex !== null ? data[hoveredIndex] : null;
  const target = hovered ? hovered.value : defaultValue;
  const label = hovered ? hovered.label : defaultLabel;

  const [display, setDisplay] = useState(target);
  const displayRef = useRef(target);

  // Odometer ticker: step through EVERY integer from the current value to
  // the new one, one per ~55ms — 8 → 7 → 6 → 5 → 4 in ~220ms. A time-based
  // rAF interpolation rounds through the same digits but at 0.18s total it
  // collapses on throttled displays (and reads as a blur even at 60fps);
  // stepping each integer explicitly is deterministic everywhere and reads
  // as a fast mechanical odometer. A plain interval (rather than motion's
  // animate) so an interruption mid-tick — a hover flicker while the slice
  // pop shifts it under the pointer — always resumes from the current value
  // toward the new target; it can never sit on a stale intermediate number.
  useEffect(() => {
    const from = displayRef.current;
    const delta = target - from;
    if (delta === 0) return;
    const dir = Math.sign(delta);
    const steps = Math.abs(delta);
    let i = 0;
    const iv = window.setInterval(() => {
      i += 1;
      const v = from + dir * Math.min(i, steps);
      displayRef.current = v;
      setDisplay(v);
      if (i >= steps) window.clearInterval(iv);
    }, 55);
    return () => window.clearInterval(iv);
  }, [target]);

  return (
    <g pointerEvents="none">
      {/* White centre plate — sits over the hole so the readout is always on
          pure white regardless of what's behind the chart. */}
      <circle
        cx={g.cx}
        cy={g.cy}
        r={g.innerRadius + 2}
        fill="#FFFFFF"
        stroke="rgba(10, 10, 10, 0.07)"
        strokeWidth={1}
      />
      {/* Number — deliberately NOT inside the label-swap animation. When the
          group was keyed by label with mode="wait", the old label faded out
          for 150ms before the new group mounted, so the ~200ms odometer tick
          ran entirely behind the fade and was never visible. The number is
          always mounted; only the label below swaps. */}
      <text
        x={g.cx}
        y={g.cy - 1}
        textAnchor="middle"
        fontSize={26}
        fontWeight={700}
        fill="#0A0A0A"
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        {display}
      </text>
      <AnimatePresence initial={false}>
        <motion.g
          key={hovered ? hovered.label : "default"}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.12, ease: EASE.out }}
        >
          <text
            x={g.cx}
            y={g.cy + 19}
            textAnchor="middle"
            fontSize={10}
            fill="#737373"
            letterSpacing="0.04em"
            style={{ textTransform: "uppercase", fontFamily: "inherit" }}
          >
            {label}
          </text>
        </motion.g>
      </AnimatePresence>
    </g>
  );
}

/** Legend rows linked to the chart — hovering a row highlights its slice. */
export function PieLegend({
  items,
  hoveredIndex,
  onHoverChange,
  className = "",
}: {
  items: PieLegendItem[];
  hoveredIndex: number | null;
  onHoverChange: (i: number | null) => void;
  className?: string;
}) {
  return (
    <div
      className={`grid grid-cols-2 gap-x-4 gap-y-1 mt-3 text-xs w-full max-w-[230px] ${className}`}
    >
      {items.map((item, i) => {
        const isHover = hoveredIndex === i;
        return (
          <motion.button
            key={item.label}
            type="button"
            onHoverStart={() => onHoverChange(i)}
            onHoverEnd={() => onHoverChange(null)}
            onFocus={() => onHoverChange(i)}
            onBlur={() => onHoverChange(null)}
            className={`flex items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition-colors ${
              isHover ? "bg-[#F0F0F0]" : "hover:bg-[#FAFAFA]"
            }`}
          >
            <span
              className="w-2 h-2 rounded-full shrink-0 transition-transform duration-200"
              style={{ background: item.color, transform: isHover ? "scale(1.3)" : "scale(1)" }}
            />
            <span
              className={`truncate transition-colors ${
                isHover ? "text-navy-950 font-semibold" : "text-navy-600"
              }`}
            >
              {item.label}
            </span>
            <span
              className={`ml-auto tabular-nums ${
                isHover ? "text-navy-950 font-bold" : "text-navy-950 font-semibold"
              }`}
            >
              {item.value}
            </span>
          </motion.button>
        );
      })}
    </div>
  );
}
