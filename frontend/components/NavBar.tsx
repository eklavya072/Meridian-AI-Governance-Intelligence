"use client";

/**
 * NavBar — a centered, floating glass pill.
 *
 * Not a full-width bar: the pill is fixed at 20px from the top, horizontally
 * centered, fully rounded, with real glassmorphism (backdrop blur 20px,
 * translucent black fill, thin light border). It is the one glass element
 * on the site. The wordmark + all 5 nav items (Workspace, Analysis, Brief,
 * AI Auditor, Frameworks) fit in a single row.
 *
 * Auto-hide: the pill slides up out of view on scroll-down and reappears on
 * scroll-up OR when the cursor nears the top edge (a mousemove check — no
 * invisible hit-zone overlay, nothing ever blocked).
 *
 * Nav links use the cursor-tracked animated underline (.link-swipe): the
 * line draws itself outward from wherever the pointer touches the link and
 * stays drawn on the active route.
 */

import { usePathname } from "next/navigation";
import MeridianMark from "@/components/MeridianMark";
import { useEffect, useRef, useState, type MouseEvent } from "react";

const LINKS = [
  { href: "/workspace", label: "Workspace" },
  { href: "/analysis", label: "Analysis" },
  { href: "/brief", label: "Brief" },
  { href: "/auditor", label: "AI Auditor", hideBelow: "lg" },
  { href: "/frameworks", label: "Frameworks", hideBelow: "md" },
];

/** Cursor band near the top of the viewport that reveals the hidden pill. */
const REVEAL_ZONE_PX = 120;

export default function NavBar() {
  const pathname = usePathname();
  const [scrolledHidden, setScrolledHidden] = useState(false);
  const [nearTop, setNearTop] = useState(false);
  const hiddenRef = useRef(false);
  const nearTopRef = useRef(false);

  useEffect(() => {
    /* sinceFlip accumulates net scroll movement in the current direction
       and decays against it when the direction reverses, so slow drags
       (sub-threshold per-event deltas) still add up to a flip while small
       jitters in the opposite direction don't. Flip resets the accumulator.
       Reveal needs only ~8px of net upward movement — not a return to the
       original hide point. */
    let lastY = window.scrollY;
    let sinceFlip = 0;

    /* `data-nav-pin` anywhere on the page holds the bar for the WHOLE page,
       not just the region it sits on. It started as a hero-only hold — the
       scrub is one continuous gesture and a bar that tucks away three lines
       in and returns four lines later turns that into a flicker — but the
       same argument runs the rest of the way down: the landing page is one
       argument read top to bottom, and losing its navigation halfway through
       leaves the reader on a page with no way off it.

       Queried live rather than cached, because the element only exists on
       routes that ask for it and the app's own pages still auto-hide. */
    const pinned = () => !!document.querySelector("[data-nav-pin]");

    const show = () => {
      if (hiddenRef.current) {
        hiddenRef.current = false;
        setScrolledHidden(false);
      }
    };
    const hide = () => {
      if (!hiddenRef.current) {
        hiddenRef.current = true;
        setScrolledHidden(true);
      }
    };

    const onScroll = () => {
      const y = window.scrollY;
      const delta = y - lastY;
      lastY = y;
      if (y < 96 || pinned()) {
        sinceFlip = 0;
        show(); // top of the page, or a route that holds the bar throughout
        return;
      }
      if (delta > 0) sinceFlip = Math.max(0, sinceFlip) + delta;
      else if (delta < 0) sinceFlip = Math.min(0, sinceFlip) + delta;
      if (hiddenRef.current) {
        if (sinceFlip < -8) {
          sinceFlip = 0;
          show(); // net upward movement — bring it back
        }
      } else if (sinceFlip > 12) {
        sinceFlip = 0;
        hide(); // net downward movement — tuck away
      }
    };

    const onMove = (e: globalThis.MouseEvent) => {
      const n = e.clientY < REVEAL_ZONE_PX;
      if (n !== nearTopRef.current) {
        nearTopRef.current = n;
        setNearTop(n);
      }
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("mousemove", onMove, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("mousemove", onMove);
    };
  }, []);

  const hidden = scrolledHidden && !nearTop;

  return (
    /* Full-width flex wrapper owns centering + the hide transform; it is
       pointer-events-none so the empty strip beside the pill never blocks
       clicks. The pill itself re-enables pointer events. */
    <nav
      className={`nav-auto-hide fixed top-4 inset-x-0 z-50 flex justify-center pointer-events-none ${
        hidden ? "is-hidden" : ""
      }`}
    >
      {/* The pill carries the brand now that the landing hero does not, so
          the mark sits beside the wordmark. It is deliberately trimmed back
          from the size it briefly ran at: a floating chrome element earns
          its place by staying out of the way, and every pixel it takes is
          taken from the page it sits over. The base breakpoint stays tight
          so it never clips on narrow phones. */}
      <div className="nav-pill pointer-events-auto flex items-center gap-1 sm:gap-2 rounded-full px-4 sm:px-6 py-[0.55rem] sm:py-3">
        <a
          href="/"
          className="flex items-center gap-2 font-brand text-[1.15rem] sm:text-xl font-semibold tracking-tight text-white pr-2 sm:pr-3"
        >
          <MeridianMark size={22} className="shrink-0 w-[1.1rem] h-[1.1rem] sm:w-[1.35rem] sm:h-[1.35rem]" />
          Meridian
        </a>
        <span className="hidden sm:block h-4 sm:h-5 w-px bg-white/15" aria-hidden />
        <div className="flex items-center gap-3 sm:gap-[1.15rem] lg:gap-6 text-[15px] font-display font-medium tracking-tight pl-2 sm:pl-3">
          {LINKS.map((link) => {
            const active =
              link.href === "/"
                ? pathname === "/"
                : pathname.startsWith(link.href);
            return (
              <NavLink
                key={link.href}
                href={link.href}
                label={link.label}
                active={active}
                hideBelow={link.hideBelow}
              />
            );
          })}
        </div>
      </div>
    </nav>
  );
}

function NavLink({
  href,
  label,
  active,
  hideBelow,
}: {
  href: string;
  label: string;
  active: boolean;
  hideBelow?: string;
}) {
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

  const responsiveClass = hideBelow === "lg" ? "hidden lg:inline-flex" : hideBelow === "md" ? "hidden md:inline-flex" : "inline-flex";

  return (
    <a
      ref={ref}
      href={href}
      onMouseEnter={trackCursor}
      onMouseMove={trackCursor}
      onMouseLeave={resetOrigin}
      className={`link-swipe relative py-0.5 transition-colors hover:text-white ${
        active ? "link-swipe-active text-white font-semibold" : "text-white font-medium"
      } ${responsiveClass}`}
    >
      {label}
    </a>
  );
}
