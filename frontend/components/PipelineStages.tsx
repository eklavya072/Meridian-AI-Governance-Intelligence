"use client";

/**
 * The four workflow stages, animated: ingestion, retrieval, analysis, brief.
 *
 * Ported from the earlier landing page, with every animation rebuilt on
 * timers and plain CSS transitions. The originals leaned on motion
 * transition delays and an AnimatePresence in "wait" mode, and both of those
 * have the same failure mode in this codebase: when requestAnimationFrame
 * stalls (embedded webviews, hidden panes), the delay never elapses and the
 * exit never reports done, so content sits at opacity zero forever. Timers
 * keep firing in those environments, so nothing here can go invisible.
 *
 * Each stage replays whenever it scrolls back into view, which is what makes
 * the section worth scrolling through twice.
 */

import { useEffect, useRef, useState } from "react";
import { ScreenPanel } from "@/components/ProductFrames";

/* Scroll-driven in-view detection, with a 500ms rect poll behind it. Some
   embedded webviews stop dispatching scroll events entirely, and an observer
   alone would leave every stage frozen at its start state. */
function useInViewReplay<T extends HTMLElement = HTMLElement>(margin = 80) {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      // Unmeasurable viewport means show it, never hide it. See LandingSections.
      if (!vh) {
        setInView(true);
        return;
      }
      setInView(r.top < vh - margin && r.bottom > margin);
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
  return { ref, inView };
}

/** Steps forward on a timer while active, and rewinds when it leaves view. */
function useSequence(active: boolean, steps: number, everyMs: number) {
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (!active) {
      setStep(0);
      return;
    }
    if (step >= steps) return;
    const t = setTimeout(() => setStep((s) => s + 1), everyMs);
    return () => clearTimeout(t);
  }, [active, step, steps, everyMs]);
  return step;
}

function Bar({ w, tone = "bg-black/10" }: { w: string; tone?: string }) {
  return <div className={`h-2.5 rounded-full ${tone} ${w}`} />;
}

/* ── 01 Ingestion ──────────────────────────────────────────────────────── */
function IngestionVisual({ active }: { active: boolean }) {
  return (
    <ScreenPanel>
      <div className="relative p-5 sm:p-7">
        <div className="flex items-center gap-2 mb-5">
          <span className="text-[11px] font-mono text-black/45 truncate">
            national-ai-strategy.pdf
          </span>
          <span className="ml-auto text-[10px] font-mono uppercase tracking-[0.14em] text-[#3F7A52] border border-[#3F7A52]/40 rounded px-1.5 py-0.5">
            Parsed
          </span>
        </div>
        <div className="space-y-3">
          <Bar w="w-11/12" tone="bg-black/20" />
          <Bar w="w-4/5" />
          <Bar w="w-9/12" />
          <Bar w="w-full" />
          <Bar w="w-10/12" />
          <Bar w="w-full" />
          <Bar w="w-3/4" />
        </div>
        {/* The scan. A pure CSS animation, so it runs on the compositor and
            never depends on JS state to be visible. */}
        {active && (
          <span
            aria-hidden
            className="pointer-events-none absolute left-4 right-4 h-[2px] rounded-full bg-[#0B0C0E] shadow-[0_0_16px_rgba(11,12,14,0.55)] animate-[stage-scan_3.2s_ease-in-out_infinite]"
          />
        )}
      </div>
    </ScreenPanel>
  );
}

/* ── 02 Retrieval ──────────────────────────────────────────────────────── */
const CHUNKS = [
  { x: -168, y: 62, w: 104 },
  { x: -92, y: -78, w: 88 },
  { x: 96, y: 86, w: 116 },
  { x: 170, y: -48, w: 94 },
  { x: -44, y: -34, w: 76 },
  { x: 48, y: 24, w: 96 },
];

function RetrievalVisual({ active }: { active: boolean }) {
  const step = useSequence(active, CHUNKS.length, 190);
  /* Same settle as the framework cards: once every chunk has been sent out,
     drop the transition so the finished positions hold even where the
     compositor never advances one. */
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    if (step < CHUNKS.length) {
      setSettled(false);
      return;
    }
    const t = setTimeout(() => setSettled(true), 1100);
    return () => clearTimeout(t);
  }, [step]);
  return (
    <ScreenPanel>
      <div className="relative h-[19rem] sm:h-[21rem] overflow-hidden">
        <div className="absolute inset-0 origin-center scale-[0.62] sm:scale-[0.82] lg:scale-100">
          {/* The document the chunks come out of. */}
          <div className="absolute left-1/2 top-1/2 w-28 h-40 -translate-x-1/2 -translate-y-1/2 rounded-lg border border-black/15 bg-white p-3 flex flex-col gap-2.5 shadow-sm">
            <Bar w="w-full" tone="bg-black/20" />
            <Bar w="w-4/5" tone="bg-black/12" />
            <Bar w="w-2/3" tone="bg-black/12" />
            <Bar w="w-11/12" tone="bg-black/12" />
          </div>
          {CHUNKS.map((c, i) => {
            const out = step > i;
            return (
              <div
                key={i}
                className="absolute left-1/2 top-1/2 rounded-lg border border-black/12 bg-white/95 p-2.5 flex flex-col gap-1.5 shadow-sm"
                style={{
                  transform: out
                    ? `translate(calc(-50% + ${c.x}px), calc(-50% + ${c.y}px)) scale(1)`
                    : "translate(-50%, -50%) scale(0.9)",
                  opacity: out ? 1 : 0,
                  transition: settled
                    ? "none"
                    : "transform 900ms cubic-bezier(0.22,1,0.36,1), opacity 500ms ease-out",
                }}
              >
                <div className="h-1.5 rounded bg-black/45" style={{ width: c.w }} />
                <div
                  className="h-1.5 rounded bg-black/15"
                  style={{ width: c.w * 0.7 }}
                />
                <span className="text-[9px] font-mono text-black/40">384-d</span>
              </div>
            );
          })}
        </div>
      </div>
    </ScreenPanel>
  );
}

/* ── 03 Analysis ───────────────────────────────────────────────────────── */
const CARDS = [
  { chip: "Analysis", title: "Transparency", footer: null as string | null },
  { chip: "Recommendations", title: "Recommendations & Alignment", footer: "Ranked by gap" },
  { chip: "Roadmap", title: "Implementation Roadmap", footer: "6 to 12 months" },
];

function AnalysisVisual({ active }: { active: boolean }) {
  const [card, setCard] = useState(0);
  useEffect(() => {
    if (!active) {
      setCard(0);
      return;
    }
    const t = setInterval(() => setCard((c) => (c + 1) % CARDS.length), 2400);
    return () => clearInterval(t);
  }, [active]);

  return (
    <ScreenPanel>
      {/* Stacked in one grid cell and crossfaded. An AnimatePresence in
          "wait" mode holds the incoming card until the outgoing one reports
          its exit finished, which never happens when rAF is stalled. */}
      <div className="grid h-[19rem] sm:h-[21rem] p-5 sm:p-7">
        {CARDS.map((c, i) => {
          const offset = i - card;
          const on = offset === 0;
          return (
            <div
              key={c.title}
              aria-hidden={!on}
              style={{
                gridArea: "1 / 1",
                opacity: on ? 1 : 0,
                transform: `translate3d(${on ? 0 : offset < 0 ? -60 : 60}px,0,0)`,
                transition:
                  "opacity 520ms cubic-bezier(0.22,1,0.36,1), transform 520ms cubic-bezier(0.22,1,0.36,1)",
              }}
            >
              <div className="flex flex-wrap items-center gap-2.5 mb-4">
                <span className="text-[10px] font-mono uppercase tracking-[0.16em] text-black/50 border border-black/15 rounded px-1.5 py-0.5">
                  {c.chip}
                </span>
                <span className="text-base sm:text-lg font-medium text-black/85">
                  {c.title}
                </span>
              </div>
              {i === 0 && (
                <div className="flex items-center gap-4 mb-4 text-[11px] text-black/60">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full" style={{ background: "#C9AF7A" }} />
                    Partially covered
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-black/40" />
                    Emerging
                  </span>
                </div>
              )}
              <div className="space-y-3">
                {["w-11/12", "w-10/12", "w-4/5", "w-9/12", "w-3/4"].map((w) => (
                  <Bar key={w} w={w} />
                ))}
              </div>
              {c.footer && (
                <p className="pt-4 text-[10px] font-mono uppercase tracking-[0.14em] text-black/40">
                  {c.footer}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </ScreenPanel>
  );
}

/* ── 04 Brief ──────────────────────────────────────────────────────────── */
const SCORES = [55, 82, 34, 68, 91, 47];

function BriefVisual({ active }: { active: boolean }) {
  // Summary lines, then the chart, then the citations.
  const step = useSequence(active, 4 + SCORES.length, 150);
  return (
    <ScreenPanel>
      <div className="p-5 sm:p-7 h-[19rem] sm:h-[21rem] flex flex-col">
        <span className="self-start text-[10px] font-mono uppercase tracking-[0.16em] text-black/50 border border-black/15 rounded px-1.5 py-0.5">
          Executive brief
        </span>
        <h4 className="mt-3 mb-5 text-base sm:text-lg font-medium text-black/85">
          AI Governance Assessment
        </h4>

        <div className="space-y-2.5">
          {["w-full", "w-11/12", "w-4/5"].map((w, i) => (
            <div
              key={w}
              className={`h-1.5 rounded-full ${i === 0 ? "bg-black/25" : "bg-black/12"} ${w}`}
              style={{
                transformOrigin: "left",
                transform: step > i ? "scaleX(1)" : "scaleX(0)",
                opacity: step > i ? 1 : 0,
                transition: "transform 460ms cubic-bezier(0.22,1,0.36,1), opacity 300ms",
              }}
            />
          ))}
        </div>

        <div className="mt-auto flex items-end gap-2.5 h-20 w-3/5 max-w-[240px]">
          {SCORES.map((h, i) => (
            <div
              key={i}
              className="flex-1 rounded-sm bg-black/55"
              style={{
                height: `${h}%`,
                transformOrigin: "bottom",
                transform: step > 3 + i ? "scaleY(1)" : "scaleY(0)",
                transition: "transform 480ms cubic-bezier(0.22,1,0.36,1)",
              }}
            />
          ))}
        </div>

        <div className="flex items-center gap-1.5 pt-5">
          {["[1]", "[2]", "[3]", "[4]"].map((c, i) => (
            <span
              key={c}
              className="text-[10px] font-mono text-black/45 border border-black/12 rounded px-1 py-0.5"
              style={{
                opacity: step >= 4 + SCORES.length ? 1 : 0,
                transform:
                  step >= 4 + SCORES.length ? "translateY(0)" : "translateY(4px)",
                transition: `opacity 360ms ease-out ${i * 70}ms, transform 360ms ease-out ${i * 70}ms`,
              }}
            >
              {c}
            </span>
          ))}
        </div>
      </div>
    </ScreenPanel>
  );
}

/* ── The section ───────────────────────────────────────────────────────── */
const STAGES = [
  {
    n: "01",
    name: "Ingestion",
    body: "The policy is read end to end and split on its own structure, headings and paragraphs kept intact. Nothing is summarised away before it is scored.",
    Visual: IngestionVisual,
  },
  {
    n: "02",
    name: "Retrieval",
    body: "Every passage is embedded and ranked per governance dimension, so each reading sees the paragraphs that actually bear on it and none of the ones that do not.",
    Visual: RetrievalVisual,
  },
  {
    n: "03",
    name: "Analysis",
    body: "Eight readings against the frameworks, then recommendations, then a roadmap. Deterministic guardrails sit under the verdict, so it is not something the model can talk itself into.",
    Visual: AnalysisVisual,
  },
  {
    n: "04",
    name: "Brief",
    body: "The findings become a document a minister can act on: what is covered, what is missing, what to do first, and the citation behind every line of it.",
    Visual: BriefVisual,
  },
];

function Stage({
  stage,
  index,
}: {
  stage: (typeof STAGES)[number];
  index: number;
}) {
  const { ref, inView } = useInViewReplay<HTMLDivElement>();
  const [entered, setEntered] = useState(false);
  const [settled, setSettled] = useState(false);
  const { Visual } = stage;
  const visualFirst = index % 2 === 0;

  /* The row's own entrance latches on first sight and never reverses, so a
     stage the visitor has already read cannot fade back out under them. The
     visual inside it still replays on every scroll-in, which is the part
     worth seeing twice. `settled` then asserts the finished state with the
     transition off, so a paused compositor cannot leave the row invisible. */
  useEffect(() => {
    if (!inView || entered) return;
    setEntered(true);
    const t = setTimeout(() => setSettled(true), 1400);
    return () => clearTimeout(t);
  }, [inView, entered]);

  return (
    <div
      ref={ref}
      className={`l-stage-row${entered ? " in" : ""}${settled ? " done" : ""}`}
      data-visual-first={visualFirst}
    >
      <div className="l-stage-visual">
        <Visual active={inView} />
      </div>
      <div className="l-stage-copy">
        <span className="l-label">{stage.n}</span>
        <h3 className="l-stage-name">{stage.name}</h3>
        <p className="l-body">{stage.body}</p>
      </div>
    </div>
  );
}

export default function PipelineStages() {
  return (
    <div className="l-stages">
      {STAGES.map((s, i) => (
        <Stage key={s.n} stage={s} index={i} />
      ))}
    </div>
  );
}
