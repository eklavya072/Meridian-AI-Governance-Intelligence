"use client";

/**
 * Home page — Meridian landing: animated pipeline hero over a constant
 * full-page background.
 *
 * The React Bits GradientWaves canvas (WebGL, monochrome — black horizon,
 * grey waves, white crests) is a single FIXED full-viewport background. It
 * never moves: no matter how far you scroll, the waves stay constant and
 * edge-to-edge (no white strips anywhere). The page opens with a full-screen
 * intro — brand, what-we-do, and a four-capability carousel (Policy
 * Knowledge Base → Analysis Engine → Executive Brief → AI Auditor) — then
 * the interactive pipeline hero (Apple Feature Block style): a clickable
 * five-stage list — 01 Ingestion → 02 Retrieval → 03 Analysis → 04 Brief
 * Generation → 05 AI Auditor. The showcase panel on the right shows ONLY
 * the selected stage's live animation (ingestion parse card, retrieval
 * chunk graph, verdict card, brief mockup, auditor chat); its explanation
 * stays hidden until a stage tab is clicked, then appears beneath the
 * list. The sections are TRANSLUCENT, so
 * the animated background stays visible behind them — never a solid cover.
 *
 * Motion rules: sub-300ms UI motion via the shared tokens; the waves
 * shader loop is the deliberate exception (transform/opacity only).
 * Reduced-motion users get a static gradient instead of the shader.
 */

import { Fragment, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useScroll, useTransform } from "motion/react";
import { EASE, DUR, staggerContainer, staggerChild } from "@/lib/motion";
import GradientWaves from "@/components/GradientWaves";
import MeridianMark from "@/components/MeridianMark";
import Preloader from "@/components/Preloader";
import RollingText from "@/components/RollingText";
import TextType from "@/components/TextType";

/* Soft dark glow behind standalone white text so it stays legible over the
   brighter parts of the waves without any covering surface. */
const TEXT_GLOW =
  "[text-shadow:0_1px_2px_rgba(0,0,0,0.9),0_2px_18px_rgba(0,0,0,0.75)]";

/* Metallic silver heading treatment — a vertical top-lit gradient from
   bright white through silver to mid-grey, clipped to the glyphs. Reads as
   brushed metal against flat white text. text-shadow is suppressed (it
   would darken the transparent fill) and replaced by a soft drop-shadow
   glow on the rendered letters. Used for the two heading lines that should
   feel distinct — "Four capabilities." and "One document. / Eight
   dimensions." — while every other line stays plain white. */
const METALLIC_TEXT =
  "bg-[linear-gradient(180deg,#ffffff_0%,#f2f2f2_14%,#e0e0e0_34%,#bcbcbc_58%,#929292_80%,#6f6f6f_100%)] bg-clip-text text-transparent [text-shadow:none] drop-shadow-[0_2px_18px_rgba(0,0,0,0.8)]";

function useReducedMotionPref() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const update = () => setReduced(mq.matches);
    update();
    mq.addEventListener?.("change", update);
    return () => mq.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

/* Scroll-driven "in view" detection — the same intent as framer's
   whileInView (animate every time the element enters the viewport), but
   driven by a scroll listener instead of an IntersectionObserver: IO
   callbacks are unreliable in some embedded webviews (the intro typewriter
   already works around this the same way), and the reveal must replay on
   EVERY scroll-in, not just the first. `margin` shrinks the trigger zone
   by that many px on each edge. */
function useInViewReplay<T extends HTMLElement = HTMLElement>(margin = 60) {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      setInView(r.top < vh - margin && r.bottom > margin);
    };
    /* Fail-open fallback: some embedded webviews stop dispatching scroll
       events (and freeze rAF) entirely, which would leave every reveal
       stuck hidden — content "missing". A 500ms rect poll keeps the check
       running on plain timers (which still fire in those environments), so
       reveals, the pipeline Ingestion reset and the entrance replays all
       work even when scroll events never arrive. Harmless in healthy
       browsers — just a cheap rect read twice a second. */
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
  return { ref, inView };
}

/* Page-glide — each of the three landing sections behaves like its own
   "page": as it scrolls in it rises up into place (+7%), sits settled
   while fully on screen, then glides out as the next page arrives (-7%),
   with a hair of scale so the transition reads as pages sliding over one
   another rather than one continuous document. Driven by scroll progress
   (plain scroll listeners under the hood), so it works in every viewport;
   reduced-motion users get no movement. */
function usePageGlide() {
  const reduced = useReducedMotionPref();
  const ref = useRef<HTMLElement | null>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  /* Vertical glide only — NO scale. The scale made the whole page shrink
     (narrower AND smaller) whenever the section's height changed — e.g.
     collapsing a stage's info — because the height shift moves the scroll
     progress into the scale ramp. A pure translate keeps the pages gliding
     into each other without ever resizing their content. */
  const y = useTransform(
    scrollYProgress,
    [0, 0.35, 0.65, 1],
    reduced ? ["0%", "0%", "0%", "0%"] : ["9%", "0%", "0%", "-9%"]
  );
  return { ref, style: { y } };
}

/* ── Stage visuals (translucent glass, for the pipeline panels) ───────── */

function SubmissionVisual() {
  return (
    <div className="relative w-full max-w-xl mx-auto">
      <motion.div
        variants={staggerContainer(0.12, 0.1)}
        initial="hidden"
        animate="show"
        className="glass-dark relative p-5"
      >
        <motion.div variants={staggerChild} className="flex items-center gap-2 mb-3">
          <span className="w-2.5 h-2.5 rounded-full bg-white/20" />
          <span className="w-2.5 h-2.5 rounded-full bg-white/20" />
          <span className="w-2.5 h-2.5 rounded-full bg-white/20" />
          <span className="ml-2 text-xs text-white font-medium truncate">
            national-ai-strategy.pdf
          </span>
          <span className="ml-auto inline-flex items-center gap-1 text-[10px] font-medium text-white px-2 py-0.5 rounded-full border border-white/25 bg-white/10">
            ✓ Parsed
          </span>
        </motion.div>
        <motion.div variants={staggerChild} className="space-y-2">
          <div className="h-2.5 bg-white/12 rounded-full w-11/12" />
          <div className="h-2.5 bg-white/12 rounded-full w-4/5" />
          <div className="h-2.5 bg-white/12 rounded-full w-9/12" />
          <div className="h-2.5 bg-white/12 rounded-full w-full" />
        </motion.div>
        {/* Scan line — continuous process motion, the loop is meaningful. */}
        <motion.div
          className="absolute left-3 right-3 h-0.5 bg-white/80 rounded-full"
          initial={{ top: "12%" }}
          animate={{ top: ["12%", "86%", "12%"] }}
          transition={{ duration: 3.2, ease: "easeInOut", repeat: Infinity }}
        />
      </motion.div>
      <p className={`text-center text-xs text-white mt-4 font-medium tracking-wide ${TEXT_GLOW}`}>
        Structure-aware chunking — headings &amp; paragraphs kept intact
      </p>
    </div>
  );
}

function RetrievalVisual() {
  /* Chunks spread symmetrically around the document — left and right are
     balanced pairs — so the whole visual reads centred, not pushed to one
     side. Larger than before: the container, the document and the chunks
     are all scaled up so the stage fills its panel. */
  const chunks = [
    { x: -185, y: 70, w: 130, delay: 0 },
    { x: -95, y: -85, w: 110, delay: 0.2 },
    { x: 95, y: 95, w: 145, delay: 0.4 },
    { x: 185, y: -50, w: 115, delay: 0.6 },
    { x: -45, y: -40, w: 95, delay: 0.8 },
    { x: 45, y: 25, w: 120, delay: 1.0 },
  ];
  return (
    /* max-w-xl (not 2xl): the panel is ~660px wide on desktop, and with
       the 12px rightward offset a 672px visual would clip at the panel
       edge. At max-w-xl the enlarged document + chunks still read larger
       than the original, and the offset never cuts anything off. */
    <div className="relative w-full max-w-xl mx-auto">
      <div className="relative h-80">
        {/* Document origin */}
        <motion.div
          className="absolute left-1/2 top-1/2 w-28 h-40 -translate-x-1/2 -translate-y-1/2 glass-dark p-2.5 flex flex-col gap-2"
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: DUR.slow, ease: EASE.out }}
        >
          <div className="h-2 bg-white/20 rounded w-full" />
          <div className="h-2 bg-white/20 rounded w-4/5" />
          <div className="h-2 bg-white/20 rounded w-2/3" />
        </motion.div>
        {/* Chunks breaking apart into vector space */}
        {chunks.map((c, i) => (
          <motion.div
            key={i}
            className="absolute left-1/2 top-1/2 rounded-lg border border-white/30 bg-white/10 backdrop-blur-lg p-2 flex flex-col gap-1.5"
            initial={{ x: 0, y: 0, opacity: 0, scale: 0.9 }}
            animate={{ x: c.x, y: c.y, opacity: 1, scale: 1 }}
            transition={{
              duration: 1.1,
              ease: EASE.outSoft,
              delay: 0.35 + c.delay,
            }}
          >
            <div className="h-1.5 bg-white/70 rounded" style={{ width: c.w }} />
            <div className="h-1.5 bg-white/20 rounded" style={{ width: c.w * 0.75 }} />
            <div className="flex items-center gap-1 mt-0.5">
              <span className={`text-[8px] text-white ${TEXT_GLOW}`}>384-d</span>
            </div>
          </motion.div>
        ))}
      </div>
      {/* Caption sits in flow BELOW the animation area — never overlaps it. */}
      <motion.p
        className={`text-center text-xs text-white mt-4 font-medium tracking-wide ${TEXT_GLOW}`}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.6, duration: 0.4 }}
      >
        Embedded &amp; ranked per governance dimension — on-topic chunks only
      </motion.p>
    </div>
  );
}

/* Analysis stage visual — mirrors the real analysis deck: the Analysis
   card lands first, then Recommendations & Alignment slides in from the
   side, then Implementation Roadmap replaces it — one card at a time,
   exactly like the module stack in the analysis view. No confidence
   gauge. Reduced motion lands on the final roadmap card. */
function AnalysisVisual() {
  const reduced = useReducedMotionPref();
  const [card, setCard] = useState(0);

  useEffect(() => {
    if (reduced) {
      setCard(2);
      return;
    }
    const timers: ReturnType<typeof setTimeout>[] = [];
    const at = (ms: number, fn: () => void) => timers.push(setTimeout(fn, ms));
    at(1500, () => setCard(1));
    at(3100, () => setCard(2));
    return () => timers.forEach((t) => clearTimeout(t));
  }, [reduced]);

  /* Cards are taller now — five content lines each (the user wants length
     over width) — and the deck is a touch narrower so it reads as a card,
     not a strip. */
  const cards = [
    {
      chip: "Analysis",
      title: "Transparency",
      lines: ["w-11/12", "w-10/12", "w-4/5", "w-9/12", "w-3/4"],
      footer: null as string | null,
    },
    {
      chip: "Recommendations",
      title: "Recommendations & Alignment",
      lines: ["w-11/12", "w-10/12", "w-4/5", "w-9/12", "w-3/4"],
      footer: "Recommendations →",
    },
    {
      chip: "Roadmap",
      title: "Implementation Roadmap",
      lines: ["w-11/12", "w-10/12", "w-4/5", "w-9/12", "w-3/4"],
      footer: "6–12 months",
    },
  ];
  const c = cards[card];

  return (
    <div className="relative w-full max-w-lg mx-auto">
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={card}
          initial={reduced ? false : { opacity: 0, x: 110 }}
          animate={{ opacity: 1, x: 0 }}
          exit={reduced ? undefined : { opacity: 0, x: -110 }}
          transition={{ duration: 0.65, ease: EASE.out }}
          className="glass-dark p-5"
        >
          <div className="flex items-center gap-2 mb-3">
            <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-white bg-white/10 border border-white/20 px-2 py-0.5 rounded">
              {c.chip}
            </span>
            <div className="font-display font-semibold text-white">{c.title}</div>
          </div>
          {card === 0 && (
            <div className="flex items-center gap-2 mb-3">
              <span className="inline-flex items-center gap-2 text-xs font-medium text-white">
                <span className="w-2 h-2 rounded-full bg-amber-400" />
                Partially Covered
              </span>
              <span className="inline-flex items-center gap-2 text-xs font-medium text-white">
                <span className="w-2 h-2 rounded-full bg-white" />
                Developing
              </span>
            </div>
          )}
          <div className="space-y-2.5">
            {c.lines.map((w, i) => (
              <div key={i} className={`h-2 bg-white/12 rounded ${w}`} />
            ))}
          </div>
          {c.footer && (
            <div className="flex items-center gap-2 pt-3">
              <span className="text-[10px] uppercase tracking-[0.14em] text-white/70 font-semibold">
                {c.footer}
              </span>
            </div>
          )}
        </motion.div>
      </AnimatePresence>
      <p className={`text-center text-xs text-white mt-4 font-medium tracking-wide ${TEXT_GLOW}`}>
        Deterministic ladder guardrails — a verdict the model can&apos;t fake
      </p>
    </div>
  );
}

function BriefVisual() {
  const reduced = useReducedMotionPref();
  return (
    <div className="relative w-full max-w-xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: DUR.slow, ease: EASE.out }}
        className="glass-dark p-5"
      >
        <div className="mb-3">
          <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-white bg-white/10 border border-white/20 px-2 py-0.5 rounded">
            Executive Brief
          </span>
        </div>
        <div className="font-display font-semibold text-white text-base mb-3">
          AI Governance Assessment Brief
        </div>
        {/* The report assembles in front of you: the executive-summary page
            lands — its sections appear one by one, a score chart grows, then
            citations populate and the exports pop in. No second page behind
            it: the overlapping glass panel covered the chart. */}
        <div className="relative h-40 mb-3">
          <motion.div
            className="absolute left-0 top-0 w-full h-full rounded-lg border border-white/20 bg-white/[0.07] backdrop-blur-sm p-3"
            initial={reduced ? false : { x: -26, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ duration: 0.5, ease: EASE.out, delay: reduced ? 0 : 0.3 }}
          >
            <div className="text-[9px] font-semibold uppercase tracking-[0.18em] text-white/70 mb-2">
              Executive Summary
            </div>
            {["w-full", "w-11/12", "w-4/5"].map((w, i) => (
              <motion.div
                key={w}
                className={`h-1 ${i === 0 ? "bg-white/25" : "bg-white/12"} rounded ${w} mb-1.5`}
                style={{ transformOrigin: "left" }}
                initial={reduced ? false : { scaleX: 0, opacity: 0 }}
                animate={{ scaleX: 1, opacity: 1 }}
                transition={{
                  duration: 0.4,
                  ease: EASE.out,
                  delay: reduced ? 0 : 0.6 + i * 0.18,
                }}
              />
            ))}
            {/* Mini chart — the dimension scores growing in */}
            <div className="flex items-end gap-1 h-6 mt-2">
              {[55, 82, 34, 68].map((h, i) => (
                <motion.div
                  key={i}
                  className="flex-1 rounded-sm bg-white/60"
                  style={{ transformOrigin: "bottom", height: `${h}%` }}
                  initial={reduced ? false : { scaleY: 0, opacity: 0 }}
                  animate={{ scaleY: 1, opacity: 1 }}
                  transition={{
                    duration: 0.45,
                    ease: EASE.out,
                    delay: reduced ? 0 : 1.2 + i * 0.1,
                  }}
                />
              ))}
            </div>
          </motion.div>
        </div>
        {/* Citations populate beneath the assembled pages */}
        <div className="flex items-center gap-1.5 mb-3">
          {["[1]", "[2]", "[3]", "[4]"].map((c, i) => (
            <motion.span
              key={c}
              initial={reduced ? false : { opacity: 0, scale: 0.6 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{
                delay: reduced ? 0 : 1.55 + i * 0.12,
                type: "spring",
                stiffness: 420,
                damping: 24,
              }}
              className="text-[9px] font-semibold tracking-wide text-white px-1.5 py-0.5 rounded bg-white/10 border border-white/15"
            >
              {c}
            </motion.span>
          ))}
          <span className="text-[9px] uppercase tracking-[0.14em] text-white/60 ml-1">
            verified
          </span>
        </div>
        {/* Export chips + verified badge pop in once the brief is written. */}
        <div className="pt-3 border-t border-white/10 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <motion.span
              initial={reduced ? false : { opacity: 0, scale: 0.6 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: reduced ? 0 : 2.05, type: "spring", stiffness: 400, damping: 22 }}
              className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-white/10 border border-white/15 text-white"
            >
              PDF
            </motion.span>
            <motion.span
              initial={reduced ? false : { opacity: 0, scale: 0.6 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: reduced ? 0 : 2.25, type: "spring", stiffness: 400, damping: 22 }}
              className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-white/10 border border-white/15 text-white"
            >
              DOCX
            </motion.span>
          </div>
          <motion.span
            initial={reduced ? false : { opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: reduced ? 0 : 2.5, type: "spring", stiffness: 380, damping: 20 }}
            className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-white/15 text-white border border-white/25"
          >
            ✓ Verified
          </motion.span>
        </div>
      </motion.div>
      <p className={`text-center text-xs text-white mt-4 font-medium tracking-wide ${TEXT_GLOW}`}>
        Synthesised from verified results — exported in one click
      </p>
    </div>
  );
}

/* ── AI Auditor stage visual (chat mockup) ───────────────────────────── */

/* Small typewriter hook — reveals `text` one character at a time while
   `start` is true, then reports `done`. Resets to empty when `start` flips
   back to false, so every loop begins from the first character. */
function useTypewriter(start: boolean, text: string, speed: number) {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!start) {
      setN(0);
      return;
    }
    if (n >= text.length) return;
    const t = setTimeout(() => setN((v) => v + 1), speed);
    return () => clearTimeout(t);
  }, [start, n, text, speed]);
  return { shown: text.slice(0, n), done: n >= text.length };
}

const AUDITOR_Q = "Why is Transparency partially covered?";
const AUDITOR_A =
  "It is covered for disclosure duties, but the document does not require independent algorithm audits or public accountability reports.";

/* AI Auditor stage visual — a premium chat loop: the user's question types
   into the input bar, is sent, the assistant shows an animated typing
   indicator, the answer types out progressively and then holds — nothing
   else animates after the answer. Phases: 0 idle → 1 typing question →
   2 sent → 3 thinking → 4 answering → back to 0. Reduced motion lands on
   the finished conversation. */
function AuditorVisual() {
  const reduced = useReducedMotionPref();
  const [phase, setPhase] = useState(0);
  const q = useTypewriter(phase === 1, AUDITOR_Q, 42);
  const a = useTypewriter(phase === 4, AUDITOR_A, 22);

  useEffect(() => {
    if (reduced) {
      setPhase(6);
      return;
    }
    const timers: ReturnType<typeof setTimeout>[] = [];
    const at = (ms: number, fn: () => void) => timers.push(setTimeout(fn, ms));
    if (phase === 0) at(900, () => setPhase(1));
    else if (phase === 1 && q.done) at(450, () => setPhase(2));
    else if (phase === 2) at(650, () => setPhase(3));
    else if (phase === 3) at(1050, () => setPhase(4));
    /* After the answer finishes, hold it on screen — then the loop replays. */
    else if (phase === 4 && a.done) at(4200, () => setPhase(0));
    return () => timers.forEach((t) => clearTimeout(t));
  }, [phase, q.done, a.done, reduced]);

  const answerText = phase >= 6 ? AUDITOR_A : a.shown;
  const answerDone = a.done || phase >= 6;
  const typingAnswer = phase === 4 && !answerDone;

  return (
    <div className="relative w-full max-w-xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: DUR.slow, ease: EASE.out }}
        className="glass-dark p-5"
        aria-hidden
      >
        <div className="flex items-center gap-2 mb-4">
          <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-white bg-white/10 border border-white/20 px-2 py-0.5 rounded">
            AI Auditor
          </span>
          <span className="text-xs text-white font-medium">
            Grounded in this document
          </span>
        </div>
        <div className="space-y-3 min-h-[240px]">
          {/* User question — sent in */}
          <AnimatePresence>
            {phase >= 2 && (
              <motion.div
                key="user"
                initial={reduced ? false : { opacity: 0, x: 18, scale: 0.92 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                exit={{ opacity: 0 }}
                transition={{ type: "spring", stiffness: 380, damping: 28 }}
                className="flex justify-end"
              >
                <div className="rounded-xl rounded-br-sm bg-white text-black text-xs px-3 py-2 max-w-[80%] font-medium">
                  {AUDITOR_Q}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          {/* Thinking — animated typing indicator */}
          <AnimatePresence>
            {phase === 3 && (
              <motion.div
                key="think"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.25 }}
                className="flex justify-start"
              >
                <div className="rounded-xl rounded-bl-sm bg-white/10 border border-white/15 text-white px-3.5 py-2.5 flex items-center gap-1.5">
                  {[0, 1, 2].map((d) => (
                    <motion.span
                      key={d}
                      className="w-1.5 h-1.5 rounded-full bg-white/80"
                      animate={{ y: [0, -4, 0] }}
                      transition={{ duration: 0.55, repeat: Infinity, delay: d * 0.12 }}
                    />
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          {/* Answer — types out progressively */}
          <AnimatePresence>
            {phase >= 4 && (
              <motion.div
                key="answer"
                initial={reduced ? false : { opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.35, ease: EASE.out }}
                className="flex justify-start"
              >
                <div className="rounded-xl rounded-bl-sm bg-white/10 border border-white/15 text-white text-xs px-3 py-2 max-w-[85%] leading-relaxed">
                  {answerText}
                  {typingAnswer && (
                    <motion.span
                      className="inline-block w-px h-3 bg-white ml-0.5 align-middle"
                      animate={{ opacity: [1, 0, 1] }}
                      transition={{ duration: 0.7, repeat: Infinity }}
                    />
                  )}
                  {answerDone && (
                    <span className="block mt-1.5 text-[10px] font-semibold tracking-[0.14em]">
                      SOURCES [2] · [7]
                    </span>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        {/* Input bar — the question types out here before it's sent */}
        <div className="mt-4 pt-3 border-t border-white/10 flex items-center gap-2">
          <span className="flex-1 text-xs text-white px-3.5 py-2 rounded-full bg-white/10 border border-white/15 truncate text-left">
            {phase === 1 ? (
              <>
                {q.shown}
                <motion.span
                  className="inline-block w-px h-3 bg-white ml-0.5 align-middle"
                  animate={{ opacity: [1, 0, 1] }}
                  transition={{ duration: 0.7, repeat: Infinity }}
                />
              </>
            ) : (
              "Ask about this policy…"
            )}
          </span>
          <span
            className={`w-8 h-8 rounded-full inline-flex items-center justify-center text-sm font-semibold shrink-0 transition-colors duration-300 ${
              phase >= 2 ? "bg-white text-black" : "bg-white/15 text-white/60"
            }`}
          >
            ↑
          </span>
        </div>
      </motion.div>
      <p className={`text-center text-xs text-white mt-4 font-medium tracking-wide ${TEXT_GLOW}`}>
        Document-grounded answers — every claim linked to its source
      </p>
    </div>
  );
}

/* ── Hero — the five-stage interactive pipeline (Apple Feature Block style):
   a clickable stage list on the left; the selected stage's content —
   headline, description, points and its live visual — swaps into the
   showcase panel on the right. Each stage replaces the Apple-style phone
   with Meridian's own hero visual (ingestion parse card, retrieval chunk
   graph, verdict card, brief mockup, auditor chat). No scroll-pinning: the
   stage list IS the navigation. ───────────────────────────────────────── */

const PIPELINE = [
  {
    id: 0,
    num: "01",
    title: "Ingestion",
    tagline: "Parse, chunk & index any policy",
    desc: "Upload a national AI strategy or regulation. It's parsed into structure-aware chunks — headings, sections and paragraphs kept intact — and indexed, ready for retrieval.",
    points: [
      "Any government PDF, any region",
      "Structure-aware chunking",
      "Indexed into the vector store",
    ],
    visual: <SubmissionVisual />,
    /* Auto-advance delay — how long the stage stays before the hero moves
       on (sequence time + ~5s on screen). */
    holdMs: 8000,
  },
  {
    id: 1,
    num: "02",
    title: "Retrieval",
    tagline: "Per-dimension, framework-aware search",
    desc: "Chunks are embedded and ranked per governance dimension — and routed to the frameworks that matter for that country and topic. No off-topic evidence, no hand-waving.",
    points: [
      "Semantic search per dimension",
      "Country-aware framework routing",
      "Only on-topic evidence retrieved",
    ],
    visual: <RetrievalVisual />,
    holdMs: 7000,
  },
  {
    id: 2,
    num: "03",
    title: "Analysis",
    tagline: "Eight dimensions, verified verdicts",
    desc: "A deterministic coverage ladder plus a calibrated language model analyse each dimension — Fully Covered, Partially Covered, or Missing — with maturity and cited evidence.",
    points: [
      "8 locked governance dimensions",
      "Deterministic ladder guardrails",
      "Every citation verified",
    ],
    visual: <AnalysisVisual />,
    holdMs: 8000,
  },
  {
    id: 3,
    num: "04",
    title: "Brief Generation",
    tagline: "A two-page brief, export-ready",
    desc: "The analysis is distilled into an executive brief — PDF or DOCX — where every claim was already verified during evaluation. Read it in three minutes, or share it as-is.",
    points: [
      "Synthesised, never re-analysed",
      "PDF & DOCX export",
      "Cached — regenerate on demand",
    ],
    visual: <BriefVisual />,
    holdMs: 7500,
  },
  {
    id: 4,
    num: "05",
    title: "AI Auditor",
    tagline: "Ask any policy anything",
    desc: "Upload any policy and ask questions directly — answers are grounded in the document's own text, with citations you can open and check. No hallucinated generalities.",
    points: [
      "Chat with any policy",
      "Document-grounded answers",
      "Citations you can open",
    ],
    visual: <AuditorVisual />,
    holdMs: 10000,
  },
];

function PipelineHero() {
  const [active, setActive] = useState(0);
  /* The stage info starts CLOSED — no section's description is open on
     arrival; each opens only when its stage is clicked (and closes on a
     second click). `explained` toggles it; `manual` tracks whether the
     user has clicked a stage (vs autoplay), so the white highlight only
     shows on a deliberate click, never during the automated cycle. */
  const [explained, setExplained] = useState(false);
  const [manual, setManual] = useState(false);
  const reducedMotion = useReducedMotionPref();
  const stage = PIPELINE[active];
  /* Same replay-on-scroll treatment as the dimensions grid below. */
  const { ref: listRef, inView: listInView } = useInViewReplay<HTMLDivElement>(80);
  /* Page-glide: this section is "page two" — rises in, settles, glides out. */
  const { ref: pageRef, style: pageStyle } = usePageGlide();
  /* The animation panel. On narrow (stacked) screens the panel sits ABOVE
     the stage list so the animation is visible the moment page two arrives
     (previously the list filled the first viewport and the panel was below
     the fold — "not visible"). Clicking a stage scrolls the panel back into
     view so the swap is always on screen; on desktop (side-by-side) the
     panel is always visible, so the scroll is a no-op there. */
  const panelRef = useRef<HTMLDivElement>(null);
  function revealPanel() {
    const el = panelRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const vh = window.innerHeight || document.documentElement.clientHeight;
    if (r.top > vh - 40 || r.bottom > vh) {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  /* The show ALWAYS restarts from Ingestion whenever the page scrolls into
     view — every scroll-down begins at stage 01 with its info OPEN and
     autoplay re-armed (manual cleared), and `showRound` bumps so the stage
     visual REMOUNTS (key change) and replays its entrance animation from
     scratch. Without the round, scrolling in while Ingestion is already
     active would be a setActive(0) no-op and the visual's animation — which
     played once at page load, off-screen — would already be finished. The
     visual stays mounted at all times, so it is always visible even where
     scroll events are unreliable; the round just restarts its animation on
     entry. */
  const prevListInView = useRef<boolean | null>(null);
  const [showRound, setShowRound] = useState(0);
  useEffect(() => {
    if (listInView && prevListInView.current !== true) {
      setActive(0);
      setExplained(false);
      setManual(false);
      setShowRound((r) => r + 1);
    }
    prevListInView.current = listInView;
  }, [listInView]);

  /* Auto-advance runs only while the page is on screen AND the user hasn't
     taken manual control: off-screen it pauses (so the show is always
     fresh when you return — combined with the Ingestion reset above), and
     once the user clicks a stage it stays put on their choice. The info
     panels stay open throughout either way. Disabled for reduced-motion
     users. */
  useEffect(() => {
    if (reducedMotion || manual || !listInView) return;
    const t = setTimeout(() => {
      setActive((a) => (a + 1) % PIPELINE.length);
    }, PIPELINE[active].holdMs);
    return () => clearTimeout(t);
  }, [active, reducedMotion, manual, listInView]);

  return (
    /* Interactive stage showcase — the feature list on the left is the
       navigation; clicking a stage swaps the panel on the right. Both
       columns are translucent, so the fixed waves stay visible behind. */
    <motion.section
      ref={pageRef}
      style={pageStyle}
      className="relative z-10 min-h-screen flex flex-col justify-center py-12 sm:py-16 lg:py-24 snap-start"
    >
      <div className="relative w-full max-w-7xl mx-auto px-6 sm:px-10">
        {/* Section header — full width above the showcase, so the animation
            panel can align with the stage list (Ingestion → AI Auditor). */}
        <div>
          {/* Eyebrow in the same metallic silver treatment as the
              capability labels — a premium accent above the heading. */}
          <p
            className={`text-[11px] sm:text-xs font-semibold uppercase tracking-[0.24em] ${METALLIC_TEXT}`}
          >
            The Pipeline
          </p>
          <h2
            aria-label="From document to decision-ready brief."
            className={`font-display text-3xl sm:text-4xl lg:text-[2.8rem] font-semibold text-white tracking-tight leading-[1.08] mt-4 lg:whitespace-nowrap ${TEXT_GLOW}`}
          >
            <RollingText text="From document to decision-ready brief." />
          </h2>
        </div>
        <div className="grid lg:grid-cols-[0.82fr_1.18fr] gap-14 lg:gap-20 items-stretch mt-14">
          {/* LEFT — clickable stage list; each stage's info pops in below
              its own button when clicked. The list staggers in on scroll,
              replaying every time it comes back into view (same pattern as
              the dimensions grid in the statement section). On narrow
              screens it sits BELOW the animation panel (order-last) so the
              animation is the first thing page two shows. */}
          <div className="min-w-0 order-last lg:order-none">
            <motion.div
              ref={listRef}
              variants={staggerContainer(0.08, 0.05)}
              initial="hidden"
              animate={listInView ? "show" : "hidden"}
              className="flex flex-col gap-3"
            >
              {PIPELINE.map((p) => {
                /* The info panel shows for the ACTIVE stage whenever info
                   is open (explained) — including during autoplay, so the
                   page never looks compacted. The WHITE highlight is
                   reserved for a deliberate click (manual), so the
                   automated cycle never highlights a stage. */
                const isOpen = p.id === active && explained;
                const isHighlighted = manual && isOpen;
                return (
                  <Fragment key={p.id}>
                    <motion.button
                      variants={staggerChild}
                      onClick={() => {
                        // Clicking the active tab collapses the info (the
                        // +/− glyph); any other tab reveals it.
                        if (p.id === active && explained) {
                          setExplained(false);
                        } else {
                          setActive(p.id);
                          setExplained(true);
                          setManual(true);
                        }
                        // On stacked screens the panel is above the list —
                        // bring the animation into view when a stage is
                        // clicked so the swap is always on screen.
                        revealPanel();
                      }}
                      aria-pressed={isHighlighted}
                      className={`group flex items-center gap-4 w-full text-left px-4 sm:px-5 py-4 rounded-2xl border transition-colors duration-300 ${
                        isHighlighted
                          ? "bg-white text-[#0A0A0A] border-white"
                          : "bg-white/[0.05] text-white border-white/10 hover:bg-white/[0.1] hover:border-white/25"
                      }`}
                    >
                      {/* Stage numerals in the metallic silver treatment —
                          brushed metal on the dark cards; back to plain
                          black when the card itself is white (highlighted),
                          so the numeral stays legible on the white surface. */}
                      <span
                        className={`text-[13px] font-medium tracking-[0.15em] ${
                          isHighlighted ? "text-[#0A0A0A]" : METALLIC_TEXT
                        }`}
                      >
                        {p.num}
                      </span>
                      <span className="flex-1">
                        <span className="block font-display text-sm font-semibold tracking-tight leading-tight">
                          {p.title}
                        </span>
                        <span
                          className={`block text-[13px] mt-0.5 leading-snug ${
                            isHighlighted ? "text-[#0A0A0A]" : "text-white"
                          }`}
                        >
                          {p.tagline}
                        </span>
                      </span>
                      <span
                        aria-hidden
                        className={`text-base ${
                          isHighlighted ? "text-[#0A0A0A]" : "text-white"
                        }`}
                      >
                        {isHighlighted ? "—" : "+"}
                      </span>
                    </motion.button>

                    {/* The stage's info — animated-height accordion. Closed = 0
                        height (no blank gap between cards); open = smooth grow
                        to the content's own height. Only the vertical dimension
                        moves — the width stays the full card width in both
                        states (the w-full container keeps the section stable). */}
                    <motion.div
                      initial={false}
                      animate={
                        reducedMotion
                          ? { height: isOpen ? "auto" : 0, opacity: isOpen ? 1 : 0 }
                          : {
                              height: isOpen ? "auto" : 0,
                              opacity: isOpen ? 1 : 0,
                              y: isOpen ? 0 : 10,
                            }
                      }
                      transition={
                        reducedMotion
                          ? { duration: 0 }
                          : {
                              height: { duration: 0.35, ease: EASE.out },
                              opacity: { duration: 0.28, ease: EASE.out },
                              y: { duration: 0.3, ease: EASE.out },
                            }
                      }
                      className="overflow-hidden"
                    >
                      <div className="pr-3 pb-2">
                        <p className="text-white/90 text-[0.93rem] leading-relaxed">
                          {p.desc}
                        </p>
                        <ul className="flex flex-col gap-1.5 mt-3 text-sm font-medium text-white">
                          {p.points.map((pt) => (
                            <li key={pt} className="flex items-center gap-2.5">
                              <span className="w-1.5 h-1.5 rounded-full bg-white/80 shrink-0" />
                              {pt}
                            </li>
                          ))}
                        </ul>
                        {p.id === 0 && (
                          <a
                            href="/workspace"
                            className="clay-button pressable inline-flex items-center gap-2 text-[#0A0A0A] px-5 py-2.5 font-semibold text-sm mt-4"
                          >
                            Start an Analysis <span aria-hidden>→</span>
                          </a>
                        )}
                      </div>
                    </motion.div>
                  </Fragment>
                );
              })}
            </motion.div>

          </div>

          {/* RIGHT — the selected stage's animation. The panel stretches to
              the full height of the stage list (Ingestion → AI Auditor) and
              centres the animation. No glass box here: each stage visual
              carries its own glass card, and the panel is transparent so the
              waves stay visible around it. mode="wait" swaps cleanly — one
              panel at a time. On narrow screens it sits ABOVE the stage list
              (order-first) so the animation is visible immediately. */}
          <div ref={panelRef} className="min-w-0 order-first lg:order-none">
            {/* No aria-live here: the panel is animation-only, and announcing
                the mockups' internal text on every swap would be noise. */}
            {/* No overflow-hidden here: it clipped the taller stage visuals
                (Brief, Auditor) where the up-shift pushed their top edge out
                of the panel, and the shorter ones looked "cut in half" with
                a black void. The visuals stay fully inside because each
                stage fits its panel; any transient slide (Analysis) spills
                harmlessly under the page-level overflow-x-clip. */}
            <div className="flex items-center justify-center min-h-[340px] lg:min-h-[540px] lg:h-full"
            >
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={`${stage.id}-${showRound}`}
                  initial={reducedMotion ? false : { opacity: 0, y: 18 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -12 }}
                  transition={
                    reducedMotion
                      ? { duration: 0 }
                      : { duration: 0.35, ease: EASE.out }
                  }
                  className="w-full flex items-center justify-center"
                >
                  {/* All stage visuals sit a tad right within the panel, and
                      a tad UP on desktop only (lg): in the tall side-by-side
                      panel the up-shift re-balances the composition against
                      the heavier left list column. On stacked screens the
                      same shift pushed the visual to the top of the panel,
                      collecting all the empty space below it as a black band
                      ("half present, half blank") — so mobile keeps it
                      perfectly centred instead. w-full keeps every visual at
                      its full configured width — the offset must never
                      shrink or clip them. */}
                  <div className="w-full translate-x-3 lg:-translate-y-12">
                    {stage.visual}
                  </div>
                </motion.div>
              </AnimatePresence>
            </div>
          </div>
        </div>
      </div>
    </motion.section>
  );
}

/* ── Intro — brand block + capabilities carousel on the first screen ──── */

const CAPABILITIES = [
  {
    index: "01",
    title: "Policy Knowledge Base",
    desc: "A living library of the world's AI governance frameworks — UNESCO, OECD, EU AI Act, NIST — indexed and routed per dimension and region.",
    tags: ["13+ frameworks", "Dimension routing", "Regional context"],
  },
  {
    index: "02",
    title: "Analysis Engine",
    desc: "Scores any policy across 8 governance dimensions — evidence-grounded verdicts, calibrated confidence, roadmaps and case intelligence.",
    tags: ["8 dimensions", "Deterministic ladder", "Verified citations"],
  },
  {
    index: "03",
    title: "Executive Brief",
    desc: "Distils the analysis into a two-page executive brief, export-ready — every citation verified against its source before it reaches the page.",
    tags: ["1–2 pages", "PDF & DOCX", "Verified citations"],
  },
  {
    index: "04",
    title: "AI Auditor",
    desc: "Upload any policy and ask questions directly — answers are grounded in the document's own text, with citations you can open and check.",
    tags: ["Chat with any policy", "Document-grounded", "Framework-aware"],
  },
];

/* Skiper 51-style capability carousel (adapted, no swiper dependency):
   ONE card on screen at a time — no half-visible neighbours. The track is
   a full-width flex row translated by index; the viewport clips it, so
   exactly one card is visible and the next slides in cleanly. Autoplay
   advances the index; arrows + dots jump; hover/touch pauses. */

function IntroSection({ active }: { active: boolean }) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const count = CAPABILITIES.length;
  const reducedMotion = useReducedMotionPref();
  const trackRef = useRef<HTMLDivElement>(null);

  /* The typed tagline plays once on load and restarts every time the intro
     scrolls back into view. A scroll/resize listener (not an
     IntersectionObserver — its callbacks can be unreliable in some embedded
     webviews) checks the section's rect: when it becomes visible after being
     fully out of view, `typeRound` bumps and the keyed TextType remounts, so
     the typewriter begins again from the first character. The initial check
     only records the state — the load play comes from the mount itself. */
  /* The page-glide ref doubles as the typewriter's scroll target — the
     section is "page one" (rises in, settles, glides out). */
  const { ref: introRef, style: pageStyle } = usePageGlide();
  const [typeRound, setTypeRound] = useState(0);
  const prevIntroVisible = useRef<boolean | null>(null);
  useEffect(() => {
    const el = introRef.current;
    if (!el) return;
    const check = () => {
      if (!el) return;
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      const visible = r.top < vh && r.bottom > 0;
      if (prevIntroVisible.current === null) {
        prevIntroVisible.current = visible;
        return;
      }
      if (visible && !prevIntroVisible.current) {
        setTypeRound((rr) => rr + 1);
      }
      prevIntroVisible.current = visible;
    };
    check();
    window.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
    return () => {
      window.removeEventListener("scroll", check);
      window.removeEventListener("resize", check);
    };
  }, []);

  /* Auto-advance on an interval; one card at a time, wrapping after the
     last. Hover/touch pauses it. The timer lives in a ref so manual
     navigation (arrows/dots/drag) can restart it — a click must buy the
     full 5.2s on the chosen card, not whatever remained of the old cycle. */
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  function restartTimer() {
    if (paused) return;
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setIndex((i) => (i + 1) % count);
    }, 5200);
  }
  useEffect(() => {
    restartTimer();
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paused, count]);

  function go(i: number) {
    setIndex(Math.max(0, Math.min(i, count - 1)));
    restartTimer();
  }

  /* Drag/swipe: the translated track stays draggable (the old snap-scroll
     was swipeable on touch — this keeps that affordance). motion's drag
     moves the track freely on top of the animated x; on release we snap to
     the nearest card by changing the index. */

  return (
    /* First screen: a full-viewport intro — brand + what we do — with the
       capabilities carousel on it. Scroll past it and the pipeline hero
       takes over (the hero pins its own viewport below). min-h-screen keeps
       the intro a complete "page"; justify-center centers the block. */
    <motion.section
      ref={introRef}
      style={pageStyle}
      className="relative z-10 min-h-screen flex flex-col justify-center py-28 sm:py-36 snap-start"
    >
      <div className="relative w-full max-w-7xl mx-auto px-6 sm:px-10">
        {/* Side-by-side first screen: the brand on the left (wordmark in
            the Unbounded brand face, tagline beneath, one line of what
            it's for — no long paragraph), and "Four capabilities. One
            pipeline." with the carousel on the right. min-w-0 on both
            columns keeps the slider track's intrinsic 4x width from
            overflowing the grid. */}
        <div className="grid lg:grid-cols-[0.95fr_1.05fr] gap-20 lg:gap-36 items-start">
          {/* LEFT — the brand */}
          <motion.div
            initial={reducedMotion ? false : { opacity: 0, y: 20 }}
            animate={reducedMotion || !active ? false : { opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: EASE.out }}
            className="min-w-0 text-center lg:text-left"
          >
            <h1 className={`text-white ${TEXT_GLOW}`}>
              {/* Logo lockup — the brand mark beside the wordmark, centred
                  on mobile, left-aligned on desktop. Unbounded is a wide
                  face, so the clamp keeps the wordmark inside the column.
                  The mark is sized to the same clamp as the wordmark, so it
                  always reads as big as the heading it sits beside. */}
              <span className="flex items-center gap-5 sm:gap-6 justify-center lg:justify-start">
                <MeridianMark
                  size={64}
                  className="shrink-0 w-[clamp(2.5rem,7vw,5rem)] h-[clamp(2.5rem,7vw,5rem)]"
                />
                <span className="block font-brand text-[clamp(2.5rem,7vw,5rem)] font-semibold text-white tracking-tight leading-[0.95]">
                  Meridian
                </span>
              </span>
              <span className="mt-5 block font-brand text-[13px] sm:text-lg font-medium uppercase tracking-[0.24em] text-white">
                AI Governance Intelligence
              </span>
            </h1>
            {/* The typewriter is the tagline — except for reduced-motion
                users, who get the static sentence (the page honors
                prefers-reduced-motion everywhere else, and a perpetually
                blinking cursor + type/delete loop is exactly what it's
                for). The keyed remount on scroll-back-up replays it. */}
            {reducedMotion ? (
              <p
                className={`mt-20 font-display text-2xl sm:text-3xl font-semibold text-white tracking-tight ${TEXT_GLOW}`}
              >
                Built for governance teams who answer to evidence.
              </p>
            ) : active ? (
              <TextType
                key={typeRound}
                as="p"
                className={`mt-20 font-display text-2xl sm:text-3xl font-semibold text-white tracking-tight ${TEXT_GLOW}`}
                text={["Built for governance teams who answer to evidence."]}
                typingSpeed={55}
                deletingSpeed={30}
                pauseDuration={2600}
                initialDelay={900}
                showCursor
                cursorCharacter="|"
                loop={false}
              />
            ) : (
              /* Reserve the tagline's line-height while the preloader is up
                 so the intro column doesn't shift when the typewriter mounts
                 at reveal. */
              <div aria-hidden className="mt-20 h-8 sm:h-9" />
            )}
          </motion.div>

          {/* RIGHT — heading + arrows on top, the slider below (narrower
              than the column, same card height as before). */}
          <motion.div
            initial={reducedMotion ? false : { opacity: 0, y: 16 }}
            animate={reducedMotion || !active ? false : { opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: EASE.out, delay: 0.25 }}
            className="min-w-0"
          >
            <div className="flex flex-wrap items-center justify-between gap-4 mb-20">
              {/* Same size, weight and colour as the "One document. Eight
                  dimensions." statement heading — and the same stacked
                  rhythm — so the two sections speak the same language. */}
              <h2
                className={`font-display text-3xl sm:text-5xl lg:text-[3.4rem] font-semibold text-white tracking-tight leading-[1.12] ${TEXT_GLOW}`}
              >
                {/* Metallic silver gradient — a distinct, premium feel for
                    the "four capabilities" line while "One pipeline."
                    below stays pure white. Stays inside the monochrome
                    scale (white → mid-grey), so no colour is introduced;
                    the top-lit sheen reads as brushed metal against the
                    flat white second line. */}
                <span className={`block ${METALLIC_TEXT}`}>
                  Four capabilities.
                </span>
                <span className="block">One pipeline.</span>
              </h2>
              <div className="flex items-center gap-2.5">
                <button
                  onClick={() => go(index - 1)}
                  aria-label="Previous capability"
                  className="pressable w-11 h-11 rounded-full border border-white/15 bg-white/[0.06] text-white inline-flex items-center justify-center text-lg hover:bg-white/[0.12] hover:border-white/30 transition-colors"
                >
                  ←
                </button>
                <button
                  onClick={() => go(index + 1)}
                  aria-label="Next capability"
                  className="pressable w-11 h-11 rounded-full bg-white text-black inline-flex items-center justify-center text-lg hover:bg-white/80 transition-colors shadow-[0_12px_28px_rgba(0,0,0,0.4)]"
                >
                  →
                </button>
              </div>
            </div>

            {/* Slider — capped width (less breadth than before), same card
                height. Pause handlers + drag/track behaviour unchanged. */}
            <div
              className="max-w-[520px] mr-auto"
              onMouseEnter={() => setPaused(true)}
              onMouseLeave={() => setPaused(false)}
              onTouchStart={() => setPaused(true)}
              onTouchEnd={() => setPaused(false)}
            >
            {/* Viewport clips the track — exactly one card is ever visible.
                Each slide is w-full; the track translates -100% per index,
                sliding the next card in (Skiper 51-style). Drag/swipe moves
                the track freely; on release it snaps to the nearest card. */}
            <div className="overflow-hidden rounded-2xl">
              <motion.div
                ref={trackRef}
                className={`flex touch-pan-y ${
                  reducedMotion ? "" : "cursor-grab active:cursor-grabbing"
                }`}
                drag={reducedMotion ? false : "x"}
                dragElastic={0.08}
                dragMomentum={false}
                // Pause autoplay for the gesture so a tick can't shift the
                // target under the pointer; resume on release.
                onDragStart={() => setPaused(true)}
                onDragEnd={(_, info) => {
                  setPaused(false);
                  const el = trackRef.current;
                  const step = el ? el.offsetWidth : 0;
                  if (!step) return;
                  // Snap to the nearest card (round = 50% of a card
                  // threshold). Left drag (negative offset) advances;
                  // right drag retreats.
                  const shift = Math.round(info.offset.x / step);
                  if (shift !== 0) go(index - shift);
                }}
                animate={{ x: `-${index * 100}%` }}
                transition={
                  reducedMotion
                    ? { duration: 0 }
                    : { duration: 0.55, ease: EASE.out }
                }
              >
                {CAPABILITIES.map((cap) => (
                  <div key={cap.index} className="w-full shrink-0 px-0.5">
                    <div className="glass-dark relative p-7 sm:p-8 flex flex-col h-full min-h-[320px]">
                      <span className="font-display text-sm font-semibold text-white tracking-[0.2em]">
                        {cap.index}
                      </span>
                      {/* Same metallic silver treatment as the section
                          headings — the card titles read as brushed metal
                          against the dark glass. */}
                      <h3 className={`font-display text-2xl font-semibold tracking-tight mt-3 ${METALLIC_TEXT}`}>
                        {cap.title}
                      </h3>
                      <p className="text-white leading-relaxed text-[0.95rem] mt-3 flex-1">
                        {cap.desc}
                      </p>
                      <div className="flex flex-wrap gap-2 mt-6 pt-5 border-t border-white/10">
                        {cap.tags.map((t) => (
                          <span
                            key={t}
                            className="inline-flex items-center gap-1.5 text-xs font-medium text-white"
                          >
                            <span className="w-1.5 h-1.5 rounded-full bg-white" />
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                ))}
              </motion.div>
            </div>

            {/* Dots */}
            <div className="flex items-center justify-center gap-2 mt-8">
              {CAPABILITIES.map((cap, i) => (
                <button
                  key={cap.index}
                  onClick={() => go(i)}
                  aria-label={`Go to ${cap.title}`}
                  className={`h-1.5 rounded-full transition-all duration-300 ${
                    i === index
                      ? "w-8 bg-white"
                      : "w-1.5 bg-white/25 hover:bg-white/50"
                  }`}
                />
              ))}
            </div>
          </div>
          </motion.div>
        </div>


      </div>
    </motion.section>
  );
}

/* ── Statement band — the eight dimensions ────────────────────────────── */

const DIMENSIONS = [
  "Transparency",
  "Accountability",
  "Privacy",
  "Safety",
  "Human Autonomy",
  "Inclusivity",
  "Fairness",
  "Environmental Sustainability",
];

function StatementBand() {
  /* The reveal replays on EVERY scroll-in, driven by a scroll listener. */
  const { ref: gridRef, inView } = useInViewReplay<HTMLDivElement>(60);
  /* Page-glide: this section is "page three" — rises in, settles, glides out. */
  const { ref: bandPageRef, style: bandPageStyle } = usePageGlide();
  return (
    <motion.section
      ref={bandPageRef}
      style={bandPageStyle}
      className="relative z-10 min-h-screen flex flex-col justify-center py-20 sm:py-24 snap-start"
    >
      <div ref={gridRef} className="relative w-full max-w-7xl mx-auto px-6 sm:px-10 grid lg:grid-cols-[1.05fr_0.95fr] gap-14 lg:gap-16 items-center">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
          transition={{ duration: 0.6, ease: EASE.out }}
        >
          {/* Eyebrow in the same metallic silver treatment. */}
          <p
            className={`text-[11px] sm:text-xs font-semibold uppercase tracking-[0.24em] mb-5 ${METALLIC_TEXT}`}
          >
            The Method
          </p>
          <h2
            className={`font-display text-3xl sm:text-5xl lg:text-[3.4rem] font-semibold text-white tracking-tight leading-[1.12] ${TEXT_GLOW}`}
          >
            {/* Same metallic silver treatment as "Four capabilities." —
                the promise lines read as brushed metal, while the third
                line stays plain white. */}
            <span className={`block ${METALLIC_TEXT}`}>One document.</span>
            <span className={`block ${METALLIC_TEXT}`}>Eight dimensions.</span>
            <span className="block text-white">Every claim traced to evidence.</span>
          </h2>          <div className="flex flex-wrap gap-3 sm:gap-4 mt-9">
            <a
              href="/workspace"
              className="clay-button pressable inline-flex items-center gap-2 text-[#0A0A0A] px-6 py-3 font-semibold text-sm"
            >
              Benchmark your policy <span aria-hidden>→</span>
            </a>
            <a
              href="/analysis"
              className="glass-button pressable inline-flex items-center gap-2 text-white px-6 py-3 font-medium text-sm"
            >
              View a sample analysis
            </a>
          </div>
        </motion.div>

        {/* The eight dimensions, staggered in */}
        <motion.div
          variants={staggerContainer(0.07, 0.1)}
          initial="hidden"
          animate={inView ? "show" : "hidden"}
          className="glass-dark p-7 sm:p-9"
        >
          {/* Same metallic silver treatment — the section label matches
              the heading language of the rest of the page. */}
          <motion.p
            variants={staggerChild}
            className={`text-xs font-semibold uppercase tracking-[0.2em] mb-6 ${METALLIC_TEXT}`}
          >
            The 8 assessed dimensions
          </motion.p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {DIMENSIONS.map((d) => (
              <motion.div
                key={d}
                variants={staggerChild}
                className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.06] px-4 py-3 text-base font-medium text-white hover:bg-white/[0.12] hover:border-white/20 transition-colors"
              >
                <span className="w-2 h-2 rounded-full bg-white shrink-0" />
                {d}
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>
    </motion.section>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────── */

export default function Home() {
  const reducedMotion = useReducedMotionPref();
  /* `active` gates the intro's entrance animations — they fire only when
     the preloader's stairs start lifting, so the landing page visibly
     arrives beneath them. `showPreloader` unmounts the overlay at the end. */
  const [active, setActive] = useState(false);
  const [showPreloader, setShowPreloader] = useState(true);

  /* The landing page is full-bleed black. Paint the DOCUMENT (html)
     background black so overscroll past the bottom shows black, not the
     app's light body colour — html's background is the very first paint
     layer, so it can never cover the fixed waves. The BODY background must
     stay TRANSPARENT (NOT black): body is an in-flow element, which per
     CSS painting order paints AFTER negative-z-index layers, so an opaque
     body background would silently cover the -z-10 wave canvas. Also clip
     horizontal overflow at the document level (the full-bleed w-screen
     wrapper is 100vw wide — wider than the visible viewport once the
     vertical scrollbar takes its width, which would otherwise show a
     sideways scroller). All scoped to this page and restored on unmount. */
  useEffect(() => {
    const root = document.documentElement;
    const prevRootBg = root.style.background;
    const prevRootOx = root.style.overflowX;
    const prevBodyBg = document.body.style.background;
    root.style.background = "#000000";
    root.style.overflowX = "clip";
    document.body.style.background = "transparent";
    return () => {
      root.style.background = prevRootBg;
      root.style.overflowX = prevRootOx;
      document.body.style.background = prevBodyBg;
    };
  }, []);

  return (
    /* Full-bleed wrapper: -mt-24 cancels main's pt-24 and -mb-8 cancels
       main's pb-8, so content runs edge to edge vertically. Horizontally we
       break the wrapper out of main's max-w-7xl so it spans the exact
       viewport at ANY screen width: w-screen (100vw) + margin-left
       calc(50% - 50vw) — 50% of the containing block re-centers the
       viewport-wide box precisely. (A plain -mx-4 would only cancel main's
       px-4, leaving the wrapper capped at main's 1280px on wide monitors.)
       overflow-x-clip stays as a safety net for horizontal overflow.

       No background here on purpose: a background on this (non-stacking-
       context) wrapper would paint ABOVE the fixed canvas's -z-10 layer per
       CSS painting order, silently covering the waves. The fixed canvas
       itself paints above the white body background and below all content,
       so it is the only backdrop needed — including during overscroll
       rubber-band, since fixed elements move with the page. */
    <div
      className="overflow-x-clip -mt-24 -mb-8 w-screen relative flex flex-col"
      style={{ marginLeft: "calc(50% - 50vw)" }}
    >
      {/* Constant full-page animated backdrop (React Bits GradientWaves) —
          ONE fixed canvas behind everything, edge to edge, never covered,
          identical no matter how far the page scrolls. -z-10 keeps it below
          all content while painting above the black document background;
          every section above it is translucent, so the waves stay visible
          for the entire page height. Reduced-motion users get a static
          gradient instead of the shader.

          Solid BLACK backing: the shader's alpha is the fog ratio, so the
          configured black horizon (#000000) is written transparent in the
          far sky and would otherwise show the white body through it. The
          black backdrop is what actually renders the horizon — the canvas
          only adds the grey/white wave bodies on top. */}
      <div
        className="fixed inset-0 -z-10 pointer-events-none"
        aria-hidden
        style={{ background: "#000000" }}
      >
        {reducedMotion ? (
          <div
            className="h-full w-full"
            style={{
              background:
                "linear-gradient(180deg, #1A1A1A 0%, #0A0A0A 55%, #141414 100%)",
            }}
          />
        ) : (
          <GradientWaves
            horizonColor="#000000"
            waveColor="#909090"
            crestColor="#ffffff"
            speed={0.4}
            amplitude={2.5}
            waveScale={0.6}
            waveRatio={0.9}
            swell={35}
            turbulence={20}
            tilt={1.11}
            zoom={1.0}
            height={5.5}
            fogDepth={15}
            detail="medium"
            brightness={1.0}
            opacity={1.0}
            mouseInteraction={true}
            parallaxStrength={0.5}
            grain={true}
            grainIntensity={0.05}
          />
        )}
      </div>

      {/* Skiper 9-style entrance: the brand name blurs in on black, the
          staircase sweeps over it, then the stairs drop away to reveal the
          intro — which animates in as they lift (active). Reduced-motion
          users skip straight to the content. */}
      {showPreloader && (
        <Preloader
          reduced={reducedMotion}
          onReveal={() => setActive(true)}
          onDone={() => setShowPreloader(false)}
        />
      )}

      {/* Intro (brand + capabilities carousel) first — scroll past it and
          the pipeline hero pins in below. The IntroSection carries the
          real page-level h1; the hero's four stage headlines are h2s. */}
      <IntroSection active={active} />
      <PipelineHero />
      <StatementBand />
    </div>
  );
}
