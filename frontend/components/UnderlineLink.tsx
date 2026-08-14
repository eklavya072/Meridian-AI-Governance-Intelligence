"use client";

import { useRef, type ReactNode, type MouseEvent } from "react";

type UnderlineLinkProps = {
  href: string;
  children: ReactNode;
  className?: string;
  /** Open in a new tab with safe rel attributes (defaults to true for
      external source links). */
  external?: boolean;
  ariaLabel?: string;
};

/**
 * Animated-underline link: the underline draws itself outward from wherever
 * the cursor enters/moves over the link, and collapses back on leave.
 * Uses the .link-swipe recipe from globals.css — no JS animation, just a
 * transform-origin custom property updated on mousemove.
 */
export default function UnderlineLink({
  href,
  children,
  className = "",
  external = true,
  ariaLabel,
}: UnderlineLinkProps) {
  const ref = useRef<HTMLAnchorElement>(null);

  function trackCursor(e: MouseEvent<HTMLAnchorElement>) {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
    el.style.setProperty("--u-origin", `${x}px center`);
  }

  function resetOrigin() {
    const el = ref.current;
    if (!el) return;
    el.style.setProperty("--u-origin", "left center");
  }

  return (
    <a
      ref={ref}
      href={href}
      target={external ? "_blank" : undefined}
      rel={external ? "noopener noreferrer" : undefined}
      aria-label={ariaLabel}
      onMouseEnter={trackCursor}
      onMouseMove={trackCursor}
      onMouseLeave={resetOrigin}
      className={`link-swipe inline-flex items-center gap-1.5 ${className}`}
    >
      {children}
    </a>
  );
}
