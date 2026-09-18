"use client";

/**
 * Three panels that travel sideways as the page scrolls down.
 *
 * A tall pinned region holds a sticky viewport-height window; progress
 * through it slides a flex row of panels horizontally. Scrolling down still
 * means moving forward, which is the only reason this is worth doing: it
 * borrows the hero's grammar so the middle of the page reads as one
 * continuous move rather than three stacked sections.
 *
 * The failure mode is the whole design problem with a device like this, so
 * it is handled first, not last:
 *
 *   - The panels are a plain flex row. With no JS and no transform they sit
 *     in the normal flow and every one of them is reachable by scrolling.
 *   - The transform is written straight to the style attribute from a
 *     scroll listener, backed by a 500ms poll. It never touches
 *     requestAnimationFrame, so a stalled compositor costs smoothness and
 *     nothing else.
 *   - Below the breakpoint, and under reduced motion, the track is not a
 *     track at all: the CSS stacks the panels vertically and the JS never
 *     writes a transform. That is the same five-gate decision the hero
 *     makes, evaluated live.
 */

import { useEffect, useRef, type ReactNode } from "react";

const GATES = [
  "(max-width: 1024px)",
  "(orientation: portrait) and (pointer: coarse)",
  "(prefers-reduced-motion: reduce)",
];

export default function HorizontalTrack({
  panels,
  rail,
}: {
  panels: { key: string; node: ReactNode }[];
  rail?: ReactNode;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const railRef = useRef<HTMLDivElement>(null);
  const windowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    const rail = railRef.current;
    const win = windowRef.current;
    if (!root || !rail || !win) return;

    const panelCount = panels.length;
    let horizontal: boolean | null = null;
    let lastX = -1;
    let lastP = -1;

    const write = () => {
      if (!horizontal) return;
      const span = root.offsetHeight - window.innerHeight;
      const vh = window.innerHeight || document.documentElement.clientHeight;
      /* Unmeasurable viewport: show the finished state rather than the start
         one, for the same reason every reveal on this route fails open. */
      const p =
        span > 0 && vh
          ? Math.min(1, Math.max(0, -root.getBoundingClientRect().top / span))
          : 1;

      /* Travel is how far the row overruns the WINDOW, measured rather than
         guessed, so the last panel lands flush with the right edge whatever
         the panels turn out to be. Measuring the rail against itself gives
         zero: it is width:max-content, so it never overflows its own box —
         the clipping happens one level up. */
      const travel = Math.max(0, rail.scrollWidth - win.clientWidth);

      /* Panels DWELL. Mapping progress straight onto travel means the rail
         never stops, so each panel is correctly framed for exactly one
         instant and is sliding off the moment you start reading — measured
         at 6% through the track with the first panel's copy already at
         x -90, ninety pixels off the left edge.

         Instead, progress is split into one segment per gap and eased
         within each. Smootherstep is flat at both ends, so the rail is
         nearly still whenever a panel is centred and does its moving in
         between. That gives reading time without the hold-then-lurch of a
         hard pause. */
      /* A lead-in and a TAIL around the traverse.
         `p` used to run 0 to 1 across the whole pinned section, which meant
         the rail was still moving at the exact scroll position where the
         sticky released — the sideways motion stopped and the vertical
         motion started in the same frame, with nothing in between. That is
         the lurch at the end of the section.

         The traverse now finishes at 88% and starts at 6%. The last twelve
         percent of the section's scroll is the final panel sitting
         perfectly still while the stage is still pinned, so the reader
         arrives, reads, and only then does the page move on. Same dwell
         logic the hero's beats use, applied to the section as a whole. */
      const LEAD = 0.06;
      const TAIL = 0.88;
      const pT = Math.min(1, Math.max(0, (p - LEAD) / (TAIL - LEAD)));

      const gaps = Math.max(1, panelCount - 1);
      const seg = Math.min(gaps - 0.000001, pT * gaps);
      const i = Math.floor(seg);
      const f = seg - i;

      /* DWELL and MOVE are two different jobs, so they get two different
         stretches of scroll: the panel sits still at each end of a segment
         and the whole traverse is eased across the middle. Pure smootherstep
         across the entire gap is never still and never quick, which is what
         made one panel take so long to hand to the next.

         The window was 0.2–0.8, which put the traverse into 60% of the
         segment and overshot — the handover snapped. At 0.12–0.88 the move
         has 76% of the segment to cross, so it still starts and ends from
         rest but travels at roughly two thirds the speed. */
      const MOVE_FROM = 0.12;
      const MOVE_TO = 0.88;
      const m = Math.min(1, Math.max(0, (f - MOVE_FROM) / (MOVE_TO - MOVE_FROM)));
      const eased = m * m * m * (m * (m * 6 - 15) + 10);
      const x = Math.round(((i + eased) / gaps) * travel);
      if (x !== lastX) {
        lastX = x;
        rail.style.transform = `translate3d(${-x}px,0,0)`;

        /* The rail is straight; the panels ride an arc across it. Each one
           is placed by its distance from the window's centre, so it sinks
           and tips as it leaves and rises level as it arrives — the panels
           read as points on the rim of a very large wheel rather than as
           cards sliding on a rail. The fall is quadratic in that distance,
           which is what makes it read as a curve and not a ramp. */
        const panelEls = rail.children;
        const winW = win.clientWidth || 1;
        const centre = x + winW / 2;
        for (let n = 0; n < panelEls.length; n++) {
          const el = panelEls[n] as HTMLElement;
          const d = (el.offsetLeft + el.offsetWidth / 2 - centre) / winW;
          const dc = Math.max(-1.4, Math.min(1.4, d));
          const dip = Math.round(dc * dc * 46);
          const tip = (dc * 2.6).toFixed(2);
          const sc = (1 - Math.min(0.075, dc * dc * 0.085)).toFixed(4);
          el.style.transform = `translate3d(0,${dip}px,0) rotate(${tip}deg) scale(${sc})`;
        }
      }
      const pr = Math.round(p * 200) / 200;
      if (pr !== lastP) {
        lastP = pr;
        /* 2πr for r = 27, the arc's own circumference: the indicator is a
           circle drawing itself once across the track rather than a bar
           filling up. */
        const C = 169.646;
      }
    };

    const clear = () => {
      rail.style.transform = "";
      for (let n = 0; n < rail.children.length; n++) {
        (rail.children[n] as HTMLElement).style.transform = "";
      }
      lastX = -1;
      lastP = -1;
    };

    const mqls = GATES.map((q) => window.matchMedia(q));
    const apply = () => {
      const stacked = mqls.some((m) => m.matches);
      if (stacked === !horizontal && horizontal !== null) return;
      horizontal = !stacked;
      root.classList.toggle("is-horizontal", horizontal);
      if (!horizontal) clear();
      else write();
    };

    mqls.forEach((m) => m.addEventListener("change", apply));
    window.addEventListener("scroll", write, { passive: true });
    window.addEventListener("resize", write);
    /* Timers keep firing where scroll events do not. */
    const poll = setInterval(write, 500);
    apply();

    return () => {
      mqls.forEach((m) => m.removeEventListener("change", apply));
      window.removeEventListener("scroll", write);
      window.removeEventListener("resize", write);
      clearInterval(poll);
    };
  }, [panels.length]);

  return (
    <div
      ref={rootRef}
      className="l-track"
      data-surface="paper"
      style={{ ["--panels" as string]: panels.length }}
    >
      <div ref={windowRef} className="l-track-window">
        <div ref={railRef} className="l-track-rail">
          {panels.map((p) => (
            <div key={p.key} className="l-panel">
              {p.node}
            </div>
          ))}
        </div>
        {/* The rail lives INSIDE the sticky window, so it holds the foot of
            the stage for the whole sideways travel rather than arriving as
            a fourth panel and leaving with it. The figures are the constant
            the three panels are argued against — a footer to the section,
            not a station on it. */}
        {rail ? <div className="l-track-rail-fixed">{rail}</div> : null}
      </div>
    </div>
  );
}
