"use client";

import { useEffect, useRef, useState } from "react";
import { api, Workspace, Analysis, Framework } from "@/lib/api";
import ProviderBadge from "@/components/ProviderBadge";
import AnimatedSelect from "@/components/AnimatedSelect";
import { byCountryOrder } from "@/lib/countryOrder";
import Button from "@/components/Button";
import ShineButton from "@/components/ShineButton";
import PageHeader from "@/components/PageHeader";
import { analysisDocuments, byStage } from "@/components/Heatmaps";
import { useChat } from "@/components/ChatProvider";
import { DecisionAnalyticsCard } from "@/components/analysis/DecisionAnalyticsCard";
import { DimensionBlock } from "@/components/analysis/DimensionBlock";
import { FrameworkLibraryContext } from "@/components/analysis/shared";

export default function AnalysisPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [frameworks, setFrameworks] = useState<Framework[]>([]);
  const [selectedWs, setSelectedWs] = useState<string>("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  // Run history: every saved analysis for the workspace (each run appends a
  // row, newest first), plus which one is currently displayed. Lets the user
  // compare the latest run against previous ones instead of only ever seeing
  // analyses[0].
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [selectedAnalysisId, setSelectedAnalysisId] = useState<string>("");
  // Read through refs, not the render's closure. The run poller holds the
  // loadAnalysisFor of the render that started it, so its view of the chosen
  // run went stale and every tick snapped a user's choice back; and a slow
  // response for the previously chosen country could land after the new one
  // and paint the wrong country's analysis under the new name.
  const selectedRunRef = useRef("");
  selectedRunRef.current = selectedAnalysisId;
  const loadSeq = useRef(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Live status of the currently-selected workspace's pipeline (independent
  // of whether it has any completed analysis yet) — lets a running analysis
  // be shown as a banner ABOVE previously-completed results, instead of
  // either hiding those results or silently doing nothing when a re-run is
  // in progress.
  const [wsStatus, setWsStatus] = useState<string | null>(null);
  const [wsStatusDetail, setWsStatusDetail] = useState<string | null>(null);
  const { openPanel, setWorkspaceId, setFindingContext, setMode, setAnalysisId } =
    useChat();

  // Load the analysis for a specific workspace id — shared by the
  // workspace dropdown (loadAnalysis) and the ?workspace=<id> deep link
  // from the Workspace page's "View Analysis" button.
  async function loadAnalysisFor(wsId: string) {
    if (!wsId) return;
    const seq = ++loadSeq.current;
    setLoading(true);
    setError(null);
    try {
      const data = await api.getAnalysis(wsId);
      if (seq !== loadSeq.current) return; // a newer request has the floor
      setWsStatus(data.status);
      setWsStatusDetail(data.status_detail);
      if (data.analyses.length > 0) {
        setAnalyses(data.analyses);
        // Keep the currently-selected run if it still exists; otherwise open
        // on the newest COMPLETE run. The newest run outright could be one
        // that lost dimensions to the provider, and it hid a finished result.
        const selected =
          data.analyses.find((a) => a.analysis_id === selectedRunRef.current) ||
          data.analyses.find((a) => a.analysis_id === data.preferred_analysis_id) ||
          data.analyses[0];
        setSelectedAnalysisId(selected.analysis_id);
        setAnalysis(selected);
      } else if (data.status === "processing" || data.status === "queued") {
        // No completed run exists yet for this workspace — keep the running
        // banner (rendered from wsStatus below) as the only messaging here;
        // no separate error text needed.
        setAnalyses([]);
        setSelectedAnalysisId("");
        setAnalysis(null);
      } else {
        setAnalyses([]);
        setSelectedAnalysisId("");
        setAnalysis(null);
        setError("No analysis results yet.");
      }
    } catch (e) {
      if (seq === loadSeq.current) {
        setError(e instanceof Error ? e.message : "Couldn't load the analysis.");
      }
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }

  // While the selected workspace's pipeline is actively running, keep
  // re-fetching so a running re-run flips over to its finished result (and
  // the banner clears) without the user having to click View Analysis again.
  // Same shape as the Workspace page poller: the "is a run in flight?" test
  // is a boolean dependency and the interval id is NOT held in state. Storing
  // it and guarding on it lets a stale id block the replacement interval after
  // a cleanup, which is how the Workspace page stopped polling after one tick
  // and left finished analyses looking like they were still running.
  //
  // "queued" is excluded: it means documents are attached and waiting for the
  // user to press Run Analysis, so polling it would never terminate.
  const isRunActive =
    wsStatus === "processing" || wsStatus === "generating_report";

  //
  // Only the workspace's status is polled. Re-fetching every run's full
  // results each tick cost about 1.5 MB per poll for Kenya; the results are
  // fetched once, when the run ends.
  const selectedWsRef = useRef("");
  selectedWsRef.current = selectedWs;

  useEffect(() => {
    if (!isRunActive || !selectedWs) return;
    const ws = selectedWs;
    const id = setInterval(async () => {
      try {
        const w = await api.getWorkspace(ws);
        if (selectedWsRef.current !== ws) return;
        setWsStatusDetail(w.status_detail);
        if (w.status !== "processing" && w.status !== "generating_report") {
          loadAnalysisFor(ws);
        }
      } catch {
        // A missed tick is retried on the next one.
      }
    }, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRunActive, selectedWs]);

  const [rerunError, setRerunError] = useState<string | null>(null);
  const [rerunStarting, setRerunStarting] = useState(false);

  async function rerun() {
    if (!selectedWs) return;
    setRerunStarting(true);
    setRerunError(null);
    try {
      await api.runAnalysis(selectedWs);
      setWsStatus("processing");
      setWsStatusDetail("Starting analysis.");
    } catch (e) {
      setRerunError(e instanceof Error ? e.message : "Could not start the analysis");
    } finally {
      setRerunStarting(false);
    }
  }

  // Keep the Rapporteur pointed at the run on screen. Done here rather than
  // in the selector's click handler so the deep-link and reload paths — which
  // pick a run without any click — stay in sync too.
  useEffect(() => {
    setAnalysisId(selectedAnalysisId || null);
  }, [selectedAnalysisId, setAnalysisId]);

  useEffect(() => {
    // Framework Library names power the clickable International Standard
    // Reference links in Module 2. Loaded once; failures leave links as text.
    // Dedupe by name so duplicate library entries don't multiply links or
    // collide in the deep-link target.
    api
      .listFrameworks()
      .then((data) => {
        const seen = new Set<string>();
        setFrameworks(
          data.filter((fw) => {
            if (seen.has(fw.name)) return false;
            seen.add(fw.name);
            return true;
          })
        );
      })
      // Only the framework links in the evidence panels use this list;
      // without it they render as plain text.
      .catch(() => {});
  }, []);

  useEffect(() => {
    api
      .listWorkspaces()
      .then((data) => {
        // Chat-only workspaces are AI Auditor document chats — they can
        // never have a dimension analysis, so they don't belong in the
        // workspace picker here (same rule as the Workspace page).
        const usable = data.filter((w) => w.status !== "chat_only").sort(byCountryOrder);
        setWorkspaces(usable);
        // ?workspace=<id> (from "View Analysis" on the Workspace page)
        // preselects that workspace and auto-loads its analysis. Read the
        // param via window.location instead of useSearchParams — this is a
        // statically-prerendered client page, and useSearchParams there
        // requires a Suspense boundary (breaks `next build`).
        const q = new URLSearchParams(window.location.search);
        const preset = q.get("workspace");
        if (preset && data.some((w) => w.id === preset)) {
          setSelectedWs(preset);
          loadAnalysisFor(preset);
        } else if (usable.length > 0) {
          // Select the first workspace for real. The picker always rendered
          // one, so leaving the state empty made "View Analysis" a no-op
          // until the user re-picked the country already shown to them.
          setSelectedWs(usable[0].id);
        }
      })
      .catch((e) =>
        setError(
          `Couldn't load the workspace list. ${e instanceof Error ? e.message : ""}`.trim()
        )
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function loadAnalysis() {
    loadAnalysisFor(selectedWs);
  }

  return (
    <FrameworkLibraryContext.Provider value={frameworks}>
    <div className="space-y-8">
      <PageHeader
        title="Governance Analysis"
        subtitle="Evidence-based gap analysis of the policy across eight governance dimensions."
        aside={
          analysis && (
            <Button
              className="px-4 py-2"
              onClick={() => {
                // Advisor mode, scoped to the loaded workspace: the chat
                // answers about this analysis and the evidence behind it.
                setWorkspaceId(selectedWs);
                setFindingContext(null, null);
                setMode("advisor");
                openPanel();
              }}
            >
              Ask AI
            </Button>
          )
        }
      />

      {/* Controls card — identical chrome to the Executive Brief page's
          Select Workspace card (same white surface, border, shadow,
          padding, and inner flex layout) so the two pages feel like one
          component. Only the action button differs. */}
      <div className="bg-white rounded-xl border border-black/[0.10] shadow-sm p-5">
        <div className="flex flex-wrap gap-4 items-end">
          <div className="flex-1 min-w-[260px]">
            <label className="block text-base font-semibold text-grey-950 mb-1.5">
              Select Workspace
            </label>
            <AnimatedSelect
              value={selectedWs}
              onChange={setSelectedWs}
              placeholder="Choose a workspace with a completed analysis..."
              options={workspaces.map((ws) => ({
                value: ws.id,
                label: `${ws.country} · ${ws.policy_title}`,
              }))}
            />
          </div>
          {/* Always black and always clickable-looking — loadAnalysis()
              itself no-ops when no workspace is selected. */}
          <ShineButton disabled={loading} onClick={loadAnalysis}>
            {loading ? "Loading..." : "View Analysis"}
          </ShineButton>
        </div>
      </div>

      {analyses.length > 1 && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-sm font-semibold text-grey-950">Documents evaluated:</span>
          {[...analyses].sort((a, b) => byStage(b, a)).map((a) => {
            // Labelled by what was evaluated: the full document set first
            // (the country's assessment, and the run the page opens on), then
            // each smaller set. A workspace keeps one run per document set,
            // so the labels are distinct without a date.
            const docs = analysisDocuments(a);
            const base = docs.length > 0 ? docs.join(" + ") : "Untitled run";
            // Kept selectable, never hidden — but a reader comparing runs has
            // to know which of them is missing dimensions.
            const failedCount = a.failed_dimensions?.length ?? 0;
            const label = failedCount
              ? `${base} · ${failedCount} of ${a.governance_gaps.length} not assessed`
              : a.provisional
              ? `${base} · provisional`
              : base;
            return (
              <button
                key={a.analysis_id}
                onClick={() => {
                  setSelectedAnalysisId(a.analysis_id);
                  setAnalysis(a);
                }}
                className={`pressable px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                  a.analysis_id === selectedAnalysisId
                    ? "bg-grey-950 text-white border-grey-950"
                    : "bg-white text-grey-950 border-grey-300 hover:border-grey-950 hover:text-grey-950"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      )}

      {(() => {
        // A run that lost dimensions, or whose depth is provisional, says
        // "re-run" — so the button to do it belongs next to the words.
        const ws = workspaces.find((w) => w.id === selectedWs);
        if (!analysis || !ws || ws.locked || isRunActive) return null;
        const failedCount = analysis.failed_dimensions?.length ?? 0;
        const queued = wsStatus === "queued";
        if (!failedCount && !analysis.provisional && !queued) return null;
        const message = queued
          ? "New documents are attached to this workspace and have not been analysed yet."
          : failedCount
          ? `${failedCount} of ${analysis.governance_gaps.length} dimensions were not assessed on this run. Re-running redoes only those.`
          : "Mechanism evidence could not be checked on this run, so implementation depth is provisional.";
        return (
          <div className="bg-status-amber-tint border border-status-amber-line text-status-amber-ink px-4 py-3 rounded-lg text-sm flex flex-wrap items-center gap-3">
            <span className="flex-1 min-w-[240px]">{rerunError || message}</span>
            <button
              onClick={rerun}
              disabled={rerunStarting}
              className="pressable text-sm px-4 py-1.5 rounded-lg bg-grey-950 text-white hover:bg-grey-800 disabled:bg-grey-50 disabled:text-grey-400"
            >
              {rerunStarting ? "Starting..." : queued ? "Run analysis" : "Re-run"}
            </button>
          </div>
        );
      })()}

      {isRunActive && (
        <div className="bg-grey-100 border border-grey-200 text-grey-800 px-4 py-3 rounded-lg text-sm flex items-center gap-2.5">
          <span className="w-2 h-2 rounded-full bg-grey-500 status-dot shrink-0" />
          <span>
            <span className="font-semibold">Analysis is currently running for this workspace.</span>{" "}
            {wsStatusDetail || "This can take a few minutes."}
            {analysis
              ? " Showing the most recently completed results below. They update automatically once the new run finishes."
              : " Results will appear here automatically once it finishes."}
          </span>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="bg-status-amber-tint border border-status-amber-line text-status-amber-ink px-4 py-3 rounded-lg text-sm"
        >
          {error}
        </div>
      )}

      {analysis && (
        <div className="space-y-6">
          <ProviderBadge generated_by={analysis.generated_by} />

          {/* What every verdict below is a statement about. Stored with each
              run and printed in the exported brief, but never shown here —
              so "Missing" read as a claim about the country rather than
              about the documents supplied, and the EU's Privacy verdict,
              read from the AI Act without the GDPR, carried no caveat. */}
          {analysis.scope_disclaimer && (
            <p className="text-[13px] leading-relaxed text-grey-800 border-l-2 border-grey-300 pl-3">
              {analysis.scope_disclaimer}
            </p>
          )}

          {analysis.decision_analytics && (
            <DecisionAnalyticsCard
              analytics={analysis.decision_analytics}
              gaps={analysis.governance_gaps}
              analyses={analyses}
              currentAnalysisId={analysis.analysis_id}
            />
          )}

          <div className="space-y-4">
            <h2 className="text-xl font-bold tracking-tight text-grey-950">
              Governance Dimensions
            </h2>
            {analysis.governance_gaps.map((gap, i) => (
              <DimensionBlock key={gap.dimension} gap={gap} index={i} />
            ))}
          </div>
        </div>
      )}
    </div>
    </FrameworkLibraryContext.Provider>
  );
}
