"use client";

interface ProviderBadgeProps {
  generated_by?: {
    provider: string;
    tier: string;
    served_by?: string;
  };
}

export default function ProviderBadge({ generated_by }: ProviderBadgeProps) {
  if (!generated_by) return null;

  // When the configured model is overloaded, a request moves to a fallback
  // model rather than failing. A run answered partly by another model says
  // so, with the count per model, instead of claiming the configured one.
  const others = (generated_by.served_by || "")
    .split(", ")
    .filter((entry) => entry && !entry.startsWith(`${generated_by.provider} `));

  if (generated_by.tier !== "fallback" && others.length === 0) return null;

  return (
    <div className="bg-[#F7F0E2] border border-[#E4D5B5] rounded-lg px-4 py-3 text-sm">
      <div className="flex items-start gap-2">
        <span className="text-[#8A6420] font-medium shrink-0">&#9888;</span>
        <div>
          <p className="text-[#7A5B1E] font-medium">
            Part of this run was answered by a fallback model
          </p>
          <p className="text-[#8A6420] mt-0.5">
            <strong>{generated_by.provider}</strong> was overloaded during the
            run, so some requests were answered by other Gemini models (
            {generated_by.served_by}). Verdicts are computed from the document
            either way; the model writes the explanations and checks mechanism
            evidence.
          </p>
        </div>
      </div>
    </div>
  );
}
