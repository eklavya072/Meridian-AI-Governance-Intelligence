"use client";

import type { ReactNode } from "react";
import { motion } from "motion/react";
import { EASE } from "@/lib/motion";

/** Every page's heading, in one layout, each with its own entrance.
 *
 *  `title` is the heading's text, always. `animated` replaces it inside the
 *  <h1> with a text effect that is still real text (InkReveal,
 *  EditorialReveal, SplitText). `art` is for an effect drawn on a canvas
 *  (WarpText): the <h1> keeps the text for screen readers and search, and
 *  the drawing is hidden from them.
 *
 *  `aside` sits at the right (the Analysis page's Ask AI button) and is
 *  mirrored by an empty column on the left so the title stays centred.
 *  Below `sm` there is no room for either column, so it drops under the
 *  subtitle instead.
 *  `compact` is the left-aligned, smaller form for the Auditor, whose page
 *  is a full-height chat rather than a document. */
export default function PageHeader({
  title,
  animated,
  art,
  subtitle,
  aside,
  compact = false,
}: {
  title: string;
  animated?: ReactNode;
  art?: ReactNode;
  subtitle?: ReactNode;
  aside?: ReactNode;
  compact?: boolean;
}) {
  const sub = subtitle && (
    <motion.p
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: EASE.out, delay: 0.35 }}
      className={compact ? "mt-1 text-sm text-grey-700" : "mx-auto mt-3 max-w-2xl text-grey-700"}
    >
      {subtitle}
    </motion.p>
  );

  if (compact) {
    return (
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-black">{animated ?? title}</h1>
        {sub}
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:gap-0">
      <div aria-hidden className={aside ? "hidden w-24 shrink-0 sm:block" : "hidden"} />
      <div className="min-w-0 flex-1 text-center">
        <h1
          className={
            art
              ? "sr-only"
              : "text-[clamp(2.5rem,7vw,4rem)] font-extrabold leading-[1.05] tracking-tight text-black"
          }
        >
          {art ? title : (animated ?? title)}
        </h1>
        {art && <div aria-hidden="true">{art}</div>}
        {sub}
      </div>
      {aside && <div className="flex shrink-0 sm:w-24 sm:justify-end">{aside}</div>}
    </div>
  );
}
