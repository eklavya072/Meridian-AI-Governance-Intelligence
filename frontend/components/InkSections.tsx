"use client";

/**
 * InkSections — the dark chapter that carries the project's own record.
 *
 * Every number and every claim on this surface is lifted verbatim from
 * the repository's measured table in README.md. Nothing here is estimated,
 * rounded for effect, or written to sound impressive: a page whose whole
 * argument is "no claim without a citation" cannot put an unsourced figure
 * on its own landing page, so each card names where its number comes from.
 *
 * Method answers the question the rest of the page raises: why should a
 * verdict it produces be trusted?
 *
 * It sits on `ink` because the route alternates surface to mark a change of
 * subject, and this is the page speaking about itself rather than about the
 * reader's document.
 */

import { useEffect, useRef, useState } from "react";
import StatsBand from "@/components/StatsBand";

/* Reveal, latched: once a section has been seen it stays shown, so a reader
   scrolling back up finds the cards where they left them rather than
   watching the whole grid re-enter. */
function useSeen<T extends HTMLElement>(margin = 0.82) {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    if (seen) return;
    const el = ref.current;
    if (!el) return;
    const check = () => {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      /* No measurable viewport means show the finished state, the same
         fail-open every other reveal on this route uses. */
      if (!vh) return setSeen(true);
      if (r.top < vh * margin && r.bottom > 0) setSeen(true);
    };
    check();
    window.addEventListener("scroll", check, { passive: true });
    /* Timers fire where scroll events are not delivered. */
    const poll = setInterval(check, 320);
    return () => {
      window.removeEventListener("scroll", check);
      clearInterval(poll);
    };
  }, [seen, margin]);
  return { ref, seen };
}

type Method = { n: string; title: string; body: string };

/* The four things that make a verdict defensible, as the scorer actually
   works. The citation rate is measured, not asserted: 318 of 330 evidence
   citations across the eight countries' showcase runs, 28 Sep 2026.
   Re-measure before changing it. */
const METHOD: Method[] = [
  {
    n: "T0-T4",
    title: "The normative-force ladder",
    body: "Every provision is graded from a stated value to a duty backed by a consequence, by who it binds, how firmly and with what penalty: the Abbott and Snidal legalization framework, applied provision by provision.",
  },
  {
    n: "0",
    title: "Verdicts the language model sets",
    body: "Coverage and depth are computed in code from counted, classified provisions. The language model is shown the verdict and explains it; it cannot set one, and cannot raise one.",
  },
  {
    n: "5",
    title: "Depth stages",
    body: "Unaddressed, Emerging, Delegated, Operationalized, Institutionalized. A fixed scale means two analyses of two countries are actually comparable.",
  },
  {
    n: "96%",
    title: "Citations confirmed at source",
    body: "Every quoted excerpt is checked against the passage it cites. One that cannot be confirmed is marked unverified, with the reason, rather than quietly kept.",
  },
];

export function MethodBand() {
  const { ref, seen } = useSeen<HTMLElement>();
  return (
    <section
      ref={ref}
      data-surface="ink"
      className={`l-ink l-ink-method${seen ? " is-on" : ""}`}
      aria-labelledby="method-h"
    >
      <div className="l-ink-inner">
        {/* The figures open the chapter, on white. Four light cards on the
            page's darkest surface is the only hard contrast on a route that
            otherwise moves in half-steps — and it puts the measurements
            where they belong, immediately before the rules that produced
            them. Numbers first, then why to believe them. */}
        <StatsBand />
        <header className="l-ink-head">
          <h2 id="method-h" className="l-ink-h">
            The verdict is not the model&rsquo;s opinion.
          </h2>
          <p className="l-ink-lede">
            Four rules sit under every reading. They run in code, the same way
            every time, which is what makes a score arguable on the evidence.
          </p>
        </header>
        <div className="l-ink-rules">
          {METHOD.map((m, i) => (
            <article
              key={m.n}
              className="l-ink-rule"
              style={{ ["--i" as string]: i }}
            >
              <span className="l-ink-rule-n">{m.n}</span>
              <h3 className="l-ink-rule-t">{m.title}</h3>
              <p className="l-ink-rule-b">{m.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
