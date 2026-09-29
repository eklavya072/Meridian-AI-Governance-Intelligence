"use client";

/* The evidence thread: a claim tied, visibly, to the passage it rests on.
   The product's whole argument is that no claim stands without a source,
   and on the page the two sat as neighbours with nothing joining them. A
   faint thread now runs down the left edge from the claim into its
   passage; on hover (or focus inside) it draws in brass from the claim to
   the source and the passage takes a brass tint, so the reader sees the
   finding and its evidence as one object.

   The path is measured from the rendered claim and source, so it lands on
   the passage's first line at any width. Pure SVG and CSS: no frame loop,
   nothing to run on scroll, and the reduced-motion path keeps the colour
   change without the draw. */

import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

export default function EvidenceThread({
  claim,
  source,
  className = "",
}: {
  claim: ReactNode;
  source: ReactNode;
  className?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const claimRef = useRef<HTMLDivElement>(null);
  const sourceRef = useRef<HTMLDivElement>(null);
  const [path, setPath] = useState<{ d: string; y1: number } | null>(null);

  useLayoutEffect(() => {
    const el = root.current;
    const c = claimRef.current;
    const s = sourceRef.current;
    if (!el || !c || !s) return;
    const measure = () => {
      const y1 = c.offsetTop + Math.min(10, c.offsetHeight / 2);
      const y2 = s.offsetTop + Math.min(11, s.offsetHeight / 2);
      setPath({ d: `M 6 ${y1} L 6 ${Math.max(y1, y2 - 7)} Q 6 ${y2} 13 ${y2}`, y1 });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={root} className={`evidence-thread relative pl-5 ${className}`}>
      {path && (
        <svg
          aria-hidden
          className="pointer-events-none absolute left-0 top-0 h-full w-5 overflow-visible"
        >
          <path className="et-base" d={path.d} />
          <path className="et-draw" d={path.d} pathLength={1} />
          <circle className="et-dot" cx={6} cy={path.y1} r={2.75} />
        </svg>
      )}
      <div ref={claimRef}>{claim}</div>
      <div ref={sourceRef} className="et-source mt-1.5 rounded-md">
        {source}
      </div>
    </div>
  );
}
