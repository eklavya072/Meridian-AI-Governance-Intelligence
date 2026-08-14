"use client";

/**
 * RollingText — a faithful rebuild of the Skiper 27 "Rolling text" effect.
 *
 * Mechanical station-board (split-flap) animation: each character is a flap
 * that starts ABOVE its resting line, edge-on (rotateX 90° — invisible, a
 * sliver), then falls down and flips flat into place (rotateX 0°). Verified
 * against the Skiper 27 demo frames: letters enter from above the baseline,
 * are visibly compressed (edge-on) mid-roll, and lock onto the final text.
 *
 * The STAGGER is center-out — the middle letter flips first, the motion
 * radiates to both edges (delay = distance from center × speed) — with a
 * hard-deceleration ease for the mechanical "slap" feel. Plays once when
 * scrolled into view and settles on the exact text.
 *
 * Characters are grouped into nowrap WORD runs (breaks only between words),
 * so the heading wraps at word boundaries instead of splitting a word
 * mid-way ("decision-ready" landing "d" on one line, "ecision" on the next).
 *
 * Typography, size and color come from the parent element — this component
 * only animates.
 */

import { type ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";
import { EASE } from "@/lib/motion";

interface RollingTextProps {
  text: string;
  /** Delay between each letter (distance from center × speed). */
  speed?: number;
  /** Per-letter flap duration in seconds. */
  duration?: number;
  className?: string;
}

export default function RollingText({
  text,
  speed = 0.05,
  duration = 0.6,
  className = "",
}: RollingTextProps) {
  const reduced = useReducedMotion();
  const chars = text.split("");
  const center = (chars.length - 1) / 2;

  if (reduced) {
    return <span className={className}>{text}</span>;
  }

  /* The station-board cell: a masked window exactly one character tall.
     The flap starts above it (clipped out of sight) and falls down INTO the
     window while flipping — so a mid-roll letter never floats over other
     content, it emerges inside its own cell. */
  const charMask = (ch: string, i: number, key: string) => (
    <motion.span
      key={key}
      aria-hidden
      className="inline-block overflow-hidden align-bottom"
      style={{ height: "1.15em", lineHeight: "1.15", perspective: 600 }}
    >
      <motion.span
        variants={{
          hidden: { y: "-1.1em", rotateX: 90, opacity: 0 },
          show: {
            y: "0em",
            rotateX: 0,
            opacity: 1,
            transition: {
              duration,
              ease: EASE.outSoft,
              delay: Math.abs(i - center) * speed,
            },
          },
        }}
        className="block"
        style={{ transformOrigin: "50% 50%", backfaceVisibility: "hidden" }}
      >
        {ch === " " ? "\u00A0" : ch}
      </motion.span>
    </motion.span>
  );

  /* Flatten words + spaces into a single indexed sequence, then group the
     non-space characters into nowrap runs so line breaks can only happen
     between words. */
  const words = text.split(" ");
  const flat: { ch: string; isSpace: boolean }[] = [];
  words.forEach((w, wi) => {
    w.split("").forEach((ch) => flat.push({ ch, isSpace: false }));
    if (wi < words.length - 1) flat.push({ ch: " ", isSpace: true });
  });

  const nodes: ReactNode[] = [];
  let pending: ReactNode[] = [];
  let idx = -1;
  const flush = () => {
    if (!pending.length) return;
    nodes.push(
      <span
        key={`w${nodes.length}`}
        style={{ display: "inline-block", whiteSpace: "nowrap" }}
      >
        {pending}
      </span>,
    );
    pending = [];
  };
  for (const { ch, isSpace } of flat) {
    idx += 1;
    if (isSpace) {
      flush();
      nodes.push(charMask(" ", idx, `s${idx}`));
    } else {
      pending.push(charMask(ch, idx, `c${idx}`));
    }
  }
  flush();

  return (
    <motion.span
      className={className}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: "-60px" }}
      aria-label={text}
      style={{ display: "inline-block" }}
    >
      {nodes}
    </motion.span>
  );
}
