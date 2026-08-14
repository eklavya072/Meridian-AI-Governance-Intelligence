"use client";

/**
 * EditorialReveal — a restrained, editorial heading entrance.
 *
 * Each word rises through a hard mask with a soft ease-out, resolving from a
 * faint blur to sharp focus as it lands. No bounce, no rotation, no colour
 * shift, no sheen — the motion is quiet and deliberate, the way premium
 * editorial sites set a headline: the text simply settles into place.
 *
 * Distinct from the app's other effects: BlurText blurs letters in from
 * above, SplitText rises letters, InkReveal wipes words up + sweeps light,
 * WarpText warps a canvas, ScrollFloat floats lines on scroll. This one is a
 * masked word-rise with a focus resolve — movement that serves the text
 * rather than performing it.
 *
 * Motion rules: transform/filter/opacity only, on-mount, one-shot. The mask
 * (overflow-hidden on each word) carries the reveal; no layout shift.
 * Reduced motion renders the plain text with no animation.
 */

import { motion, useReducedMotion } from "motion/react";

// Expo-out — starts decisively, lands gently; no overshoot.
const EASE_OUT = [0.22, 1, 0.36, 1] as const;

export default function EditorialReveal({
  text,
  className = "",
  stagger = 0.09,
  delay = 0.1,
}: {
  text: string;
  className?: string;
  /** Seconds between each word starting its rise. */
  stagger?: number;
  /** Seconds before the first word starts. */
  delay?: number;
}) {
  const reduced = useReducedMotion();

  if (reduced) {
    return <span className={className}>{text}</span>;
  }

  const words = text.split(" ");

  return (
    <span className={`inline-block ${className}`} aria-label={text}>
      {words.map((word, i) => (
        <span
          key={i}
          aria-hidden
          className="inline-block overflow-hidden pb-[0.12em] -mb-[0.12em]"
        >
          <motion.span
            className="inline-block"
            initial={{ y: "110%", opacity: 0, filter: "blur(6px)" }}
            animate={{ y: "0%", opacity: 1, filter: "blur(0px)" }}
            transition={{
              duration: 0.75,
              ease: EASE_OUT,
              delay: delay + i * stagger,
            }}
          >
            {word}
            {i < words.length - 1 ? "\u00A0" : ""}
          </motion.span>
        </span>
      ))}
    </span>
  );
}
