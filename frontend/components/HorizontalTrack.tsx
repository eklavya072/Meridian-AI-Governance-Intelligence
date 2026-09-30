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
}: {
  panels: { key: string; node: ReactNode }[];
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

      /* Panels DWELL. Mapping progress straight onto travel would leave each
         panel correctly framed for one instant only. Instead, progress is
         split into one segment per gap and eased within each. Smootherstep
         is flat at both ends, so the rail is nearly still whenever a panel
         is centred and does its moving in between. */
      /* A lead-in and a TAIL around the traverse: it starts at 6% and ends
         at 88%, so the final panel sits still while the stage is still
         pinned, and the sideways and vertical motion never meet in the same
         frame. The same dwell logic the hero's beats use. */
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
    };

    const clear = () => {
      rail.style.transform = "";
      for (let n = 0; n < rail.children.length; n++) {
        (rail.children[n] as HTMLElement).style.transform = "";
      }
      lastX = -1;
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
      </div>
    </div>
  );
}
