"use client";

/**
 * ProductFrames — the landing page's product screens, as short loops.
 *
 * Three faithful, LIVE recreations of the real screens, rendered as
 * bezelled panels rather than captured stills:
 *
 *   AnalysisFrame   → /analysis   the coverage donut fills, the depth
 *                                 gauge sweeps, the dimension verdicts pop
 *                                 in one after another
 *   AuditorFrame    → /auditor    the question types itself into the
 *                                 composer, sends, the auditor thinks, then
 *                                 the grounded answer types out and its
 *                                 verified-sources chip lands
 *   FrameworksFrame → /frameworks the framework cards (UNDP, OECD, G7
 *                                 Hiroshima, UNESCO, EU AI Act, NIST …)
 *                                 land in sequence
 *
 * They are built from the same tokens the real pages use — the light
 * surface and the black/grey scale — so what the landing page shows is what
 * the product actually looks like, at any DPI, with no image payload and no
 * layout shift.
 *
 * The coverage scale is the app's own: green, gold, red for Covered,
 * Partial, Missing. These frames are a picture of the product, so they show
 * what the product shows. The one accent rule governs the PAGE — its
 * headlines, its marks, its indicators — not a screenshot of software that
 * has its own established colour language.
 *
 * Each frame takes `active` (is it on screen) and `runId` (bumped on every
 * scroll-in). `runId` is used as a React key so the whole sequence
 * remounts and replays from the top every time the reader comes back to
 * it, and nothing animates while the frame is off screen.
 *
 * Sequencing is driven by setTimeout/setInterval rather than by chains of
 * delayed motion transitions: timers still fire when requestAnimationFrame
 * stalls (a backgrounded tab, or one of the embedded webviews this app
 * already works around), so a stalled frame resumes correctly instead of
 * stranding half its content at opacity 0.
 *
 * Every frame is aria-hidden: it is product imagery. The surrounding
 * section carries the real heading and description for screen readers.
 */

import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { EASE } from "@/lib/motion";

/* ── Panel ─────────────────────────────────────────────────────────────
   The product surface itself, with rounded corners and a shadow. No bezel.

   This started as a translucent, backdrop-blurred frame around an inset
   screen, which put a ghostly ring of the moving background between the
   page and the content. The ring was the only thing on the page pretending
   to be a physical object, and it read as an artifact rather than as
   hardware. The surface now sits directly on the page: one radius, one
   shadow, nothing floating around the edge. */

export function ScreenPanel({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      aria-hidden
      /* The shadow, rebuilt rather than removed.
         It was one layer: `0 28px 80px -12px rgba(0,0,0,0.7)`. A single
         huge, near-opaque blur is what made it read as a bloom trailing the
         panel instead of as the panel sitting above the page — and taking
         it away left a flat rectangle with a hard edge against a background
         of nearly the same value, which is worse.

         Three layers instead, the way real elevation falls off: a hairline
         contact shadow, a short ambient one, and a long soft cast. Total
         alpha is a fraction of what it was, and the panel reads as glass
         over parchment rather than a dark cloud.

         The glass is three things together, not a blur alone: the layered
         cast underneath, an inset white ring for the lit top edge a pane of
         glass catches, and 2px of backdrop blur so the parchment grain
         behind it softens at the boundary. Blur on its own is the
         decoration version of this effect; it is the ring and the cast that
         make it read as a physical object above a surface. */
      className={`w-full overflow-hidden rounded-2xl border border-[rgba(10,10,10,0.08)] bg-[#F5F5F5] shadow-[0_1px_2px_rgba(16,18,22,0.07),0_8px_20px_-8px_rgba(16,18,22,0.13),0_32px_64px_-28px_rgba(16,18,22,0.20)] ring-1 ring-inset ring-white/45 backdrop-blur-[2px] ${className}`}
    >
      {children}
    </div>
  );
}

/* Muted coverage tokens — identical to the analysis page's TIER_DOT. */
/* The instrument's own three verdicts, in the instrument's own colours.
   These were flattened to a gold ramp when the landing route went down to
   one accent — which was right for the page's argument and wrong for this
   one component, because these screens are a PICTURE OF THE PRODUCT. The
   real /analysis draws Covered, Partial and Missing in green, gold and red;
   a recreation that draws them in three browns is a recreation of something
   that does not exist. Values are `--chart-*` verbatim. */
const COVERED = "#3F7A52";
const PARTIAL = "#B08114";
const MISSING = "#A8483F";

function Dot({ color }: { color: string }) {
  return (
    <span
      className="h-1.5 w-1.5 shrink-0 rounded-full"
      style={{ background: color }}
    />
  );
}

/** Steps a counter 0→steps while `active`, pausing when it goes off screen. */
/**
 * Advances 0..steps once `active`, one step every `everyMs`.
 *
 * The chain of per-step timeouts is the nice version of this; the deadline
 * beside it is the one that has to hold. A backgrounded or non-composited
 * tab clamps repeat timers to roughly a second, so an eight-step sequence
 * authored at 190ms becomes an eight-SECOND sequence there, and anything
 * waiting on the chain to finish waits that long with content still at
 * opacity zero.
 *
 * The deadline is a single timeout armed once, for the whole budget, and a
 * lone long timeout is not subject to that clamp. So the sequence animates
 * when the page can animate and simply arrives when it cannot — which is
 * the rule this whole route is built on. Measured: without it, four of
 * eight framework cards were still invisible four seconds in.
 */
function useSequence(active: boolean, steps: number, everyMs: number) {
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!active) return;
    if (step >= steps) return;
    const t = setTimeout(() => setStep((s) => s + 1), everyMs);
    return () => clearTimeout(t);
  }, [active, step, steps, everyMs]);

  useEffect(() => {
    if (!active) {
      setStep(0);
      return;
    }
    const deadline = setTimeout(
      () => setStep(steps),
      steps * everyMs + 900,
    );
    return () => clearTimeout(deadline);
  }, [active, steps, everyMs]);

  return step;
}

/**
 * True once a sequence has finished AND its last transition has had time to
 * run. Callers use it to drop the transition entirely, which is what makes
 * the finished state hold: a CSS transition needs frames to advance, and a
 * paused compositor leaves the element reporting its START value forever
 * even though the style says otherwise. With no transition there is nothing
 * standing between the value and the pixel.
 */
function useSettled(done: boolean, afterMs = 600) {
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    if (!done) {
      setSettled(false);
      return;
    }
    const t = setTimeout(() => setSettled(true), afterMs);
    return () => clearTimeout(t);
  }, [done, afterMs]);
  return settled;
}

/* ── 1. Analysis ──────────────────────────────────────────────────────
   The governance analysis screen: the Decision Analytics card (coverage
   donut + implementation-depth gauge) above the dimension verdicts, which
   land one at a time the way they do as the real page streams in. */

/* Coverage verdicts and depth stages are the instrument's own, not
   generic capability-model words: coverage is Covered / Partial / Missing,
   and depth runs Unaddressed, Emerging, Delegated, Operationalized,
   Institutionalized. The spread below is a real run. */
const ANALYSIS_ROWS = [
  { dim: "Transparency", tier: "Covered", color: COVERED, depth: "Operationalized", cites: 6 },
  { dim: "Accountability", tier: "Covered", color: COVERED, depth: "Institutionalized", cites: 6 },
  { dim: "Privacy", tier: "Covered", color: COVERED, depth: "Institutionalized", cites: 5 },
  { dim: "Fairness", tier: "Partial", color: PARTIAL, depth: "Emerging", cites: 6 },
  { dim: "Environmental", tier: "Missing", color: MISSING, depth: "Unaddressed", cites: 4 },
];

/* 5 covered / 2 partial / 1 missing across the 8 dimensions — India's run of
   22 Sep 2026, the one ANALYSIS_ROWS and the gauge are also taken from. */
const DONUT = [
  { label: "Covered", value: 5, color: COVERED },
  { label: "Partial", value: 2, color: PARTIAL },
  { label: "Missing", value: 1, color: MISSING },
];

function CoverageDonut({ active }: { active: boolean }) {
  const total = DONUT.reduce((s, d) => s + d.value, 0);
  /* The three arcs land one after another, sequenced by a timer rather
     than by `delay` on each transition. A delayed motion transition only
     starts once the frame loop reaches it, so on a throttled tab the later
     arcs never drew at all and the donut sat empty next to a legend that
     said three, three and two. Stepping the TARGET from a timer means the
     ring always ends up correct, whatever the frame loop does. */
  const seg = useSequence(active, DONUT.length, 420);
  let offset = 0;
  return (
    <div className="flex items-center gap-4">
      {/* Plain stroke-dash arithmetic on a normalised path, with the value
          written straight from the sequence step and a CSS transition for
          the growth. The motion equivalent animated pathLength, which needs
          the frame loop to finish: on a throttled tab the arcs stopped
          part-drawn beside a legend and a readout that both said otherwise.
          Here the geometry is whatever the step says it is, so the ring can
          never disagree with the numbers next to it. */}
      <svg viewBox="0 0 90 90" className="h-[74px] w-[74px] shrink-0 -rotate-90">
        <circle cx="45" cy="45" r="34" fill="none" stroke="#E8E8E8" strokeWidth="13" />
        {DONUT.map((d, i) => {
          const frac = d.value / total;
          const drawn = i < seg ? frac : 0;
          const el = (
            <circle
              key={d.label}
              cx="45"
              cy="45"
              r="34"
              fill="none"
              stroke={d.color}
              strokeWidth="13"
              pathLength={1}
              strokeDasharray="1"
              style={{
                strokeDashoffset: 1 - drawn,
                transformOrigin: "45px 45px",
                transform: `rotate(${offset * 360}deg)`,
                transition: "stroke-dashoffset 450ms cubic-bezier(0.22,1,0.36,1)",
              }}
            />
          );
          offset += frac;
          return el;
        })}
      </svg>
      <ul className="min-w-0 space-y-1.5">
        {DONUT.map((d, i) => (
          <li
            key={d.label}
            style={{
              opacity: i < seg ? 1 : 0,
              transition: "opacity 300ms cubic-bezier(0.22,1,0.36,1)",
            }}
            className="flex items-center gap-2 text-[11px] font-medium text-[#0A0A0A]"
          >
            <Dot color={d.color} />
            <span className="truncate">{d.label}</span>
            <span className="ml-auto tabular-nums text-[#737373]">{d.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DepthGauge({ active }: { active: boolean }) {
  /* The index is a mean of stage scores over the assessed dimensions, on 0
     to 100. It was previously drawn as x/5, which is a scale this
     instrument does not have. The arc and the readout share one value so
     they can never disagree. */
  const target = 67.0;
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (!active) {
      setShown(0);
      return;
    }
    const start = Date.now();
    const dur = 1400;
    const id = setInterval(() => {
      const p = Math.min(1, (Date.now() - start) / dur);
      /* Same deceleration as EASE.out, so the digits settle with the arc. */
      setShown(target * (1 - Math.pow(1 - p, 3)));
      if (p >= 1) clearInterval(id);
    }, 40);
    /* The count-up is decoration; the number is information. A throttled
       timer (a background tab clamps intervals to about a second) would
       otherwise leave the readout reporting 0.0 next to a drawn arc. This
       lands the true value regardless of how many ticks actually fired. */
    const settle = setTimeout(() => setShown(target), dur + 400);
    return () => {
      clearInterval(id);
      clearTimeout(settle);
    };
  }, [active]);

  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 100 60" className="h-[74px] w-[112px] shrink-0">
        <path d="M10 50 A40 40 0 0 1 90 50" fill="none" stroke="#E8E8E8" strokeWidth="8" strokeLinecap="round" />
        {/* The arc is drawn from the SAME value the readout prints, so the
            needle and the number are one quantity rather than two things
            animating separately toward the same answer. `shown` already
            lands on target from its settle timer, which makes the arc
            fail-safe for free. */}
        <path
          d="M10 50 A40 40 0 0 1 90 50"
          fill="none"
          stroke="#0A0A0A"
          strokeWidth="8"
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray="1"
          style={{ strokeDashoffset: 1 - shown / 100 }}
        />
      </svg>
      <div className="min-w-0">
        <p className="font-display text-2xl font-bold leading-none tabular-nums text-[#0A0A0A]">
          {shown.toFixed(1)}
        </p>
        <p className="mt-1 text-[11px] font-medium text-[#404040]">of 100</p>
        <p className="text-[10px] text-[#737373]">Mean of stage scores, 8 dimensions</p>
      </div>
    </div>
  );
}

export function AnalysisFrame({ active }: { active: boolean }) {
  /* The verdicts land after the charts have drawn — the same order the real
     page fills in. One row every 320ms. */
  const rows = useSequence(active, ANALYSIS_ROWS.length, 320);
  return (
    <ScreenPanel>
      <div className="space-y-3 p-3.5 sm:space-y-4 sm:p-5">
        <div className="flex items-center gap-3">
          <div aria-hidden className="w-12 shrink-0 sm:w-16" />
          <div className="min-w-0 flex-1 text-center">
            <h3 className="font-display text-base font-extrabold tracking-tight text-[#0A0A0A] sm:text-xl">
              Governance Analysis
            </h3>
            {/* This read "Kenya. National AI Strategy 2025-2030" over a
                verdict spread, donut split and depth score that are a
                REAL RUN ON A DIFFERENT COUNTRY — India's. Kenya has
                published a strategy of that name, so the frame attributed
                one state's governance grade to another, on a page whose
                stated position is that nothing is asserted without a source.
                The label is now unattributed and the frame is marked
                illustrative in the UI, not only in a code comment. */}
            <p className="mt-0.5 truncate text-[10px] font-medium text-[#404040] sm:text-[11px]">
              Sample analysis · figures from a recorded run
            </p>
          </div>
          <span className="shrink-0 rounded-lg border border-[rgba(10,10,10,0.14)] px-2.5 py-1.5 text-[10px] font-medium text-[#404040] sm:text-[11px]">
            Illustrative
          </span>
        </div>

        <div className="rounded-xl border border-[rgba(10,10,10,0.10)] bg-white p-3 sm:p-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="font-display text-[12px] font-bold text-[#0A0A0A] sm:text-sm">
              Decision Analytics
            </p>
            <span className="text-[9px] font-semibold uppercase tracking-[0.16em] text-[#737373]">
              Dashboard-ready
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-[rgba(10,10,10,0.10)] bg-white p-3">
              <p className="mb-2 text-[9px] font-semibold uppercase tracking-[0.16em] text-[#737373]">
                Coverage Distribution
              </p>
              <CoverageDonut active={active} />
            </div>
            <div className="hidden rounded-lg border border-[rgba(10,10,10,0.10)] bg-white p-3 sm:block">
              <p className="mb-2 text-[9px] font-semibold uppercase tracking-[0.16em] text-[#737373]">
                Binding Force
              </p>
              <DepthGauge active={active} />
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <p className="font-display text-[12px] font-semibold text-[#0A0A0A] sm:text-sm">
            Governance Dimensions
          </p>
          {ANALYSIS_ROWS.map((r, i) => (
            <motion.div
              key={r.dim}
              initial={{ opacity: 0, y: 10, scale: 0.98 }}
              animate={
                i < rows
                  ? { opacity: 1, y: 0, scale: 1 }
                  : { opacity: 0, y: 10, scale: 0.98 }
              }
              transition={{ duration: 0.32, ease: EASE.out }}
              className="flex items-center gap-2.5 rounded-lg border border-[rgba(10,10,10,0.10)] bg-white px-3 py-2.5"
            >
              <span className="min-w-0 flex-1 truncate font-display text-[12px] font-bold text-[#0A0A0A] sm:text-[13px]">
                {r.dim}
              </span>
              <span className="hidden items-center gap-1.5 text-[10px] font-medium text-[#404040] sm:flex">
                <Dot color={r.color} />
                {r.tier}
              </span>
              <span className="hidden rounded-full border border-[rgba(10,10,10,0.12)] px-2 py-0.5 text-[9px] font-medium text-[#404040] md:inline">
                {r.depth}
              </span>
              <span className="flex shrink-0 items-center gap-1 text-[10px] font-medium text-[#3F7A52]">
                <CheckGlyph className="h-3 w-3" />
                {r.cites}
              </span>
              <span className="sm:hidden">
                <Dot color={r.color} />
              </span>
            </motion.div>
          ))}
        </div>
      </div>
    </ScreenPanel>
  );
}

function CheckGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="m4 12 5.5 5.5L20 6.5" />
    </svg>
  );
}

/* ── 2. AI Auditor ────────────────────────────────────────────────────
   The whole exchange, played out: the question types itself into the
   composer, sends, the auditor thinks, then the grounded answer types out
   and its verified-sources chip lands. Loops. */

const AUDITOR_Q = "How does the G7 Hiroshima process handle safety?";

/* The answer, in segments so the bold run survives the typewriter. */
const AUDITOR_A: { t: string; b?: boolean }[] = [
  { t: "The " },
  { t: "HAIP Reporting Framework", b: true },
  {
    t:
      " treats safety as a reporting duty, not a principle: organisations disclose risk identification, red-teaming results and incident handling on a recurring cycle: testing before deployment, monitoring after it.",
  },
];
const AUDITOR_A_LEN = AUDITOR_A.reduce((n, s) => n + s.t.length, 0);

/** Phases of the exchange. */
const TYPING = 0;
const SENT = 1;
const THINKING = 2;
const ANSWERING = 3;
const SOURCED = 4;

function useAuditorSequence(active: boolean) {
  const [phase, setPhase] = useState(TYPING);
  const [qChars, setQChars] = useState(0);
  const [aChars, setAChars] = useState(0);
  /* One interval drives the whole loop on a fixed tick, so a throttled tab
     resumes mid-exchange rather than losing the sequence. */
  const tick = useRef(0);

  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => {
      tick.current += 1;
      const t = tick.current;
      /* 40ms per tick. Question types over ~2s, holds, sends, thinks for
         ~1.2s, answers over ~3.4s, then rests before starting over. */
      const qEnd = AUDITOR_Q.length;
      const sendAt = qEnd + 12;
      const thinkEnd = sendAt + 30;
      const aEnd = thinkEnd + AUDITOR_A_LEN * 0.42;
      const restEnd = aEnd + 90;

      if (t <= qEnd) {
        setPhase(TYPING);
        setQChars(t);
      } else if (t <= sendAt) {
        setPhase(TYPING);
        setQChars(qEnd);
      } else if (t <= thinkEnd) {
        setPhase(t === sendAt + 1 ? SENT : THINKING);
        setQChars(0);
        setAChars(0);
      } else if (t <= aEnd) {
        setPhase(ANSWERING);
        setAChars(Math.round((t - thinkEnd) / 0.42));
      } else if (t <= restEnd) {
        setPhase(SOURCED);
        setAChars(AUDITOR_A_LEN);
      } else {
        tick.current = 0;
        setPhase(TYPING);
        setQChars(0);
        setAChars(0);
      }
    }, 40);
    return () => clearInterval(id);
  }, [active]);

  return { phase, qChars, aChars };
}

/** Renders the answer up to `chars`, keeping the bold run bold. */
function AnswerText({ chars }: { chars: number }) {
  let used = 0;
  return (
    <>
      {AUDITOR_A.map((seg, i) => {
        const take = Math.max(0, Math.min(seg.t.length, chars - used));
        used += seg.t.length;
        if (take === 0) return null;
        const slice = seg.t.slice(0, take);
        return seg.b ? (
          <strong key={i} className="font-semibold text-[#0A0A0A]">
            {slice}
          </strong>
        ) : (
          <span key={i}>{slice}</span>
        );
      })}
    </>
  );
}

export function AuditorFrame({ active }: { active: boolean }) {
  const { phase, qChars, aChars } = useAuditorSequence(active);
  const answered = phase >= ANSWERING;
  const showChip = phase === SOURCED;

  return (
    <ScreenPanel>
      <div className="flex flex-col gap-3 p-3.5 sm:p-5">
        <div className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5 rounded-full border border-[rgba(10,10,10,0.15)] bg-white px-2.5 py-1 text-[10px] font-medium text-[#404040]">
            <DocGlyph className="h-3 w-3 shrink-0 text-[#737373]" />
            <span className="truncate">rwanda_national_ai_policy.pdf</span>
          </span>
          <span className="shrink-0 text-[10px] font-medium text-[#5C5C5C]">
            AI Auditor
          </span>
        </div>

        {/* Conversation. Fixed min-height so the panel never resizes as the
            exchange plays — no layout shift on the page behind it. */}
        <div className="flex min-h-[188px] flex-col justify-end gap-2.5 sm:min-h-[212px]">
          {phase >= SENT && (
            <motion.div
              initial={{ opacity: 0, y: 10, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.3, ease: EASE.out }}
              className="flex justify-end"
            >
              <p className="max-w-[82%] rounded-2xl rounded-br-md bg-[#0A0A0A] px-3.5 py-2.5 text-[11px] leading-relaxed text-white sm:text-[12.5px]">
                {AUDITOR_Q}
              </p>
            </motion.div>
          )}

          {phase === THINKING && (
            <div className="flex justify-start">
              <span className="flex items-center gap-1 rounded-2xl rounded-bl-md border border-[rgba(10,10,10,0.10)] bg-white px-3.5 py-3">
                {/* A settling pulse, not a bounce. Tailwind's animate-bounce
                    rides a hard cubic-bezier(0.8,0,1,1) that reads as a toy
                    next to the rest of this page's motion. */}
                <span className="l-think h-1.5 w-1.5 rounded-full bg-[#404040]" />
                <span className="l-think h-1.5 w-1.5 rounded-full bg-[#404040] [animation-delay:180ms]" />
                <span className="l-think h-1.5 w-1.5 rounded-full bg-[#404040] [animation-delay:360ms]" />
              </span>
            </div>
          )}

          {answered && (
            <div className="flex justify-start">
              <div className="max-w-[88%] rounded-2xl rounded-bl-md border border-[rgba(10,10,10,0.10)] bg-white px-3.5 py-2.5">
                <p className="text-[11px] leading-relaxed text-[#404040] sm:text-[12.5px]">
                  <AnswerText chars={aChars} />
                  {phase === ANSWERING && (
                    <span className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] bg-[#0A0A0A]" />
                  )}
                </p>
                {showChip && (
                  <motion.span
                    initial={{ opacity: 0, scale: 0.7 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ type: "spring", stiffness: 480, damping: 26 }}
                    className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-[rgba(10,10,10,0.15)] bg-white px-2.5 py-1 text-[9.5px] font-medium text-[#404040]"
                  >
                    <Dot color={COVERED} />
                    Show 3 verified sources
                  </motion.span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Composer — the question is typed in here before it is sent. */}
        <div className="flex items-center gap-2 rounded-[24px] border border-[rgba(10,10,10,0.15)] bg-white p-1.5 pl-3">
          <PaperclipGlyph className="h-4 w-4 shrink-0 text-[#737373]" />
          <span className="min-w-0 flex-1 truncate text-[11px] sm:text-[12.5px]">
            {qChars > 0 ? (
              <span className="text-[#0A0A0A]">
                {AUDITOR_Q.slice(0, qChars)}
                <span className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] bg-[#0A0A0A]" />
              </span>
            ) : (
              <span className="text-[#737373]">Ask anything about this document…</span>
            )}
          </span>
          <motion.span
            animate={{ scale: qChars >= AUDITOR_Q.length ? [1, 0.9, 1] : 1 }}
            transition={{ duration: 0.3, ease: EASE.out }}
            className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#0A0A0A] text-white"
          >
            <ArrowUpGlyph className="h-3.5 w-3.5" />
          </motion.span>
        </div>
      </div>
    </ScreenPanel>
  );
}

function DocGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </svg>
  );
}

function PaperclipGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}

function ArrowUpGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M12 19V5" />
      <path d="m5 12 7-7 7 7" />
    </svg>
  );
}

/* ── 3. Framework library ─────────────────────────────────────────────
   The real roster from config/frameworks.yaml — names, issuing bodies and
   versions exactly as the library page lists them, landing card by card as
   the index reports in. No counts: the chunk figures that used to sit here
   were invented (OECD "1320" against 17 indexed), and a reader who opened the
   Frameworks page next would have caught it. */

const FRAMEWORKS = [
  { org: "UNDP", name: "Digital Strategy 2022-2025", version: "2022" },
  { org: "OECD", name: "AI Principles", version: "2024" },
  { org: "G7", name: "Hiroshima AI Process (HAIP)", version: "2023" },
  { org: "UNESCO", name: "Recommendation on the Ethics of AI", version: "2021" },
  { org: "EU", name: "AI Act, Regulation 2024/1689", version: "2024" },
  { org: "NIST", name: "AI Risk Management Framework", version: "1.0" },
  { org: "AU", name: "Continental AI Strategy", version: "2024" },
  { org: "ASEAN", name: "Guide on AI Governance & Ethics", version: "2024" },
];

export function FrameworksFrame({ active }: { active: boolean }) {
  const shown = useSequence(active, FRAMEWORKS.length, 190);
  const settled = useSettled(shown === FRAMEWORKS.length);
  return (
    <ScreenPanel>
      <div className="space-y-3 p-3.5 sm:space-y-4 sm:p-5">
        <div className="flex items-end justify-between gap-3">
          <div className="min-w-0">
            <h3 className="font-display text-base font-extrabold tracking-tight text-[#0A0A0A] sm:text-xl">
              Framework Library
            </h3>
            <p className="mt-0.5 text-[10px] font-medium text-[#404040] sm:text-[11px]">
              <span className="tabular-nums">{shown === FRAMEWORKS.length ? 44 : shown * 5}</span>{" "}
              instruments indexed, routed per dimension and region
            </p>
          </div>
          <span
            style={{
              opacity: shown === FRAMEWORKS.length ? 1 : 0,
              transition: settled ? "none" : "opacity 300ms var(--ease-enter)",
            }}
            className="hidden shrink-0 items-center gap-1.5 rounded-full border border-[rgba(10,10,10,0.12)] bg-white px-2.5 py-1 text-[10px] font-medium text-[#404040] sm:inline-flex"
          >
            <Dot color={COVERED} />
            All sources indexed
          </span>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:gap-2.5 lg:grid-cols-4">
          {/* Plain style writes with a CSS transition, not a motion animate.
              The motion version only advanced while the frame loop ran, so
              on a throttled tab the cards never arrived and the grid sat
              empty. The step comes from a timer, so the pop always plays. */}
          {FRAMEWORKS.map((f, i) => (
            <div
              key={f.org + f.name}
              style={{
                opacity: i < shown ? 1 : 0,
                transform:
                  i < shown ? "translateY(0) scale(1)" : "translateY(14px) scale(0.94)",
                transition: settled
                  ? "none"
                  : "opacity 340ms var(--ease-enter), transform 340ms var(--ease-enter)",
              }}
              className="flex flex-col rounded-lg border border-[rgba(10,10,10,0.10)] bg-white p-2.5 sm:p-3"
            >
              <span className="font-display text-[10px] font-bold uppercase tracking-[0.14em] text-[#737373]">
                {f.org}
              </span>
              <span className="mt-1 line-clamp-2 font-display text-[11px] font-semibold leading-snug text-[#0A0A0A] sm:text-[12px]">
                {f.name}
              </span>
              <span className="mt-auto flex items-center gap-1.5 pt-2 text-[9.5px] font-medium text-[#737373]">
                <Dot color={COVERED} />
                <span className="tabular-nums">v{f.version}</span>
                <span className="ml-auto">indexed</span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </ScreenPanel>
  );
}
