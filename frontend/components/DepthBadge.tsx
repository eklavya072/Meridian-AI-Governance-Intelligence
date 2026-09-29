import palette from "@/lib/palette.json";
// Implementation depth is intentionally monochrome, not a rainbow: Coverage (Covered/
// Partial/Missing) already owns the site's three status hues (green/amber/
// red) — reusing them here would make Implementation depth read as a second coverage
// verdict instead of the distinct "how operational is it" axis it actually
// is. Same grey ramp as the StageHistogram gauge (DashboardCharts.tsx) for
// one consistent visual language: light grey = barely present, black =
// fully institutionalized — a weight/ink metaphor that fits the site's
// black+white+grey system instead of borrowing colors that mean something
// else.
const depthDot: Record<string, string> = {
  Unaddressed: palette.grey["500"], // grey.500 — barely present
  Emerging: palette.grey["600"], // grey.550
  Delegated: palette.grey["800"], // grey.700 — an owner or a duty, no regime yet
  Operationalized: palette.grey["900"], // grey.800
  Institutionalized: palette.black, // black — fully established
};

export default function DepthBadge({ level }: { level?: string | null }) {
  if (!level) return null;
  return (
    <span
      className="inline-flex items-center gap-2 text-sm font-semibold text-grey-950"
      title={`Implementation Depth: ${level}`}
    >
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ background: depthDot[level] || palette.grey["500"] }}
      />
      {level}
    </span>
  );
}
