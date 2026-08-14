"use client";

/**
 * InkReveal — an "ink drawing" heading entrance.
 *
 * A two-beat sequence, deliberately composed and calm:
 *   1. WORDS RISE  — each word wipes up from its baseline (clip-path inset
 *      from the top), staggered, like a line being written.
 *   2. LIGHT SWEEP — once the words are assembled, a soft band of light
 *      passes across the navy letters (an animated gradient clipped to the
 *      text), as if the ink catches the light.
 *
 * Distinct from the app's other text effects: BlurText blurs letters in,
 * SplitText rises letters, EditorialReveal rises words through masks,
 * ScrollFloat floats — this one layers a wipe + a light sweep, so it reads
 * as a document being finished rather than mere motion.
 *
 * The base words are solid navy (inherited); the sheen is an absolutely
 * positioned duplicate of the text whose gradient band is parked off-screen
 * before/after the sweep, so it is invisible except during the pass.
 *
 * Motion rules: transform/filter/clip-path/background-position only,
 * on-mount, one-shot. Reduced motion renders the plain text with no
 * animation.
 */

import { motion, useReducedMotion } from "motion/react";

// ── Timing constants (seconds) — tune the feel in one place ─────────────
const WORD_STAGGER = 0.14; // gap between each word starting its wipe
const WIPE_DURATION = 0.55; // how long a single word takes to rise
const SHEEN_AFTER_LAST = 0.3; // sheen begins while the last word still wipes (overlap)
const SHEEN_DURATION = 0.9; // how long the light takes to cross

const WIPE_EASE = [0.22, 1, 0.36, 1] as const;

export default function InkReveal({
  text,
  className = "",
  ink = "#0A0A0A",
  sheen = "#7C8DB1",
}: {
  text: string;
  className?: string;
  /** Settled ink colour of the words. */
  ink?: string;
  /** Lighter band colour that sweeps across the letters. */
  sheen?: string;
}) {
  const reduced = useReducedMotion();

  if (reduced) {
    return <span className={className}>{text}</span>;
  }

  const words = text.split(" ");
  // The sheen overlaps the tail of the word wipe — the light arrives while
  // the last word is still rising, so the whole beat lands in ~2.4s rather
  // than a drawn-out sequence.
  const sheenDelay = 0.1 + (words.length - 1) * WORD_STAGGER + SHEEN_AFTER_LAST;

  return (
    <span className={`relative inline-block ${className}`} aria-label={text}>
      {/* Base layer: solid words, each rising from its baseline. */}
      <span aria-hidden className="inline-block">
        {words.map((word, i) => (
          <motion.span
            key={i}
            className="inline-block whitespace-nowrap"
            initial={{ clipPath: "inset(100% 0 0 0)" }}
            animate={{ clipPath: "inset(0% 0 0 0)" }}
            transition={{
              duration: WIPE_DURATION,
              ease: WIPE_EASE,
              delay: 0.1 + i * WORD_STAGGER,
            }}
          >
            {i > 0 && (
              <span aria-hidden className="inline-block" style={{ width: "0.26em" }} />
            )}
            {word}
          </motion.span>
        ))}
      </span>

      {/* Sheen layer: identical text, gradient clipped to the glyphs, the
          band parked off-screen until the sweep moment. */}
      <motion.span
        aria-hidden
        className="pointer-events-none absolute inset-0 select-none"
        style={{
          backgroundImage: `linear-gradient(110deg, ${ink} 38%, ${sheen} 50%, ${ink} 62%)`,
          backgroundSize: "250% 100%",
          backgroundClip: "text",
          WebkitBackgroundClip: "text",
          color: "transparent",
        }}
        // Band parked off the LEFT edge at rest (position 100%), then sweeps
        // LEFT→RIGHT (100% → 0%) across the words — the natural reading
        // direction for a light pass.
        initial={{ backgroundPosition: "100% 0" }}
        animate={{ backgroundPosition: "0% 0" }}
        transition={{ delay: sheenDelay, duration: SHEEN_DURATION, ease: "easeInOut" }}
      >
        {text}
      </motion.span>

    </span>
  );
}
