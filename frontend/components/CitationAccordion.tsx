"use client";

import { useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { EASE, DUR, heightTransition } from "@/lib/motion";

/**
 * Shared closed-by-default citation accordion.
 *
 * One implementation of the "Show X (N sources)" expand/collapse pattern,
 * reused by the Module 1 Evidence sections and the Module 2 Grounding
 * Citations (both the Recommendations tier and the Fully Covered Best
 * Practices tier). Renders the toggle + the one-line quality summary
 * (source split / verification rate) without expanding, and reveals the
 * citation rows via the shared heightTransition token.
 *
 * The caller decides the empty state (this component renders nothing useful
 * when `total === 0` and simply does not render the toggle).
 */
export default function CitationAccordion({
  label,
  total,
  summary,
  children,
  className,
}: {
  /** Toggle wording: "Show {label} (N sources)" / "Hide {label}". */
  label: string;
  /** Number of real (chunk-backed) sources — shown as "(N sources)". */
  total: number;
  /** One-line quality summary shown collapsed, e.g. "3 document · 2 framework · 5/5 verified". */
  summary: string;
  /** Citation rows (and any group labels) revealed when open. */
  children: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  if (total === 0) return null;

  return (
    <div className={`border-t border-gray-100 pt-2 ${className ?? ""}`}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="pressable w-full flex items-center justify-between gap-3 py-1.5 text-left group"
      >
        <span className="text-sm font-semibold text-navy-950 group-hover:opacity-70 transition-opacity">
          {open ? `Hide ${label}` : `Show ${label} (${total} ${total === 1 ? "source" : "sources"})`}
        </span>
        <span className="flex items-center gap-2 shrink-0">
          {summary && <span className="text-xs font-medium text-navy-900">{summary}</span>}
          <motion.span
            animate={{ rotate: open ? 180 : 0 }}
            transition={{ duration: DUR.fast, ease: EASE.out }}
            className="text-navy-950 text-sm inline-block"
            aria-hidden
          >
            ▼
          </motion.span>
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="citation-content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={heightTransition}
            className="overflow-hidden"
          >
            <div className="pt-3 space-y-3">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
