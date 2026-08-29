"use client";

/**
 * The six sections below the hero.
 *
 * 01 The finding      the research that gives the product its reason
 * 02 The standards    the framework library assembling
 * 03 The reading      the analysis screen taking its eight readings
 * 04 The proof        the auditor answering, with the citation behind it
 * 05 The method       the four stages of a run
 * 06 The close        one call to action
 *
 * The standards come before the readings on purpose: a visitor has to know
 * what a policy is being measured AGAINST before a verdict on it means
 * anything.
 *
 * Sections 02 to 05 are the product animating itself rather than
 * screenshots of it: crisp at any resolution, no image payload, and no
 * layout shift while they load. Copy is authored in
 * docs/landing-design-package.md and ships verbatim.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import MeridianMark from "@/components/MeridianMark";
import {
  AnalysisFrame,
  AuditorFrame,
  FrameworksFrame,
} from "@/components/ProductFrames";
import PipelineStages from "@/components/PipelineStages";
import { RollWords, TypeLine } from "@/components/TextEffects";

/* ── Seeing an element ────────────────────────────────────────────────────
   Scroll listeners with a 500ms rect poll behind them, NOT an
   IntersectionObserver. IO callbacks do not fire reliably in embedded
   webviews that stop compositing, and this hook gates whether content is
   visible at all: a missed callback leaves a whole section pinned at
   opacity zero, which is the one failure this page must not have. Timers
   keep firing in those environments, so the poll always rescues it.

   Measured directly: with IO, all three product screens rendered their full
   content at the right size and stayed invisible. */
function useSeen<T extends HTMLElement>(margin = 100) {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      /* Fail OPEN when the viewport cannot be measured. A hidden or
         non-composited pane reports innerHeight 0, and comparing against
         that makes every element permanently "not seen", which hides the
         whole page. Unmeasurable means show it. */
      if (!vh) {
        setSeen(true);
        return;
      }
      setSeen(r.top < vh - margin && r.bottom > margin);
    };
    const poll = setInterval(check, 500);
    check();
    window.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
    return () => {
      clearInterval(poll);
      window.removeEventListener("scroll", check);
      window.removeEventListener("resize", check);
    };
  }, [margin]);
  return { ref, seen };
}

/* The section entrance. Latches on first sight and never reverses, so a
   section the visitor has already read cannot fade back out under them.
   Entrance start and end states are both prefixed with the section class in
   CSS, so a later rule cannot win the cascade and strand an element. */
function useReveal<T extends HTMLElement>() {
  const { ref, seen } = useSeen<T>(40);
  const done = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || done.current) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.classList.add("in", "done");
      done.current = true;
      return;
    }
    if (!seen) return;
    done.current = true;
    el.classList.add("in");
    // Retire the stagger delays once the entrance is done, or every hover
    // on a later sibling lags by its entrance delay forever.
    const t = setTimeout(() => el.classList.add("done"), 2200);
    return () => clearTimeout(t);
  }, [ref, seen]);
  return ref;
}

/* ── 01 The finding ──────────────────────────────────────────────────────
   The OECD result, drawn rather than written. Three rungs of the same
   ladder the product scores on, each one harder to reach than the last.
   The proportions are qualitative because the source is: it reports most,
   about half, and a minority, so the bars carry those words rather than
   invented percentages. */
const RUNGS = [
  {
    qty: "Most",
    text: "define specific actions and set goals.",
    fill: "88%",
    gap: false,
  },
  {
    qty: "About half",
    text: "establish funding, or name who is responsible for delivering it.",
    fill: "50%",
    gap: false,
  },
  {
    qty: "A minority",
    text: "set an implementation timeframe for any of it.",
    fill: "19%",
    gap: true,
  },
];

function Finding() {
  const ref = useReveal<HTMLElement>();
  return (
    <section className="l-sec l-finding" ref={ref}>
      <div className="l-finding-head">
        <p className="l-label">01 / The finding</p>
        <RollWords
          as="h2"
          className="l-finding-lede"
          text="The OECD read the world’s national AI strategies."
          stagger={70}
        />
      </div>

      <ol className="l-ladder">
        {RUNGS.map((r) => (
          <li key={r.qty} className={`l-rung${r.gap ? " is-gap" : ""}`}>
            <RollWords className="l-rung-qty" text={r.qty} stagger={0} />
            <div className="l-rung-body">
              <p className="l-rung-text">{r.text}</p>
              <div className="l-rung-bar">
                <span
                  className="l-rung-fill"
                  style={{ width: r.fill }}
                  aria-hidden
                />
              </div>
            </div>
          </li>
        ))}
      </ol>

      <div className="l-finding-note">
        <p className="l-finding-kicker">
          A promise nobody has to keep by any particular date is not a plan.{" "}
          <span className="l-mark">That distance is what Meridian measures.</span>
        </p>
        <p className="l-finding-source">
          <a
            href="https://www.oecd.org/en/publications/governing-with-artificial-intelligence_26324bc2-en.html"
            target="_blank"
            rel="noreferrer noopener"
            className="l-link"
          >
            OECD, Governing with Artificial Intelligence
          </a>
        </p>
      </div>
    </section>
  );
}

/* ── 02 The reading ────────────────────────────────────────────────────── */
function Reading() {
  const ref = useReveal<HTMLElement>();
  const frame = useSeen<HTMLDivElement>();
  return (
    <section className="l-sec l-split is-reverse" ref={ref}>
      <div className="l-split-copy">
        <p className="l-label">03 / The reading</p>
        <RollWords as="h2" className="l-display l-h2" text="Eight dimensions, read at once." />
        <p className="l-body">
          Transparency. Accountability. Privacy. Safety. Human autonomy.
          Inclusivity. Fairness. Environmental sustainability. Each one gets a
          coverage verdict, a maturity stage, and the binding force behind it,{" "}
          <span className="l-mark">scored on evidence rather than intent</span>.
        </p>
      </div>
      <div className="l-split-visual" ref={frame.ref}>
        <AnalysisFrame active={frame.seen} />
      </div>
    </section>
  );
}

/* ── 03 The proof ──────────────────────────────────────────────────────── */
function Proof() {
  const ref = useReveal<HTMLElement>();
  const frame = useSeen<HTMLDivElement>();
  const head = useSeen<HTMLDivElement>(60);
  return (
    <section className="l-sec l-split" ref={ref}>
      <div className="l-split-copy" ref={head.ref}>
        <p className="l-label">04 / The proof</p>
        {/* The one line on the page that types. This section is about
            putting a question to the instrument, so the heading is written
            the way the visitor would write it. */}
        <TypeLine
          as="h2"
          className="l-display l-h2"
          text="Ask it why. It cites the paragraph."
          active={head.seen}
        />
        <p className="l-body">
          Every finding can be questioned in plain language, and{" "}
          <strong>every answer comes back with the framework text it rests
          on</strong>. A governance tool that cannot show its working is an
          opinion with a score attached.
        </p>
      </div>
      <div className="l-split-visual" ref={frame.ref}>
        <AuditorFrame active={frame.seen} />
      </div>
    </section>
  );
}

/* ── 04 The standards ──────────────────────────────────────────────────── */
function Standards() {
  const ref = useReveal<HTMLElement>();
  const frame = useSeen<HTMLDivElement>();
  return (
    <section className="l-sec l-standards" ref={ref}>
      <div className="l-standards-head">
        <p className="l-label">02 / The standards</p>
        <RollWords
          as="h2"
          className="l-display l-h2"
          text="Not our opinion of good governance. Theirs."
        />
        <p className="l-body">
          UNESCO, the OECD, UNDP, the G7 Hiroshima process, the EU AI Act, NIST,
          and the UN digital compacts, at the versions named beside them.{" "}
          <strong>The roster is configuration, not code</strong>, so it moves as
          the frameworks do.
        </p>
      </div>
      <div className="l-standards-visual" ref={frame.ref}>
        <FrameworksFrame active={frame.seen} />
      </div>
    </section>
  );
}

/* ── 05 The method ─────────────────────────────────────────────────────── */
function Method() {
  const ref = useReveal<HTMLElement>();
  return (
    <section className="l-sec l-method" ref={ref}>
      <div className="l-method-head">
        <p className="l-label">05 / The method</p>
        <RollWords
          as="h2"
          className="l-display l-h2"
          text="Four steps, and every one leaves a trail."
        />
      </div>
      <PipelineStages />
    </section>
  );
}

/* ── 06 The close ──────────────────────────────────────────────────────── */
function Close() {
  const ref = useReveal<HTMLElement>();
  return (
    <section className="l-sec l-close" ref={ref}>
      <MeridianMark size={48} className="l-close-mark" />
      <RollWords
        as="h2"
        className="l-display l-close-h"
        text="You already have the document. Find out how deep it goes."
        stagger={48}
      />
      <div className="l-close-cta">
        <Link href="/workspace" className="l-btn l-btn-primary">
          Benchmark your policy
        </Link>
        <Link href="/analysis" className="l-btn l-btn-quiet">
          See a finished analysis
        </Link>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="l-footer">
      <div className="l-footer-inner">
        <span className="l-label">Meridian</span>
        <span className="l-label">AI Governance Intelligence Workbench</span>
        <nav className="l-footer-nav" aria-label="Product">
          <Link href="/workspace" className="l-link">Workspace</Link>
          <Link href="/analysis" className="l-link">Analysis</Link>
          <Link href="/frameworks" className="l-link">Frameworks</Link>
          <Link href="/auditor" className="l-link">Auditor</Link>
        </nav>
      </div>
    </footer>
  );
}

export default function LandingSections() {
  return (
    <>
      <Finding />
      <Standards />
      <Reading />
      <Proof />
      <Method />
      <Close />
      <Footer />
    </>
  );
}
