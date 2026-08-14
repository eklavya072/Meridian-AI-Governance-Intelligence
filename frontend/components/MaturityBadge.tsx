// Logical maturity color ramp — every level carries a real semantic color
// (red → amber → green), never grey: Ad Hoc is the weakest tier, Optimized
// the strongest, so the dot reads like a progress signal at a glance.
const maturityDot: Record<string, string> = {
  "Ad Hoc": "#A8483F", // muted red — weakest
  Developing: "#B07E2B", // muted amber
  Defined: "#3F7A52", // muted green
  Managed: "#3F7A52", // muted green
  Optimized: "#3F7A52", // muted forest green — strongest
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
        style={{ background: maturityDot[level] || "#A8483F" }}
      />
      {level}
    </span>
  );
}
