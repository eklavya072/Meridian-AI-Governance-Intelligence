/**
 * Shared motion tokens & variants for Meridian.
 *
 * Every animation in the app is governed by these values so the motion
 * language stays consistent. The rules below are a direct application of
 * Emil Kowalski's animation principles (emilkowalski/skills@emil-design-eng):
 *
 *  - Default to ease-out; never linear easing for UI motion.
 *  - UI animations stay under ~300ms; the cinematic hero is the deliberate
 *    exception and does not use these tokens.
 *  - Prefer transform/opacity over animating layout properties.
 *  - Press feedback on interactive elements: subtle scale-down on :active.
 */

/** Premium ease-out curves (expo-ish deceleration). */
export const EASE = {
  /** Primary UI easing — fast start, gentle settle. */
  out: [0.16, 1, 0.3, 1] as const,
  /** Softer, Apple-like default for larger panels. */
  outSoft: [0.22, 1, 0.36, 1] as const,
  /** Reserved for elements that must feel mechanical (progress, scrubbing). */
  inOut: [0.65, 0, 0.35, 1] as const,
} as const;

/** UI durations — all at or under the 300ms "premium" ceiling. */
export const DUR = {
  /** Focus ring / color shifts. */
  instant: 0.12,
  /** Micro-interactions (badges, press states). */
  fast: 0.18,
  /** Standard enter/exit for panels and reveals. */
  base: 0.26,
  /** Large surfaces (drawers, accordions) — kept at the ceiling. */
  slow: 0.3,
} as const;

/**
 * Container that staggers its children. Use only when several elements
 * genuinely change at once — never animate 5 things simultaneously for
 * decoration; stagger is the tool for sequencing real state changes.
 */
export const staggerContainer = (stagger = 0.06, delayChildren = 0.04) => ({
  hidden: {},
  show: {
    transition: { staggerChildren: stagger, delayChildren },
  },
});

/** Standard per-child variants paired with staggerContainer. */
export const staggerChild = {
  hidden: { opacity: 0, y: 10 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: DUR.base, ease: EASE.out },
  },
} as const;

/** The transition object used by the accordion height animation. */
export const heightTransition = {
  height: { duration: DUR.slow, ease: EASE.outSoft },
  opacity: { duration: DUR.fast, ease: "easeOut" },
} as const;

/** Press feedback: 150ms scale-down, applied to every clickable surface. */
export const pressScale = {
  whileTap: { scale: 0.97 },
  transition: { duration: DUR.instant, ease: "easeOut" },
} as const;

/**
 * Verified-badge "snap into place". A light spring is deliberate here — it
 * reinforces the project's core trust mechanic (a citation is confirmed),
 * so a small, controlled settle is meaningful rather than decorative.
 */
export const verifiedSnap = {
  initial: { scale: 0.6, opacity: 0 },
  animate: {
    scale: 1,
    opacity: 1,
    transition: { type: "spring", stiffness: 520, damping: 30, mass: 0.6 },
  },
} as const;

/** Small checkmark pop for selection feedback (pills, chips). */
export const checkPop = {
  initial: { scale: 0, opacity: 0 },
  animate: {
    scale: 1,
    opacity: 1,
    transition: { type: "spring", stiffness: 600, damping: 30 },
  },
  exit: { scale: 0, opacity: 0 },
} as const;
