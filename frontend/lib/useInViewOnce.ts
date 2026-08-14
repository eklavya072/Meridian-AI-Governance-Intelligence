"use client";

/**
 * useInViewOnce — scroll-reveal gate shared by the charts.
 *
 * Returns true once `visibleRatio` (default 25%) of the ref'd element is on
 * screen, then stays true (and tears everything down).
 *
 * Deliberately NOT IntersectionObserver or framer's onViewportEnter: both
 * proved unreliable for SVG charts inside scaled webviews/iframes (observed
 * never firing on scroll-in despite full visibility). Instead: a capture-
 * phase scroll listener + resize listener PLUS a 400ms poll fallback, since
 * some embedded webviews scroll without dispatching scroll events to the
 * page at all. One getBoundingClientRect per check is negligible, and the
 * poll is cleared the moment the element becomes visible.
 */

import { useEffect, useState, type RefObject } from "react";

export function useInViewOnce<T extends Element>(
  ref: RefObject<T | null>,
  visibleRatio = 0.25
): boolean {
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    // Hoisted above check(): check() may fire cleanup() synchronously on its
    // first run (element already in view at mount) — a `const timer` declared
    // later would be in its temporal dead zone there (ReferenceError).
    let done = false;
    let timer: number | undefined;

    const check = () => {
      if (done) return;
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      if (rect.height <= 0) return; // not laid out yet
      const vh = window.innerHeight || document.documentElement.clientHeight;
      const visible = Math.min(rect.bottom, vh) - Math.max(rect.top, 0);
      if (visible > rect.height * visibleRatio) {
        done = true;
        setEntered(true);
        cleanup();
      }
    };

    const cleanup = () => {
      done = true;
      window.removeEventListener("scroll", check, true);
      window.removeEventListener("resize", check);
      if (timer !== undefined) window.clearInterval(timer);
    };

    check();
    window.addEventListener("scroll", check, true); // capture: nested scrollers
    window.addEventListener("resize", check);
    timer = window.setInterval(check, 400);
    return cleanup;
  }, [ref, visibleRatio]);

  return entered;
}
