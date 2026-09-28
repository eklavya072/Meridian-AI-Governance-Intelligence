"use client";

/**
 * Four measured numbers, counted up on arrival.
 *
 * Every figure here comes from a recorded run or from the repository
 * itself, and each one names its source in the markup below. Nothing is
 * rounded up for effect and nothing is invented, which is the only reason a
 * band like this earns its place on a page about verifiable claims.
 *
 * The count is driven by setInterval with a settle timer behind it, not by
 * requestAnimationFrame or a spring: the value has to arrive whether or not
 * the frame loop is running. A number that never finishes counting is worse
 * than a number that simply appears.
 */

import { useEffect, useRef, useState } from "react";

type Stat = {
  value: number;
  decimals?: number;
  suffix?: string;
  label: string;
  source: string;
};

const STATS: Stat[] = [
  { value: 8, label: "governance dimensions", source: "per strategy" },
  { value: 43, label: "frameworks indexed", source: "config/frameworks.yaml" },
  // 318 of 330 evidence citations confirmed across the eight countries'
  // showcase runs, recounted 28 Sep 2026. Not the 88.7% in MEASUREMENTS.md,
  // which is the verifier's acceptance rate on known-verbatim excerpts (a
  // calibration of the checker, not of the tool's citations).
  {
    value: 96.4,
    decimals: 1,
    suffix: "%",
    label: "of citations confirmed at source",
    source: "showcase runs, 8 countries",
  },
  { value: 1320, label: "tests passing", source: "CI, 80% coverage" },
];

function useCount(target: number, active: boolean, decimals: number) {
  const [n, setN] = useState(0);

  useEffect(() => {
    if (!active) return;

    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setN(target);
      return;
    }

    /* Long enough to be watched. At 1.1s the count was over before the band
       had finished arriving — technically animated, and never actually seen
       rolling. */
    const DUR = 1900;
    const t0 = Date.now();
    const id = setInterval(() => {
      const p = Math.min(1, (Date.now() - t0) / DUR);
      /* Exponential ease-out: fast off the mark, long settle, which is how
         a readout behaves rather than how a slider behaves. */
      setN(target * (1 - Math.pow(1 - p, 3)));
      if (p >= 1) clearInterval(id);
    }, 40);
    /* The guarantee, independent of the interval above: clamped timers in a
       backgrounded tab would otherwise leave the number mid-count. */
    const settle = setTimeout(() => setN(target), DUR + 700);
    return () => {
      clearInterval(id);
      clearTimeout(settle);
    };
    /* No `started` latch. The count used to fire once per mount and never
       again, so scrolling back up to the band showed four settled numbers —
       the effect existed exactly once per page load, at the one moment the
       reader was least likely to be looking at it. Keyed on `active`
       instead, so it replays on every entry. */
  }, [active, target, decimals]);

  return n;
}

function Figure({ stat, active }: { stat: Stat; active: boolean }) {
  const n = useCount(stat.value, active, stat.decimals ?? 0);
  const shown =
    stat.decimals && stat.decimals > 0
      ? n.toFixed(stat.decimals)
      : Math.round(n).toLocaleString("en-GB");

  return (
    <div className="l-stat">
      <p className="l-stat-value">
        <span className="l-sr">
          {stat.value.toLocaleString("en-GB")}
          {stat.suffix ?? ""}
        </span>
        <span aria-hidden="true">
          {shown}
          {stat.suffix ?? ""}
        </span>
      </p>
      <p className="l-stat-label">{stat.label}</p>
      <p className="l-stat-source">{stat.source}</p>
    </div>
  );
}

export default function StatsBand() {
  const ref = useRef<HTMLElement>(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      /* Unmeasurable viewport means show the finished state, the same way
         every other reveal on this route fails open. */
      if (!vh) return setActive(true);
      /* Presence, not position. The figures have been a scrolling band, a
         panel on a track, and a strip pinned to a sticky foot; a threshold
         tuned to any one of those broke on the next. "Is any of it on
         screen" survives all three. Still a window rather than a latch, so
         leaving the section and coming back re-runs the roll. */
      setActive(r.top < vh && r.bottom > 0);
    };
    const poll = setInterval(check, 300);
    check();
    window.addEventListener("scroll", check, { passive: true });
    return () => {
      clearInterval(poll);
      window.removeEventListener("scroll", check);
    };
  }, []);

  return (
    /* No `data-surface` any more: this rides inside the track as its
       closing panel, so it paints its own dark card on the track's paper
       rather than claiming a surface of its own. A full-bleed band between
       two sections was one change of place too many — the figures belong to
       the argument that earned them. */
    <section className="l-stats" ref={ref} aria-label="Measured results">
      <div className="l-stats-inner">
        {STATS.map((s) => (
          <Figure key={s.label} stat={s} active={active} />
        ))}
      </div>
    </section>
  );
}
