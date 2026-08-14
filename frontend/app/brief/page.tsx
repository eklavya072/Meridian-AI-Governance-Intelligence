"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Workspace, BriefDocument } from "@/lib/api";
import SpecularButton from "@/components/SpecularButton";
import AnimatedSelect from "@/components/AnimatedSelect";
import InkReveal from "@/components/InkReveal";

function SectionHeading({ index, children }: { index: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 mt-10 mb-4">
      <span className="text-[11px] font-bold tracking-[0.14em] text-navy-950/40 tabular-nums">
        {index}
      </span>
      <h2 className="text-lg font-bold text-navy-950 tracking-tight">{children}</h2>
      <div className="h-px flex-1 bg-[rgba(10,10,10,0.10)]" />
    </div>
  );
}

function BulletList({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) {
    return <p className="text-sm text-gray-500 italic">{empty}</p>;
  }
  return (
    <ul className="space-y-2.5">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2.5 text-sm leading-relaxed text-gray-800">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-navy-950/50" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export default function BriefPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWs, setSelectedWs] = useState("");
  const [brief, setBrief] = useState<BriefDocument | null>(null);
  const [cached, setCached] = useState(false);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState<"pdf" | "docx" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    api.listWorkspaces().then(setWorkspaces).catch(() => {});
  }, []);

  const loadCached = useCallback(async (wsId: string) => {
    if (!wsId) return;
    setBrief(null);
    setCached(false);
    setError(null);
    setInfo(null);
    try {
      const b = await api.getBrief(wsId);
      setBrief(b);
      setCached(true);
    } catch {
      setBrief(null); // 404 — nothing cached yet
    }
  }, []);

  async function generate() {
    if (!selectedWs) return;
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const b = await api.generateBrief(selectedWs);
      setBrief(b);
      setCached(false);
      setInfo(
        "Brief generated from the stored, citation-verified analysis results — one synthesis call."
      );
    } catch (e) {
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

  return (
    <div className="space-y-8">
      {/* Centered heading block, with the InkReveal entrance (words rise,
          a light sweeps across, a rule draws beneath). Size and colour are
          unchanged — only the text effect is added. */}
      <div className="text-center">
        <h1 className="text-[clamp(3.25rem,7vw,4rem)] leading-[1.05] font-extrabold text-navy-950 tracking-tight">
          <InkReveal text="Executive Brief" />
        </h1>
        <p className="text-sm text-gray-600 mt-2 max-w-2xl mx-auto">
          A concise synthesis of the analysis.
        </p>
      </div>

      {/* Controls */}
      <div className="bg-white rounded-xl border border-[rgba(10,10,10,0.10)] shadow-sm p-5">
        <div className="flex flex-wrap gap-4 items-end">
          <div className="flex-1 min-w-[260px]">
            <label className="block text-base font-semibold text-navy-950 mb-1.5">
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
                .map((ws) => ({
                  value: ws.id,
                  label: `${ws.country} — ${ws.policy_title}`,
                }))}
            />
          </div>
          {/* Primary action: the same black SpecularButton as the Analysis
              page's View Analysis. Once a brief exists it becomes a plain
              compact button — the same size as the download buttons it
              sits beside. generate() no-ops without a selection, so it
              never greys out; disabled only while a call is in flight. */}
          {brief ? (
            <button
              onClick={generate}
              disabled={loading}
              className="pressable border border-navy-950/20 text-navy-950 px-5 py-2.5 rounded-lg text-sm font-semibold hover:bg-navy-950/5 disabled:opacity-50 transition-colors"
            >
              {loading ? "Generating..." : "Regenerate Brief"}
            </button>
          ) : (
            <SpecularButton
              size="md"
              className="specular-button--compact"
              radius={12}
              tint="#0A0A0A"
              tintOpacity={1}
              blur={0}
              textColor="#ffffff"
              lineColor="#ffffff"
              baseColor="#0A0A0A"
              intensity={1.2}
              shineSize={10}
              shineFade={40}
              thickness={1.2}
              speed={0.35}
              followMouse
              proximity={250}
              autoAnimate={false}
              disabled={loading}
              onClick={generate}
            >
              {loading ? "Generating..." : "Generate Brief"}
            </SpecularButton>
          )}
          {brief && (
            <>
              <button
                onClick={() => download("pdf")}
                disabled={exporting !== null}
                className="pressable border border-navy-950/20 text-navy-950 px-5 py-2.5 rounded-lg text-sm font-semibold hover:bg-navy-950/5 disabled:opacity-50 transition-colors"
              >
                {exporting === "pdf" ? "Preparing..." : "Download PDF"}
              </button>
              <button
                onClick={() => download("docx")}
                disabled={exporting !== null}
                className="pressable border border-navy-950/20 text-navy-950 px-5 py-2.5 rounded-lg text-sm font-semibold hover:bg-navy-950/5 disabled:opacity-50 transition-colors"
              >
                {exporting === "docx" ? "Preparing..." : "Download DOCX"}
              </button>
            </>
          )}
        </div>
        {cached && !info && (
          <p className="mt-3 text-xs text-gray-500">
            Showing the cached brief — exports render from it without re-running the LLM call.
          </p>
        )}
        {info && (
          <div className="mt-3 rounded-lg bg-navy-950/5 border border-navy-950/10 px-4 py-2.5 text-sm text-navy-950">
            {info}
          </div>
        )}
        {error && (
          <div className="mt-3 rounded-lg bg-[#F6ECEB] border border-[#E4C9C6] px-4 py-2.5 text-sm text-[#A8483F]">
            {error}
          </div>
        )}
      </div>

      {/* Brief preview */}
      {brief && s && (
        <div className="bg-white rounded-xl border border-[rgba(10,10,10,0.10)] shadow-sm overflow-hidden">
          {/* Title block */}
          <div className="border-b border-[rgba(10,10,10,0.10)] bg-gradient-to-b from-navy-950/5 to-transparent px-8 py-8 text-center">
            <p className="text-[11px] font-bold tracking-[0.18em] text-navy-600 uppercase">
              AI Governance Assessment Brief
            </p>
            <h2 className="mt-2 text-2xl font-bold text-navy-950 tracking-tight">
              {brief.country} — {brief.policy_title}
            </h2>
          </div>

          <div className="px-8 py-6">
            {/* EXECUTIVE SUMMARY */}
            <SectionHeading index="01">Executive Summary</SectionHeading>
            <p className="text-sm leading-relaxed text-gray-800 max-w-3xl">
              {s.executive_summary}
            </p>

            {/* KEY FINDINGS */}
            <SectionHeading index="02">Key Findings</SectionHeading>
            <div className="space-y-5 max-w-3xl">
              <div>
                <h3 className="text-sm font-bold text-navy-800 mb-2">
                  Areas of Strength
                </h3>
                <BulletList items={s.areas_of_strength} empty="None identified." />
              </div>
              <div>
                <h3 className="text-sm font-bold text-navy-800 mb-2">
                  Areas Requiring Attention
                </h3>
                <BulletList items={s.areas_requiring_attention} empty="None identified." />
              </div>
            </div>

            {/* RISK OVERVIEW */}
            <SectionHeading index="03">Risk Overview</SectionHeading>
            <p className="text-sm leading-relaxed text-gray-800 max-w-3xl">
              {s.risk_overview.paragraph}
            </p>
            {s.risk_overview.high_priority_dimensions.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {s.risk_overview.high_priority_dimensions.map((d) => (
                  <span
                    key={d}
                    className="text-[11px] font-semibold text-white bg-navy-950 rounded-full px-3 py-1"
                  >
                    {d}
                  </span>
                ))}
              </div>
            )}

            {/* PRIORITY RECOMMENDATIONS */}
            <SectionHeading index="04">Priority Recommendations</SectionHeading>
            {s.priority_recommendations.length === 0 ? (
              <p className="text-sm text-gray-500 italic">
                No critical gaps identified — no priority actions required.
              </p>
            ) : (
              <ol className="space-y-3 max-w-3xl">
                {s.priority_recommendations.map((r, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-navy-950 text-[11px] font-bold text-white">
                      {i + 1}
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-navy-950 leading-snug">
                        {r.recommendation}
                      </p>
                      {r.rationale && (
                        <p className="mt-0.5 text-sm text-gray-600 leading-snug">
                          {r.rationale}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}

            {/* RELEVANT PRECEDENT */}
            {s.relevant_precedent && (
              <>
                <SectionHeading index="05">Relevant Precedent</SectionHeading>
                <p className="text-sm leading-relaxed text-gray-800 max-w-3xl">
                  {s.relevant_precedent}
                </p>
              </>
            )}

            {/* SCOPE & METHODOLOGY */}
            <SectionHeading index={s.relevant_precedent ? "06" : "05"}>
              Scope &amp; Methodology
            </SectionHeading>
            <div className="space-y-3 max-w-3xl">
              {s.scope_and_methodology.split("\n\n").map((para, i) => (
                <p key={i} className="text-xs leading-relaxed text-gray-500">
                  {para}
                </p>
              ))}
            </div>

            {/* Generated-stamp footer — on the card only, never in the
                PDF/DOCX exports. */}
            <div className="mt-8 border-t border-[rgba(10,10,10,0.10)] pt-4 text-center">
              <p className="text-xs text-gray-400">
                Generated {brief.generated_at} · Based on analysis of{" "}
                {brief.num_dimensions} governance dimensions
              </p>
            </div>
          </div>
        </div>
      )}

      {!brief && selectedWs && !loading && (
        <div className="bg-white rounded-xl border border-dashed border-[rgba(10,10,10,0.20)] px-8 py-12 text-center">
          <p className="text-sm text-gray-500">
            No brief exists for this workspace yet. Click{" "}
            <span className="font-semibold text-navy-950">Generate Brief</span> to synthesize
            one from the stored analysis.
          </p>
        </div>
      )}
    </div>
  );
}
