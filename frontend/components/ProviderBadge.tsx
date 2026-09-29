"use client";

interface ProviderBadgeProps {
  generated_by?: {
    provider: string;
    tier: string;
  };
}

export default function ProviderBadge({ generated_by }: ProviderBadgeProps) {
  if (!generated_by) return null;

  const isFallback = generated_by.tier === "fallback";

  if (!isFallback) return null;

  return (
    <div className="bg-status-amber-tint border border-status-amber-line rounded-lg px-4 py-3 text-sm">
      <div className="flex items-start gap-2">
        <span className="text-status-amber-ink font-medium shrink-0">&#9888;</span>
        <div>
          <p className="text-status-amber-ink font-medium">
            Generated with reduced-capacity model
          </p>
          <p className="text-status-amber-ink mt-0.5">
            This analysis was produced by{" "}
            <strong>{generated_by.provider}</strong> (
            {generated_by.tier} tier).{" "}
            Recommend re-running with full analysis when the primary provider
            is available.
          </p>
        </div>
      </div>
    </div>
  );
}
