"use client";

/**
 * InkSections — the two dark chapters that carry the project's own record.
 *
 * Every number and every claim on these two surfaces is lifted verbatim from
 * the repository's measured table in README.md. Nothing here is estimated,
 * rounded for effect, or written to sound impressive: a page whose whole
 * argument is "no claim without a citation" cannot put an unsourced figure
 * on its own landing page, so each card names where its number comes from.
 *
 * Two chapters, not one, because they answer two different questions:
 *
 *   Proof   — does the thing actually work, under load, in CI?
 *   Method  — why should a verdict it produces be trusted?
 *
 * They sit on `ink` because the route alternates surface to mark a change of
 * subject, and both are the page speaking about itself rather than about the
 * reader's document.
 *
 * The Proof grid is six columns carrying five cells as 3 + 3 over 2 + 2 + 2.
 * That is the only split of five across six that fills two rows exactly: the
 * first arrangement tried was 6 + 2 + 2 + 2, which left a single cell alone
 * on a third row with four empty columns beside it — a dead corner, and the
 * most common way a grid like this fails.
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

type Proof = {
  figure: string;
  unit?: string;
  claim: string;
  source: string;
  span: string;
};

/* All five are from README.md's "Measured" table. */
const PROOF: Proof[] = [
  {
    figure: "4.9",
    unit: "s",
    claim:
      "Median end-to-end latency on a replayed run, p95 at 6.9 seconds, across which the API returned zero server errors.",
    source: "replay harness",
    span: "l-ink-cell-half",
  },
  {
    figure: "36",
    claim:
      "Requests refused outright with a 429 while 45 were admitted. Work is never silently queued — the system says no rather than pretending.",
    source: "load test",
    span: "l-ink-cell-half",
  },
  {
    figure: "0",
    claim:
      "Fixable HIGH and CRITICAL vulnerabilities left in the production image, all closed at source. The .trivyignore file is empty.",
    source: "Trivy, per release",
    span: "",
  },
  {
    figure: "1,889",
    unit: "MB",
    claim:
      "Production image, down from 5,683. The release pipeline that builds it runs in about four minutes, down from twenty-two.",
    source: "CI, per release",
    span: "",
  },
  {
    figure: "238",
    claim:
      "Packages in the SPDX 2.3 software bill of materials attached to every single release, not just tagged ones.",
    source: "SBOM",
    span: "",
  },
];

type Method = { n: string; title: string; body: string };

/* The four guarantees, from the anti-fabrication section of README.md. */
const METHOD: Method[] = [
  {
    n: "R1",
    title: "The explicit-commitment floor",
    body: "A raw Missing verdict only stands when the document genuinely says nothing. If a commitment exists in the text, the verdict has to account for it.",
  },
  {
    n: "R2",
    title: "The implementation raise",
    body: "Partial is raised deterministically when implementation commitments are present — in code, on evidence, not at the model's discretion.",
  },
  {
    n: "0–5",
    title: "Six depth levels",
    body: "From No Governance Intent to Continuous Improvement. A fixed scale means two analyses of two countries are actually comparable.",
  },
  {
    n: "88.7%",
    title: "Citations checked verbatim",
    body: "Every excerpt is verified to appear word for word in the chunk it cites. A citation that cannot be found is not shown.",
  },
];

export function ProofBand() {
  const { ref, seen } = useSeen<HTMLElement>();
  return (
    <section
      ref={ref}
      data-surface="ink"
      className={`l-ink l-ink-proof${seen ? " is-on" : ""}`}
      aria-labelledby="proof-h"
    >
      <div className="l-ink-inner">
        <header className="l-ink-head">
          <h2 id="proof-h" className="l-ink-h">
            Measured, not claimed.
          </h2>
          <p className="l-ink-lede">
            Every figure below is in the repository, produced by a run anyone
            can repeat. Where a number has not been measured, the table says
            so instead of estimating.
          </p>
        </header>
        <div className="l-ink-grid">
          {PROOF.map((p, i) => (
            <article
              key={p.figure + p.source}
              className={`l-ink-cell ${p.span}`}
              style={{ ["--i" as string]: i }}
            >
              <p className="l-ink-fig">
                {p.figure}
                {p.unit ? <span className="l-ink-unit">{p.unit}</span> : null}
              </p>
              <p className="l-ink-claim">{p.claim}</p>
              <p className="l-ink-src">{p.source}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

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
            Four rules sit under every reading. They run in code, they run the
            same way every time, and they are the reason a score from Meridian
            can be argued with on the evidence.
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
