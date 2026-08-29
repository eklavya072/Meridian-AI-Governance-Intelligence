// Maturity is intentionally monochrome, not a rainbow: Coverage (Covered/
// Partial/Missing) already owns the site's three status hues (green/amber/
// red) — reusing them here would make Maturity read as a second coverage
// verdict instead of the distinct "how operational is it" axis it actually
// is. Same grey ramp as the StageHistogram gauge (DashboardCharts.tsx) for
// one consistent visual language: light grey = barely present, black =
// fully institutionalized — a weight/ink metaphor that fits the site's
// black+white+grey system instead of borrowing colors that mean something
// else.
const maturityDot: Record<string, string> = {
  Unaddressed: "#8A8A8A", // grey.500 — barely present
  Emerging: "#6E6E6E", // grey.550
  Delegated: "#4A4A4A", // grey.700 — an owner or a duty, no regime yet
  Operationalized: "#262626", // grey.800
  Institutionalized: "#0A0A0A", // black — fully established
};

export default function MaturityBadge({ level }: { level?: string | null }) {
  if (!level) return null;
  return (
    <span
      className="inline-flex items-center gap-2 text-sm font-semibold text-navy-950"
      title={`Governance Maturity: ${level}`}
    >
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ background: maturityDot[level] || "#8A8A8A" }}
      />
      {level}
    </span>
  );
}
