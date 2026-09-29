"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FileDown, FileText } from "lucide-react";
import { motion } from "motion/react";
import { EASE } from "@/lib/motion";
import { api, API_UNREACHABLE, Workspace, BriefDocument } from "@/lib/api";
import AnimatedSelect from "@/components/AnimatedSelect";
import ShineButton from "@/components/ShineButton";
import InkReveal from "@/components/InkReveal";
import { byCountryOrder } from "@/lib/countryOrder";

import palette from "@/lib/palette.json";
import PageHeader from "@/components/PageHeader";

/* The two downloads, each in the colour its format is known by, so the
   pair reads at a glance and neither is mistaken for the primary action. */
const DOWNLOAD_LOOK = {
  pdf: "border-file-pdf-line bg-file-pdf-tint text-file-pdf hover:border-file-pdf/50 hover:shadow-[0_6px_18px_-8px_rgba(154,63,55,0.45)]",
  docx: "border-file-docx-line bg-file-docx-tint text-file-docx hover:border-file-docx/50 hover:shadow-[0_6px_18px_-8px_rgba(46,90,140,0.45)]",
} as const;
/* Scroll reveals in the brief play once, a little before the element is
   fully in view, so reading down never waits on them. */
const IN_VIEW = { once: true, margin: "0px 0px -8% 0px" } as const;

/* A section heading whose rule draws out from the title as it comes into
   view, the way a ruled document is set. */
function SectionHeading({ index, children }: { index: string; children: React.ReactNode }) {
  return (
    <motion.div
      className="flex items-center gap-3 mt-10 mb-4"
      initial="hidden"
      whileInView="shown"
      viewport={IN_VIEW}
    >
      <motion.span
        variants={{ hidden: { opacity: 0, y: 6 }, shown: { opacity: 1, y: 0 } }}
        transition={{ duration: 0.4, ease: EASE.out }}
        className="text-[11px] font-bold tracking-[0.14em] text-grey-950/40 tabular-nums"
      >
        {index}
      </motion.span>
      <motion.h2
        variants={{ hidden: { opacity: 0, y: 6 }, shown: { opacity: 1, y: 0 } }}
        transition={{ duration: 0.45, ease: EASE.out, delay: 0.05 }}
        className="text-lg font-bold text-grey-950 tracking-tight"
      >
        {children}
      </motion.h2>
      <motion.div
        variants={{ hidden: { scaleX: 0 }, shown: { scaleX: 1 } }}
        transition={{ duration: 0.8, ease: EASE.out, delay: 0.12 }}
        className="h-px flex-1 origin-left bg-black/[0.10]"
      />
    </motion.div>
  );
}

function BulletList({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) {
    return <p className="text-sm text-grey-600 italic">{empty}</p>;
  }
  return (
    <ul className="space-y-2.5">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2.5 text-sm leading-relaxed text-grey-900">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-grey-950/50" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export default function BriefPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWs, setSelectedWs] = useState("");
  // The country on screen now, for replies that arrive later. Generating a
  // brief takes ~20s; switching country meanwhile showed the finished brief
  // under the wrong name, and a slow cached read did the same.
  const currentWs = useRef("");
  currentWs.current = selectedWs;
  const [brief, setBrief] = useState<BriefDocument | null>(null);
  const [cached, setCached] = useState(false);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState<"pdf" | "docx" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    api
      .listWorkspaces()
      .then(setWorkspaces)
      .catch((e) =>
        setError(
          `Couldn't load the workspace list. ${e instanceof Error ? e.message : ""}`.trim()
        )
      );
  }, []);

  const loadCached = useCallback(async (wsId: string) => {
    if (!wsId) return;
    setBrief(null);
    setCached(false);
    setError(null);
    setInfo(null);
    try {
      const b = await api.getBrief(wsId);
      if (currentWs.current !== wsId) return;
      setBrief(b);
      setCached(true);
    } catch (e) {
      if (currentWs.current !== wsId) return;
      setBrief(null); // a 404 means nothing is cached yet: not an error
      if (e instanceof Error && e.message === API_UNREACHABLE) setError(e.message);
    }
  }, []);

  async function generate() {
    const wsId = selectedWs;
    if (!wsId) return;
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const b = await api.generateBrief(wsId);
      if (currentWs.current !== wsId) return;
      setBrief(b);
      setCached(false);
      setInfo(
        "Brief generated from the stored, citation-verified analysis results — one synthesis call."
      );
    } catch (e) {
      if (currentWs.current === wsId)
        setError(e instanceof Error ? e.message : "Failed to generate brief");
    } finally {
      setLoading(false);
    }
  }

  async function download(format: "pdf" | "docx") {
    if (!selectedWs) return;
    setExporting(format);
    setError(null);
    try {
      await api.downloadBrief(selectedWs, format);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setExporting(null);
    }
  }

  const s = brief?.sections;
  // Render-order section numbering. Reset on every render so the counter does
  // not accumulate across re-renders; JSX below evaluates top-to-bottom, so
  // calling this in place yields 01, 02, 03 ... skipping absent sections.
  let sectionCounter = 0;
  const nextIndex = () => String(++sectionCounter).padStart(2, "0");

  return (
    <div className="space-y-8">
      <PageHeader
        title="Executive Brief"
        animated={<InkReveal text="Executive Brief" />}
        subtitle="A concise synthesis of the analysis."
      />

      {/* Controls */}
      <div className="bg-white rounded-xl border border-black/[0.10] shadow-sm p-5">
        <div className="flex flex-wrap gap-4 items-end">
          <div className="flex-1 min-w-[260px]">
            <label className="block text-base font-semibold text-grey-950 mb-1.5">
              Select Workspace
            </label>
            {/* Same dropdown component as the Analysis page — identical
                look and identical scrollbar, so the two pages feel one. */}
            <AnimatedSelect
              value={selectedWs}
              onChange={(v) => {
                setSelectedWs(v);
                loadCached(v);
              }}
              placeholder="Choose a workspace with a completed analysis..."
              options={workspaces
                .filter((ws) => ws.status === "complete")
                .sort(byCountryOrder)
                .map((ws) => ({
                  value: ws.id,
                  label: `${ws.country} — ${ws.policy_title}`,
                }))}
            />
          </div>
          {/* The black shine button generates, and regenerates once a brief
              exists (an example workspace keeps the brief it ships with).
              generate() no-ops without a selection, so it is disabled only
              while a call is in flight. */}
          {brief && workspaces.find((w) => w.id === selectedWs)?.locked ? null : (
            <ShineButton disabled={loading} onClick={generate}>
              {loading ? "Generating..." : brief ? "Regenerate Brief" : "Generate Brief"}
            </ShineButton>
          )}
          {brief &&
            (["pdf", "docx"] as const).map((fmt) => (
              <button
                key={fmt}
                type="button"
                onClick={() => download(fmt)}
                disabled={exporting !== null}
                className={`pressable inline-flex items-center gap-2 rounded-xl border px-5 py-[13px] text-[15px] font-semibold transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-0.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-black disabled:cursor-not-allowed disabled:opacity-50 ${DOWNLOAD_LOOK[fmt]}`}
              >
                {fmt === "pdf" ? (
                  <FileDown aria-hidden className="h-4 w-4" />
                ) : (
                  <FileText aria-hidden className="h-4 w-4" />
                )}
                {exporting === fmt
                  ? "Preparing..."
                  : fmt === "pdf"
                    ? "Download PDF"
                    : "Download Word"}
              </button>
            ))}
        </div>
        {cached && !info && (
          <p className="mt-3 text-xs text-grey-600">
            Downloads contain exactly the brief shown here.
          </p>
        )}
        {info && (
          <div className="mt-3 rounded-lg bg-grey-950/5 border border-grey-950/10 px-4 py-2.5 text-sm text-grey-950">
            {info}
          </div>
        )}
        {error && (
          <div role="alert" className="mt-3 rounded-lg bg-status-red-tint border border-status-red-line px-4 py-2.5 text-sm text-status-red">
            {error}
          </div>
        )}
      </div>

      {/* Brief preview */}
      {brief && s && (
        <motion.div
          key={brief.workspace_id}
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, ease: EASE.out }}
          className="bg-white rounded-xl border border-black/[0.10] shadow-sm overflow-hidden"
        >
          {/* Title block */}
          <div className="border-b border-black/[0.10] bg-gradient-to-b from-grey-950/5 to-transparent px-8 py-8 text-center">
            <p className="text-[11px] font-bold tracking-[0.18em] text-grey-600 uppercase">
              AI Governance Assessment Brief
            </p>
            <h2 className="mt-2 text-2xl font-bold text-grey-950 tracking-tight">
              {brief.country} — {brief.policy_title}
            </h2>
          </div>

          <div className="px-8 py-6">
            {/* Section numbers are assigned in render order rather than
                hardcoded: several sections below are conditional (a run with
                no gaps has no roadmap), and fixed indices skipped numbers or
                repeated them as soon as one was absent. */}
            {/* EXECUTIVE SUMMARY */}
            <SectionHeading index={nextIndex()}>Executive Summary</SectionHeading>
            <p className="text-sm leading-relaxed text-grey-900 max-w-3xl">
              {s.executive_summary}
            </p>

            {/* KEY FINDINGS */}
            <SectionHeading index={nextIndex()}>Key Findings</SectionHeading>
            <div className="space-y-5 max-w-3xl">
              <div>
                <h3 className="text-sm font-bold text-grey-800 mb-2">
                  Areas of Strength
                </h3>
                <BulletList items={s.areas_of_strength} empty="None identified." />
              </div>
              <div>
                <h3 className="text-sm font-bold text-grey-800 mb-2">
                  Areas Requiring Attention
                </h3>
                <BulletList items={s.areas_requiring_attention} empty="None identified." />
              </div>
            </div>

            {/* DIMENSION ASSESSMENT — deterministic per-dimension detail */}
            {(s.dimension_assessment?.length ?? 0) > 0 && (
              <>
                <SectionHeading index={nextIndex()}>Dimension Assessment</SectionHeading>
                <div className="max-w-3xl divide-y divide-grey-950/10">
                  {s.dimension_assessment!.map((r, ri) => (
                    <motion.div
                      key={r.dimension}
                      initial={{ opacity: 0, y: 10 }}
                      whileInView={{ opacity: 1, y: 0 }}
                      viewport={IN_VIEW}
                      transition={{ duration: 0.45, ease: EASE.out, delay: (ri % 4) * 0.04 }}
                      className="-mx-3 rounded-lg px-3 py-3 transition-colors duration-200 hover:bg-grey-950/[0.025]"
                    >
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className="text-sm font-semibold text-grey-950">
                          {r.dimension}
                        </span>
                        <span className="text-xs font-semibold uppercase tracking-wide text-grey-600">
                          {r.coverage}
                          {r.depth ? ` · ${r.depth}` : ""}
                        </span>
                      </div>
                      {r.basis && (
                        <p className="mt-1 text-sm leading-relaxed text-grey-800">
                          {r.basis}
                        </p>
                      )}
                      {(r.in_place?.length ?? 0) > 0 && (
                        <p className="mt-1.5 text-xs leading-relaxed text-grey-700">
                          <span className="font-semibold text-grey-950">Named in the document:</span>{" "}
                          {r.in_place!.join("; ")}
                        </p>
                      )}
                      {r.absent_mechanisms.length > 0 && (
                        <p className="mt-1 text-xs leading-relaxed text-grey-700">
                          <span className="font-semibold text-grey-950">Not addressed:</span>{" "}
                          {r.absent_mechanisms.join(", ")}
                        </p>
                      )}
                      {r.key_provision && (
                        <blockquote className="mt-2 border-l-2 border-grey-950/20 pl-3">
                          <p className="text-[13px] italic leading-relaxed text-grey-800">
                            &ldquo;{r.key_provision.quote}&rdquo;
                          </p>
                          {r.key_provision.source && (
                            <footer className="mt-0.5 text-xs text-grey-600">
                              {r.key_provision.source}
                            </footer>
                          )}
                        </blockquote>
                      )}
                    </motion.div>
                  ))}
                </div>
              </>
            )}

            {/* PRIORITY RECOMMENDATIONS */}
            <SectionHeading index={nextIndex()}>Priority Recommendations</SectionHeading>
            {s.priority_recommendations.length === 0 ? (
              <p className="text-sm text-grey-600 italic">
                No critical gaps identified — no priority actions required.
              </p>
            ) : (
              <ol className="space-y-3 max-w-3xl">
                {s.priority_recommendations.map((r, i) => (
                  <motion.li
                    key={i}
                    initial={{ opacity: 0, x: -10 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={IN_VIEW}
                    transition={{ duration: 0.45, ease: EASE.out, delay: i * 0.07 }}
                    className="flex gap-3"
                  >
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-grey-950 text-[11px] font-bold text-white">
                      {i + 1}
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-grey-950 leading-snug">
                        {r.recommendation}
                      </p>
                      {r.rationale && (
                        <p className="mt-0.5 text-sm text-grey-700 leading-snug">
                          {r.rationale}
                        </p>
                      )}
                    </div>
                  </motion.li>
                ))}
              </ol>
            )}

            {/* IMPLEMENTATION ROADMAP — sequenced Module 3 actions */}
            {(s.implementation_roadmap?.length ?? 0) > 0 && (
              <>
                <SectionHeading index={nextIndex()}>Implementation Roadmap</SectionHeading>
                <div className="max-w-3xl space-y-5">
                  {s.implementation_roadmap!.map((item) => (
                    <div key={item.dimension}>
                      <p className="text-sm font-semibold text-grey-950">
                        {item.dimension}{" "}
                        <span className="font-normal text-grey-600">({item.coverage})</span>
                      </p>
                      {item.responsible_agency && (
                        <p className="mt-0.5 text-xs text-grey-600">
                          Responsible body: {item.responsible_agency}
                        </p>
                      )}
                      {item.phases.map((ph, pi) => (
                        <div key={pi} className="mt-2 border-l-2 border-grey-950/15 pl-3">
                          <p className="text-xs font-semibold uppercase tracking-wide text-grey-600">
                            {ph.phase}
                            {ph.timeline ? ` · ${ph.timeline}` : ""}
                          </p>
                          {ph.objective && (
                            <p className="text-sm text-grey-900">{ph.objective}</p>
                          )}
                          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-grey-800">
                            {ph.steps.map((st, si) => (
                              <li key={si}>{st}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                      {item.monitoring.length > 0 && (
                        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-grey-600">
                          {item.monitoring.map((mc, mi) => (
                            <li key={mi}>Monitor: {mc}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* EVIDENCE BASE — what the verdicts rest on */}
            {(s.evidence_base?.citations_total ?? 0) > 0 && (
              <>
                <SectionHeading index={nextIndex()}>Evidence Base</SectionHeading>
                <p className="text-sm leading-relaxed text-grey-900 max-w-3xl">
                  {s.evidence_base!.citations_verified} of{" "}
                  {s.evidence_base!.citations_total} citations were verified against
                  their source passage.
                </p>
                {s.evidence_base!.representative_quotes.length > 0 && (
                  <ul className="mt-2 max-w-3xl space-y-2">
                    {s.evidence_base!.representative_quotes.map((q, qi) => (
                      <li key={qi} className="border-l-2 border-grey-950/15 pl-3">
                        <span className="text-xs font-semibold text-grey-950">
                          {q.dimension}
                        </span>
                        <p className="text-sm italic leading-relaxed text-grey-800">
                          &ldquo;{q.quote}&rdquo;
                        </p>
                        {q.source && (
                          <p className="text-xs text-grey-600 mt-0.5">{q.source}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}

            {/* RELEVANT PRECEDENT */}
            {s.relevant_precedent && (
              <>
                <SectionHeading index={nextIndex()}>Relevant Precedent</SectionHeading>
                <p className="text-sm leading-relaxed text-grey-900 max-w-3xl">
                  {s.relevant_precedent}
                </p>
              </>
            )}

            {/* SCOPE & METHODOLOGY */}
            <SectionHeading index={nextIndex()}>
              Scope &amp; Methodology
            </SectionHeading>
            <div className="space-y-3 max-w-3xl">
              {s.scope_and_methodology.split("\n\n").map((para, i) => (
                <p key={i} className="text-xs leading-relaxed text-grey-600">
                  {para}
                </p>
              ))}
            </div>

            {/* Generated-stamp footer — on the card only, never in the
                PDF/DOCX exports. */}
            <div className="mt-8 border-t border-black/[0.10] pt-4 text-center">
              <p className="text-xs text-grey-600">
                Generated {brief.generated_at} · Based on analysis of{" "}
                {brief.num_dimensions} governance dimensions
              </p>
            </div>
          </div>
        </motion.div>
      )}

      {!brief && selectedWs && !loading && (
        <div className="bg-white rounded-xl border border-dashed border-black/[0.20] px-8 py-12 text-center">
          <p className="text-sm text-grey-600">
            No brief exists for this workspace yet. Click{" "}
            <span className="font-semibold text-grey-950">Generate Brief</span> to synthesize
            one from the stored analysis.
          </p>
        </div>
      )}
    </div>
  );
}
