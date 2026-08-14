"use client";

/**
 * Preloader — Skiper 9-style entrance for the Meridian landing page.
 *
 * Sequence on a fixed, black, full-viewport overlay:
 *   1. The Meridian mark fades/blurs in, then "Meridian" follows character
 *      by character (brand face), the "AI Governance Intelligence" subline
 *      fades in beneath it, and a hairline fills — pure black screen, white
 *      symbol + text.
 *   2. SOLID staircase panels sweep UP from the bottom, staggered
 *      left→right, climbing over the brand like steps — no glass, no
 *      gradient, just dark slabs.
 *   3. A beat, then the panels DROP AWAY in the same stepped order —
 *      revealing the page top-first as `onReveal()` fires, so the intro
 *      content animates in beneath the falling stairs.
 *   4. The overlay fades out and `onDone()` unmounts it.
 *
 * Reduced motion: skips straight to `onReveal` + `onDone` (no overlay).
 */

import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { EASE } from "@/lib/motion";
import MeridianMark from "@/components/MeridianMark";

const WORD = "Meridian";
const STAIR_COUNT = 7;

type Phase = "name" | "cover" | "lift" | "gone";

export default function Preloader({
  reduced,
  onReveal,
  onDone,
}: {
  reduced: boolean;
  onReveal: () => void;
  onDone: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("name");

  /* Timeline — name → stairs cover → hold → stairs drop → fade out. */
  useEffect(() => {
    if (reduced) {
      onReveal();
      onDone();
      return;
    }
    const timers: ReturnType<typeof setTimeout>[] = [];
    const at = (ms: number, fn: () => void) => timers.push(setTimeout(fn, ms));
    at(1700, () => setPhase("cover")); // stairs sweep up over the name
    at(2700, () => {
      onReveal(); // page animates in beneath the lift
      setPhase("lift"); // stairs drop away, top first
    });
    at(3600, () => setPhase("gone")); // overlay fades
    at(4000, () => onDone()); // unmount
    return () => timers.forEach((t) => clearTimeout(t));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reduced]);

  /* Lock page scroll while the overlay is up, restore on unmount. */
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.scrollTo(0, 0);
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  return (
    <motion.div
      className="fixed inset-0 z-[100] flex items-center justify-center overflow-hidden"
      style={{ background: "#000000" }}
      initial={{ opacity: 1 }}
      animate={{ opacity: phase === "gone" ? 0 : 1 }}
      transition={{ duration: 0.4, ease: EASE.out }}
      aria-hidden
    >
      {/* Wordmark — the mark, then the name characters blur in; the stairs
          sweep over all of it. */}
      <div className="relative z-10 px-6 text-center">
        {/* The brand symbol — fades/blurs in just ahead of the wordmark. */}
        <motion.div
          initial={{ opacity: 0, y: 10, filter: "blur(8px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          transition={{ duration: 0.6, ease: EASE.out, delay: 0.1 }}
          className="mb-7 flex justify-center text-white"
        >
          <MeridianMark size={72} />
        </motion.div>
        <div className="flex justify-center">
          {WORD.split("").map((ch, i) => (
            <motion.span
              key={i}
              className="font-brand font-semibold text-white leading-none tracking-tight text-[clamp(2.6rem,9vw,5.5rem)]"
              initial={{ opacity: 0, y: 26, filter: "blur(10px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              transition={{ duration: 0.7, ease: EASE.out, delay: 0.15 + i * 0.055 }}
            >
              {ch}
            </motion.span>
          ))}
        </div>
        <motion.div
          className="mt-5 font-brand text-[11px] sm:text-sm font-medium uppercase tracking-[0.34em] text-white/70"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE.out, delay: 1.0 }}
        >
          AI Governance Intelligence
        </motion.div>
        <motion.div
          className="mx-auto mt-8 h-px w-44 origin-center bg-white/40"
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 1.2, ease: EASE.out, delay: 0.45 }}
        />
      </div>

      {/* Staircase panels — rise staggered, drop staggered. */}
      {Array.from({ length: STAIR_COUNT }).map((_, i) => (
        <motion.div
          key={i}
          className="absolute inset-y-0"
          style={{
            left: `${(i * 100) / STAIR_COUNT}%`,
            width: `${100 / STAIR_COUNT}%`,
            /* Solid panels — no gradient, no glass: the stairs read as
               solid dark slabs stepping over the brand. */
            background: "#141414",
          }}
          initial={{ y: "100%" }}
          animate={{
            y: phase === "name" ? "100%" : phase === "cover" ? "0%" : "110%",
          }}
          transition={
            phase === "cover" || phase === "lift"
              ? {
                  duration: phase === "cover" ? 0.6 : 0.7,
                  ease: "easeInOut",
                  delay: i * 0.05,
                }
              : { duration: 0.2 }
          }
        />
      ))}
    </motion.div>
  );
}
