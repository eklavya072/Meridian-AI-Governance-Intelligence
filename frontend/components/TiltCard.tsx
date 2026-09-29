"use client";

/**
 * TiltCard — a card that leans toward the pointer.
 *
 * A rotateX/rotateY driven by pointer position, with the transform written
 * straight to the DOM (no React state), so a pointermove storm never
 * re-renders and the motion stays on the compositor.
 *
 * Two strengths:
 * - `subtle` (workspace rows): a few degrees of lean and nothing else.
 * - `strong` (framework cards): a deeper lean, the card lifting toward the
 *   reader, its shadow deepening underneath, and a faint pool of shade that
 *   follows the cursor across the face, so the card reads as a surface
 *   turning under a light.
 *
 * Gated to fine-pointer, hover-capable devices: touch users scroll, they
 * don't hover, and a tilt reacting to scroll-gesture pointermoves would
 * jitter the cards. `useReducedMotion` turns it off entirely.
 */

import { useRef } from "react";
import { useReducedMotion } from "motion/react";

const PRESETS = {
  subtle: { deg: 3.5, lift: 1, glare: false },
  strong: { deg: 8, lift: 1.025, glare: true },
} as const;

const REST_TRANSFORM = "perspective(900px)";
const REST_SHADOW = "0 1px 2px rgba(10, 10, 10, 0.05)";
const LIFT_SHADOW = "0 22px 44px -20px rgba(10, 10, 10, 0.38), 0 6px 14px -8px rgba(10, 10, 10, 0.16)";

function isHoverCapable(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(hover: hover) and (pointer: fine)").matches
  );
}

export default function TiltCard({
  children,
  className = "",
  id,
  strength = "subtle",
}: {
  children: React.ReactNode;
  className?: string;
  id?: string;
  strength?: keyof typeof PRESETS;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const glareRef = useRef<HTMLSpanElement>(null);
  const reducedMotion = useReducedMotion();
  const preset = PRESETS[strength];

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (reducedMotion || !isHoverCapable()) return;
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    // Normalized pointer position in [-0.5, 0.5] within the card.
    const px = (e.clientX - rect.left) / rect.width - 0.5;
    const py = (e.clientY - rect.top) / rect.height - 0.5;
    const rx = -py * preset.deg;
    const ry = px * preset.deg;
    el.style.transition = "transform 120ms ease-out, box-shadow 250ms ease-out";
    el.style.transform = `perspective(900px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg) scale(${preset.lift})`;
    if (strength === "strong") el.style.boxShadow = LIFT_SHADOW;
    const glare = glareRef.current;
    if (glare) {
      glare.style.opacity = "1";
      glare.style.background = `radial-gradient(360px circle at ${((px + 0.5) * 100).toFixed(1)}% ${((py + 0.5) * 100).toFixed(1)}%, rgba(10, 10, 10, 0.055), rgba(10, 10, 10, 0) 60%)`;
    }
  }

  function onPointerLeave() {
    const el = ref.current;
    if (!el) return;
    // The settle is slower than the follow, so the card eases back rather
    // than snapping flat.
    el.style.transition = "transform 480ms cubic-bezier(0.16, 1, 0.3, 1), box-shadow 480ms ease-out";
    el.style.transform = REST_TRANSFORM;
    if (strength === "strong") el.style.boxShadow = REST_SHADOW;
    if (glareRef.current) glareRef.current.style.opacity = "0";
  }

  return (
    <div
      ref={ref}
      id={id}
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
      style={{
        transformStyle: "preserve-3d",
        transform: REST_TRANSFORM,
        transition: "transform 180ms ease-out",
        willChange: "transform",
        ...(strength === "strong" ? { boxShadow: REST_SHADOW } : {}),
      }}
      className={`relative ${className}`}
    >
      {children}
      {preset.glare && (
        <span
          ref={glareRef}
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-[inherit] opacity-0 transition-opacity duration-300"
        />
      )}
    </div>
  );
}
