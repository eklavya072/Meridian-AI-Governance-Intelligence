/**
 * MeridianMark — the brand symbol.
 *
 * "THE CULMINATION" — an abstract surveyor's instrument, drawn as a
 * meridian at the moment of measurement:
 *
 *  · GRADUATED DOME — the arc of the meridian standing on the standard
 *    line: the whole field of policy being surveyed. The name itself
 *    comes from the moment a reference crosses the meridian — the point
 *    of culmination.
 *  · EIGHT DIMENSION TICKS — the eight locked governance dimensions,
 *    inscribed on the dome like sextant graduations, all pointing at the
 *    single point of assessment: each policy is read against all eight
 *    at once.
 *  · MERIDIAN REFERENCE AXIS — the bold vertical line rising from the
 *    standard to the dome's apex: the one true line every policy is
 *    measured against.
 *  · PIVOT POINT — where the axis crosses the standard line and the dome
 *    is centered: the exact point of assessment.
 *  · BENCHMARK BASELINE — the ground line of evidence the instrument
 *    stands on.
 *  · PLUMB DIAMOND — the surveyor's weight hanging on true vertical:
 *    grounded, evidence-anchored truth. "At its meridian" — maximum
 *    precision, the height of the assessment.
 *
 * The meaning folds in four layers: the meridian (origin and namesake),
 * the eight ticks (dimensions), the axis (the standard), and the plumb
 * (evidence). Stroke-based and currentColor, so it inherits white on the
 * dark landing and navy/black on light surfaces. Optically centered in
 * the viewBox, so it aligns cleanly with text in the navbar; renders
 * crisp at favicon size (16px) and strong at hero size (80px+).
 */
export default function MeridianMark({
  size = 24,
  className = "",
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      {/* Graduated dome — the arc of the meridian standing on the standard */}
      <path d="M 6 40 A 26 26 0 0 1 58 40" strokeWidth={2.5} />

      {/* Eight dimension ticks — sextant graduations, pointing at the pivot */}
      <g strokeWidth={1.8} strokeOpacity={0.55}>
        <path d="M 7.57 31.11 L 11.33 32.48" />
        <path d="M 12.08 23.29 L 15.15 25.86" />
        <path d="M 19 17.48 L 21 20.95" />
        <path d="M 27.49 14.39 L 28.18 18.33" />
        <path d="M 36.51 14.39 L 35.82 18.33" />
        <path d="M 45 17.48 L 43 20.95" />
        <path d="M 51.92 23.29 L 48.85 25.86" />
        <path d="M 56.43 31.11 L 52.67 32.48" />
      </g>

      {/* Benchmark baseline — the ground line of evidence */}
      <path d="M 12 40 L 52 40" strokeWidth={2} strokeOpacity={0.75} />

      {/* Meridian reference axis — apex to plumb, crossing the standard */}
      <path d="M 32 14 L 32 44" strokeWidth={3.5} />

      {/* Pivot point — where the axis crosses the standard */}
      <circle cx="32" cy="40" r="2" fill="currentColor" stroke="none" />

      {/* Plumb diamond — evidence-weighted truth on true vertical */}
      <path
        d="M 32 44 L 35.4 46.3 L 32 48.6 L 28.6 46.3 Z"
        fill="currentColor"
        stroke="none"
      />
    </svg>
  );
}
