const statusConfig: Record<
  string,
  { label: string; badge: string; dot: string; active: boolean; bar?: string }
> = {
  queued: {
    label: "Queued",
    badge: "bg-status-amber-tint text-status-amber-ink",
    dot: "bg-status-amber",
    active: true,
    bar: "text-status-amber",
  },
  processing: {
    label: "Processing",
    badge: "bg-grey-100 text-grey-800",
    dot: "bg-grey-500",
    active: true,
    bar: "text-grey-600",
  },
  generating_report: {
    label: "Generating Report",
    badge: "bg-grey-100 text-grey-800",
    dot: "bg-grey-500",
    active: true,
    bar: "text-grey-600",
  },
  complete: {
    label: "Complete",
    badge: "bg-status-green-tint text-status-green",
    dot: "bg-status-green",
    active: false,
  },
  error: {
    label: "Error",
    badge: "bg-status-red-tint text-status-red",
    dot: "bg-status-red",
    active: false,
  },
  chat_only: {
    label: "Document only",
    badge: "bg-grey-100 text-grey-800",
    dot: "bg-grey-400",
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
    badge: "bg-grey-50 text-grey-900",
    dot: "bg-grey-400",
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
          className={`w-full h-1 rounded-full progress-indeterminate bg-grey-100 ${cfg.bar}`}
        />
      )}
    </div>
  );
}
