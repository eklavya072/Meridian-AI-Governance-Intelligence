const statusConfig: Record<
  string,
  { label: string; badge: string; dot: string; active: boolean; bar?: string }
> = {
  queued: {
    label: "Queued",
    badge: "bg-[#F7F0E2] text-[#7A5B1E]",
    dot: "bg-[#B07E2B]",
    active: true,
    bar: "text-[#B07E2B]",
  },
  processing: {
    label: "Processing",
    badge: "bg-navy-100 text-navy-800",
    dot: "bg-navy-500",
    active: true,
    bar: "text-navy-500",
  },
  generating_report: {
    label: "Generating Report",
    badge: "bg-navy-100 text-navy-800",
    dot: "bg-navy-500",
    active: true,
    bar: "text-navy-500",
  },
  complete: {
    label: "Complete",
    badge: "bg-[#EAF1EC] text-[#3F7A52]",
    dot: "bg-[#3F7A52]",
    active: false,
  },
  error: {
    label: "Error",
    badge: "bg-[#F6ECEB] text-[#A8483F]",
    dot: "bg-[#A8483F]",
    active: false,
  },
  chat_only: {
    label: "Document only",
    badge: "bg-navy-100 text-navy-800",
    dot: "bg-navy-400",
    active: false,
  },
};

export default function StatusBadge({
  status,
  showBar,
}: {
  status: string;
  showBar?: boolean;
}) {
  const cfg = statusConfig[status.toLowerCase()] || {
    label: status,
    badge: "bg-gray-100 text-gray-800",
    dot: "bg-gray-400",
    active: false,
  };

  return (
    <div className="inline-flex flex-col items-start gap-1.5">
      <span
        className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${cfg.badge}`}
      >
        {/* Processing dot: breathing pulse — communicates "this stage is live".
            Complete/error get a static dot; nothing animates without a reason. */}
        <span
          className={`w-1.5 h-1.5 rounded-full ${cfg.dot} ${cfg.active ? "status-dot" : ""}`}
        />
        {cfg.label}
      </span>
      {/* Pipeline stages (queued → processing → generating report) get an
          indeterminate progress bar — the user is waiting, so the motion
          earns its place by showing the run is alive. */}
      {showBar && cfg.active && cfg.bar && (
        <div
          className={`w-full h-1 rounded-full progress-indeterminate bg-gray-200 ${cfg.bar}`}
        />
      )}
    </div>
  );
}
