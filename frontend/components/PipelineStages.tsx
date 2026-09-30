"use client";

/**
 * The four workflow stages, animated: ingestion, retrieval, analysis, brief.
 *
 * Every animation runs on timers and plain CSS transitions rather than
 * motion delays or AnimatePresence: when requestAnimationFrame stalls
 * (embedded webviews, hidden panes) a delay never elapses and content would
 * sit at opacity zero. Timers keep firing, so nothing here can go invisible.
 *
 * Each stage replays whenever it scrolls back into view, which is what makes
 * the section worth scrolling through twice.
 */

import { useEffect, useRef, useState } from "react";
import { ScreenPanel } from "@/components/ProductFrames";

import palette from "@/lib/palette.json";
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
/**
 * Advances 0..steps once `active`, one step every `everyMs`, with an
 * independent deadline beside the chain.
 *
 * The chain is one timeout per step, and a backgrounded or non-composited
 * tab clamps repeat timers to roughly a second — so a seven-step sequence
 * authored at 190ms runs for seven SECONDS there, with the later steps
 * still invisible. The deadline is a single timeout armed once for the
 * whole budget, and a lone long timeout is not subject to that clamp.
 *
 * The same fix already lives in ProductFrames' copy of this hook. Two
 * copies of the same hook is one too many; they should be extracted the
 * next time either is touched.
 */
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

  useEffect(() => {
    if (!active) return;
    const deadline = setTimeout(() => setStep(steps), steps * everyMs + 900);
    return () => clearTimeout(deadline);
  }, [active, steps, everyMs]);

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
          <span className="text-[11px] font-mono text-black/62 truncate">
            national-ai-strategy.pdf
          </span>
          <span className="ml-auto text-[10px] font-mono uppercase tracking-[0.14em] text-status-green border border-status-green/40 rounded px-1.5 py-0.5">
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
            /* The scan line carries no glow: this page has no shadows. */
            className="pointer-events-none absolute left-4 right-4 h-[2px] rounded-full bg-black animate-[stage-scan_3.2s_ease-in-out_infinite]"
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
          <div className="absolute left-1/2 top-1/2 w-28 h-40 -translate-x-1/2 -translate-y-1/2 rounded-lg border border-black/15 bg-white p-3 flex flex-col gap-2.5">
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
                className="absolute left-1/2 top-1/2 rounded-lg border border-black/12 bg-white/95 p-2.5 flex flex-col gap-1.5"
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
                <span className="text-[9px] font-mono text-black/62">384-d</span>
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
                <span className="text-[10px] font-mono uppercase tracking-[0.16em] text-black/62 border border-black/15 rounded px-1.5 py-0.5">
                  {c.chip}
                </span>
                <span className="text-base sm:text-lg font-medium text-black/85">
                  {c.title}
                </span>
              </div>
              {i === 0 && (
                <div className="flex items-center gap-4 mb-4 text-[11px] text-black/60">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full" style={{ background: palette.chart.partial }} />
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
                <p className="pt-4 text-[10px] font-mono uppercase tracking-[0.14em] text-black/62">
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
        <span className="self-start text-[10px] font-mono uppercase tracking-[0.16em] text-black/62 border border-black/15 rounded px-1.5 py-0.5">
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
              className="text-[10px] font-mono text-black/62 border border-black/12 rounded px-1 py-0.5"
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
/* The pipeline's own names, the same words an evaluator finds in the
   repository. The bodies are written to one length (~150 characters, two
   lines at the section's measure) so the four rows read as four of one
   thing. */
const STAGES = [
  {
    n: "01",
    name: "Ingestion",
    body: "The document is split on its own headings, paragraphs intact. Nothing is summarised away before it is scored, and nothing is scored out of context.",
    Visual: IngestionVisual,
  },
  {
    n: "02",
    name: "Retrieval",
    body: "Each passage is embedded and ranked per governance dimension, so a reading sees the paragraphs that bear on it and none of the ones that do not.",
    Visual: RetrievalVisual,
  },
  {
    n: "03",
    name: "Analysis",
    body: "Eight readings against the frameworks that govern them. Deterministic guardrails sit under each verdict, so it is not one the model can talk itself into.",
    Visual: AnalysisVisual,
  },
  {
    n: "04",
    name: "Brief",
    body: "The findings become a document a minister can act on: what is covered, what is missing, what to do first, and the citation behind every line.",
    Visual: BriefVisual,
  },
];

/* One stage, as a row. The sticky deck this replaces was a clever device
   that cost the section its readability: three of the four cards spent most
   of their scroll buried under the one on top, and a pipeline whose steps
   you cannot see side by side is not showing you a pipeline. Rows let all
   four be compared, and the alternation gives the eye somewhere new to land
   on each one. */
function StageRow({
  stage,
  index,
}: {
  stage: (typeof STAGES)[number];
  index: number;
}) {
  const { ref, inView } = useInViewReplay<HTMLDivElement>(120);
  const visualFirst = index % 2 === 1;
  return (
    <div
      ref={ref}
      className={`l-stage-row${inView ? " in" : ""}`}
      data-visual-first={visualFirst ? "true" : "false"}
    >
      <div className="l-stage-copy">
        <div className="l-stage-head">
          <span className="l-stage-n">{stage.n}</span>
          <h3 className="l-stage-name">{stage.name}</h3>
        </div>
        <p className="l-body l-stage-body">{stage.body}</p>
      </div>
      <div className="l-stage-visual">
        <StageVisual stage={stage} />
      </div>
    </div>
  );
}

export default function PipelineStages() {
  return (
    <div className="l-stages">
      {STAGES.map((s, i) => (
        <StageRow key={s.n} stage={s} index={i} />
      ))}
    </div>
  );
}

/* The visual replays whenever its row is on screen. */
function StageVisual({ stage }: { stage: (typeof STAGES)[number] }) {
  const { ref, inView } = useInViewReplay<HTMLDivElement>();
  const { Visual } = stage;
  return (
    <div ref={ref}>
      <Visual active={inView} />
    </div>
  );
}
