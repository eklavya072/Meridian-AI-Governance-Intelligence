"use client";

/**
 * TiltCard — CSS-faux-3D tilt on hover.
 *
 * A subtle rotateX/rotateY driven by pointer position (few degrees max),
 * with a depth-increasing shadow while hovered. Transform/opacity only —
 * no layout involvement — and the short settle back to 0 on leave keeps
 * it tactile without feeling like a gimmick. Used for workspace rows and
 * framework cards; the shared geometry keeps the two surfaces consistent.
 *
 * Deliberate implementation choices:
 * - The transform is written straight to the DOM element (no React state),
 *   so a pointermove storm never triggers re-renders — motion stays on the
 *   compositor.
 * - Tilt is gated to fine-pointer, hover-capable devices via
 *   `(hover: hover)` — touch users scroll the page, they don't hover, and a
 *   tilt reacting to scroll-gesture pointermoves would jitter the cards.
 * - `useReducedMotion` disables tilt entirely for users who opt out.
 */

import { useRef } from "react";
import { useReducedMotion } from "motion/react";

const MAX_TILT_DEG = 3.5;
const REST_TRANSFORM = "perspective(900px)";

function isHoverCapable(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(hover: hover) and (pointer: fine)").matches
  );
}

export default function TiltCard({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (reducedMotion || !isHoverCapable()) return;
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    // Normalized pointer position in [-1, 1] within the card.
    const px = (e.clientX - rect.left) / rect.width - 0.5;
    const py = (e.clientY - rect.top) / rect.height - 0.5;
    const rx = -py * MAX_TILT_DEG;
    const ry = px * MAX_TILT_DEG;
    el.style.transform = `perspective(900px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg)`;
  }

  function onPointerLeave() {
    const el = ref.current;
    if (!el) return;
    el.style.transform = REST_TRANSFORM;
  }

  return (
    <div
      ref={ref}
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
      style={{
        transformStyle: "preserve-3d",
        transform: REST_TRANSFORM,
        // Short settle so the tilt follows the cursor without lag and
        // returns smoothly on leave — transform-only, compositor-friendly.
        transition: "transform 180ms ease-out",
        willChange: "transform",
      }}
      className={`relative ${className}`}
    >
      {children}
    </div>
  );
}
