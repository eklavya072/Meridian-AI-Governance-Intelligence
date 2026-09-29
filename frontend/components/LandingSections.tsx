"use client";

/**
 * The page below the hero.
 *
 *   The standards    the framework library assembling
 *   The reading      the analysis screen taking its eight readings
 *   The proof        the auditor answering, with the citation behind it
 *   The method       the four stages of a run
 *   The close        one call to action
 *
 * The first three travel sideways inside a pinned track; the last two
 * return to vertical. The standards come before the readings on purpose: a
 * visitor has to know what a policy is being measured AGAINST before a
 * verdict on it means anything.
 *
 * The OECD finding that used to open this file now plays over the hero
 * video instead, where it belongs — it is the reason the product exists,
 * and it was reading as just another section down here.
 *
 * Every panel is the product animating itself rather than a screenshot of
 * it: crisp at any resolution, no image payload, and no layout shift while
 * it loads. Copy is authored in docs/landing-design-package.md.
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
import HorizontalTrack from "@/components/HorizontalTrack";
import { MethodBand } from "@/components/InkSections";
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

/* Activation for a panel inside the horizontal track.
   The product frames hide their own contents until `active`, so whatever
   drives that flag must never be able to go false again once true, and must
   never depend on a measurement that can silently fail. This latches on the
   first of three independent signals: the panel is horizontally near the
   middle of the window, OR the viewport cannot be measured, OR two seconds
   have passed since it became vertically visible. The animation plays when
   the panel arrives; the content appears regardless. */
function usePanelActive<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [active, setActive] = useState(false);
  useEffect(() => {
    if (active) return;
    const el = ref.current;
    if (!el) return;
    let fallback: ReturnType<typeof setTimeout> | null = null;
    const check = () => {
      const r = el.getBoundingClientRect();
      const vw = window.innerWidth || document.documentElement.clientWidth;
      const vh = window.innerHeight || document.documentElement.clientHeight;
      if (!vw || !vh) {
        setActive(true);
        return;
      }
      const verticallyOn = r.top < vh && r.bottom > 0;
      if (!verticallyOn) return;
      if (fallback === null) fallback = setTimeout(() => setActive(true), 2000);
      const cx = r.left + r.width / 2;
      if (Math.abs(cx - vw / 2) < vw * 0.42) setActive(true);
    };
    const poll = setInterval(check, 200);
    check();
    window.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
    return () => {
      clearInterval(poll);
      if (fallback) clearTimeout(fallback);
      window.removeEventListener("scroll", check);
      window.removeEventListener("resize", check);
    };
  }, [active]);
  return { ref, active };
}

/* ── The track panels ────────────────────────────────────────────────────
   One shell for all three, because inside a pinned viewport they read as a
   single device rather than three sections, and three different layouts in
   a row is what made the track look unformatted. The composition alternates
   which side the screen sits on; everything else is identical.

   Text arrives with the panel: `active` latches when the panel reaches the
   middle of the window, and drives both the heading's word rise and the
   body's fade. */
function Panel({
  heading,
  body,
  visual,
  reverse = false,
  typed = false,
  active,
  innerRef,
}: {
  heading: string;
  body: React.ReactNode;
  visual: React.ReactNode;
  reverse?: boolean;
  typed?: boolean;
  active: boolean;
  innerRef?: React.Ref<HTMLDivElement>;
}) {
  /* A CSS transition needs frames to advance. Where they do not arrive the
     element keeps reporting its start value however the class list reads,
     which strands the body and the screen at opacity zero on an active
     panel. Measured here on the third panel. The settle asserts the
     finished state with the transition switched off. */
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    if (!active) return;
    const t = setTimeout(() => setSettled(true), 1200);
    return () => clearTimeout(t);
  }, [active]);

  return (
    <div
      className={`l-pane${reverse ? " is-reverse" : ""}${active ? " is-on" : ""}${
        settled ? " is-settled" : ""
      }`}
    >
      <div className="l-pane-copy">
        {typed ? (
          <TypeLine as="h2" className="l-display l-h2" text={heading} active={active} />
        ) : (
          <RollWords as="h2" className="l-display l-h2" text={heading} />
        )}
        <p className="l-body l-pane-body">{body}</p>
      </div>
      <div className="l-pane-visual" ref={innerRef}>
        {visual}
      </div>
    </div>
  );
}

function Standards() {
  const frame = usePanelActive<HTMLDivElement>();
  return (
    <Panel
      heading="Not our opinion of good governance. Theirs."
      body={
        <>
          UNESCO, the OECD, UNDP, the G7 Hiroshima process, the EU AI Act,
          NIST and the UN digital compacts, at the versions named beside
          them. <strong>The roster is configuration, not code</strong>, so it
          moves as the frameworks do.
        </>
      }
      visual={<FrameworksFrame active={frame.active} />}
      active={frame.active}
      innerRef={frame.ref}
    />
  );
}

function Reading() {
  const frame = usePanelActive<HTMLDivElement>();
  return (
    <Panel
      reverse
      heading="Eight dimensions, read at once."
      body={
        <>
          Transparency. Accountability. Privacy. Safety. Human autonomy.
          Inclusivity. Fairness. Environmental sustainability. Each one gets a
          coverage verdict, a depth stage and the binding force behind it,{" "}
          <span className="l-mark">scored on evidence rather than intent</span>.
        </>
      }
      visual={<AnalysisFrame active={frame.active} />}
      active={frame.active}
      innerRef={frame.ref}
    />
  );
}

function Proof() {
  const frame = usePanelActive<HTMLDivElement>();
  return (
    <Panel
      typed
      heading="Ask it why. It cites the paragraph."
      body={
        <>
          Every finding can be questioned in plain language, and{" "}
          <strong>
            every answer comes back with the framework text it rests on
          </strong>
          .
        </>
      }
      visual={<AuditorFrame active={frame.active} />}
      active={frame.active}
      innerRef={frame.ref}
    />
  );
}

/* ── 05 The method ─────────────────────────────────────────────────────── */
function Method() {
  const ref = useReveal<HTMLElement>();
  return (
    <section className="l-sec l-method" data-surface="paper" ref={ref}>
      <div className="l-method-head">
        <RollWords
          as="h2"
          className="l-display l-method-h"
          text="Nothing is asserted. Everything is traced."
        />
        {/* The section had a heading and then four rows, with nothing to say
            why the four exist. This is the argument the stages are evidence
            for — and it is the one claim on the page a sceptical evaluator
            will actually test. */}
        <p className="l-body l-method-lede">
          A score you cannot audit is an opinion with a number on it. Each of
          the four stages below writes down what it did, so the brief at the
          end comes apart line by line: back through the reasoning, back to
          the paragraph it came from.
        </p>
      </div>
      <PipelineStages />
    </section>
  );
}

/* ── 06 The close ──────────────────────────────────────────────────────── */
function Close() {
  const ref = useReveal<HTMLElement>();
  return (
    <section className="l-sec l-close" data-surface="ink" ref={ref}>
      <MeridianMark size={48} className="l-close-mark" />
      {/* Two clauses, so two lines — stated, not left to `text-wrap: balance`
          to guess at. Balance was splitting one sentence across two ragged
          parts that broke mid-clause and shared no edge; the sentence has a
          full stop in the middle of it, and that is where a reader expects
          the break. The second line takes the accent, the way the hero's
          turn does. */}
      <h2 className="l-display l-close-h">
        <RollWords as="span" className="l-close-line" text="You already have the AI governance framework." stagger={48} />
        <RollWords as="span" className="l-close-line l-close-turn" text="Find out how deep it goes." stagger={48} />
      </h2>
      <div className="l-close-cta">
        <Link href="/workspace" className="l-btn l-btn-primary">
          Benchmark your AI governance
        </Link>
        <Link href="/analysis" className="l-btn l-btn-quiet">
          See a finished analysis
        </Link>
      </div>
    </section>
  );
}

const REPO = "https://github.com/eklavya072/Meridian-AI-Governance-Intelligence";

function Footer() {
  return (
    <footer className="l-footer" data-surface="paper-mid">
      <div className="l-footer-inner">
        {/* The mark in gold, at the size a colophon takes it. It opens the
            close above and it closes the page here, and those are the only
            two places on the route it appears. */}
        <MeridianMark size={13} className="l-footer-mark" />
        <span>Meridian</span>
        <span>AI Governance Intelligence Workbench</span>
        <nav className="l-footer-nav" aria-label="Product">
          <Link href="/workspace" className="l-link">Workspace</Link>
          <Link href="/analysis" className="l-link">Analysis</Link>
          <Link href="/frameworks" className="l-link">Frameworks</Link>
          <Link href="/auditor" className="l-link">Auditor</Link>
          <a
            href={REPO}
            className="l-footer-gh"
            target="_blank"
            rel="noreferrer noopener"
          >
            {/* Drawn, not an emoji or a glyph standing in for one. */}
            <svg viewBox="0 0 16 16" aria-hidden>
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.4 7.4 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
            </svg>
            Source
          </a>
        </nav>
      </div>
    </footer>
  );
}

export default function LandingSections() {
  return (
    <>
      {/* The argument's middle travels sideways: the standards a policy is
          measured against, the reading taken, then the working shown.
          Scrolling down still means moving forward, which is the only thing
          that makes the device worth using — it borrows the hero's grammar
          so the middle of the page reads as one continuous move rather than
          three stacked sections.

          Below 1024px, on portrait touch screens, and under reduced motion
          this is not a track at all: the panels stack and the page behaves
          exactly as it did before. */}
      <HorizontalTrack
        panels={[
          { key: "standards", node: <Standards /> },
          { key: "reading", node: <Reading /> },
          { key: "proof", node: <Proof /> },
        ]}
      />
      {/* One dark chapter between the two light ones, and it does two jobs
          in a deliberate order: the figures first, on white cards, then the
          rules that produced them. Numbers, then why to believe them.

          The white cards are the point of putting it here. A dark section
          whose contents are dark is a change of paint; a dark section
          holding light cards is a change of PLACE, and it is the only hard
          contrast on a page that otherwise moves in half-steps. */}
      <MethodBand />
      {/* Then back to paper for the procedure, which is where a procedure
          belongs. */}
      <Method />
      {/* The last dark chapter answers the question the method raises —
          why trust the verdict — and hands straight to the close, so the
          page ends on one continuous dark passage rather than flickering
          between surfaces twice more. */}
      <Close />
      <Footer />
    </>
  );
}
