"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Workspace } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import TiltCard from "@/components/TiltCard";
import SpecularButton from "@/components/SpecularButton";
import EditorialReveal from "@/components/EditorialReveal";
import SmoothInput from "@/components/SmoothInput";

export default function WorkspacePage() {
  const router = useRouter();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [country, setCountry] = useState("");
  const [policyTitle, setPolicyTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const [uploadingId, setUploadingId] = useState<string | null>(null);
  const [startingId, setStartingId] = useState<string | null>(null);
  // Client-side run-start timestamps, keyed by workspace id — lets the
  // "estimated time remaining" line show a real elapsed counter even though
  // the backend has no dedicated "pipeline started at" field. Falls back to
  // updated_at (below) for a workspace whose run began before this page
  // load, e.g. after a browser refresh mid-run. Set when Run Analysis is
  // pressed, not on upload: uploading no longer starts anything, so timing
  // from the upload would show a counter for a workspace sitting idle.
  const [runStartedAt, setRunStartedAt] = useState<Record<string, number>>({});
  // Ticks once a second, only while something is actually processing, so the
  // elapsed-time text stays live without a re-render storm the rest of the
  // time.
  const [nowTick, setNowTick] = useState(Date.now());
  // Freshly-created workspaces, newest last. Only used to know which
  // workspace the auto-opened file picker belongs to; the workspace itself
  // is already visible in the list below, which is where the explicit
  // Upload PDF button lives if the browser blocks that programmatic click
  // (the create await consumes the user activation). A list rather than a
  // single slot so creating a second workspace cannot retarget the picker
  // of one still waiting on its file.
  const [pendingUploads, setPendingUploads] = useState<Workspace[]>([]);
  const pendingInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadWorkspaces();
  }, []);

  // Is any run actually in flight? "queued" now means "documents attached,
  // waiting for the user to press Run Analysis" — an idle state, not a
  // running one, so it must not start a poller.
  //
  // Derived as a BOOLEAN and used as the effect dependency, which is the
  // whole point. Both timers below previously depended on the `workspaces`
  // ARRAY, and the poller additionally stored its interval id in state and
  // guarded on it. That combination cancels itself after exactly one tick:
  // the poll refreshes `workspaces`, the new array identity fires the
  // cleanup which clears the live interval, the effect re-runs, and the
  // guard `hasActiveRun && !pollInterval` sees the stale-but-truthy id in
  // state and declines to start a replacement. Polling stops, the status
  // never reaches "complete", and the 1s ticker counts up forever because
  // `workspaces` never changes again — so a finished analysis looked like it
  // was still running until the page was reloaded by hand.
  //
  // A boolean only changes when a run actually starts or stops, so neither
  // interval is torn down by routine data refreshes.
  const hasActiveRun = workspaces.some(
    (w) => w.status === "processing" || w.status === "generating_report"
  );

  useEffect(() => {
    if (!hasActiveRun) return;
    const id = setInterval(loadWorkspaces, 3000);
    return () => clearInterval(id);
  }, [hasActiveRun]);

  // Live elapsed-time ticker for the "estimated time" line — only runs while
  // something is actually processing.
  useEffect(() => {
    if (!hasActiveRun) return;
    const id = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(id);
  }, [hasActiveRun]);

  // Based on real pipeline runs this session: an 8-dimension analysis
  // typically lands in the 90s-3min range, with larger documents or provider
  // slowness pushing past that — so the estimate is a range, not a false
  // promise of an exact number.
  const ESTIMATED_LOW_S = 90;
  const ESTIMATED_HIGH_S = 240;

  // A workspace accepts documents (and can be started) whenever it is not
  // mid-run. "error" is included so a failed run can be retried without
  // creating a new workspace.
  function canAttach(ws: Workspace): boolean {
    return ws.status === "queued" || ws.status === "error";
  }

  function estimateLine(ws: Workspace): string {
    const started =
      runStartedAt[ws.id] ?? Date.parse(ws.updated_at || ws.created_at);
    if (!started || Number.isNaN(started)) return "Estimated time: ~2-4 minutes.";
    const elapsedS = Math.max(0, Math.floor((nowTick - started) / 1000));
    const mm = Math.floor(elapsedS / 60);
    const ss = elapsedS % 60;
    const elapsedLabel = `${mm}:${ss.toString().padStart(2, "0")}`;
    if (elapsedS < ESTIMATED_HIGH_S) {
      return `Estimated time: ~2-4 minutes total · elapsed ${elapsedLabel}`;
    }
    // Past the usual window — most likely provider quota/latency, not a
    // stuck pipeline (this app hits daily LLM quota limits regularly).
    return `Taking longer than usual (elapsed ${elapsedLabel}) — likely provider load, still running`;
  }

  async function loadWorkspaces() {
    try {
      const data = await api.listWorkspaces();
      // AI Auditor uploads are chat-only workspaces (document ingested for
      // chat, never analysed) — they live on the AI Auditor page, not here.
      // Queued workspaces DO belong here: that is where a workspace sits
      // while it collects documents, and hiding it would strand the Run
      // Analysis button the moment the page reloaded.
      setWorkspaces(data.filter((w) => w.status !== "chat_only"));
      setError(null);
    } catch (e) {
      setError("Failed to load workspaces");
    } finally {
      setLoading(false);
    }
  }

  async function createWorkspace() {
    if (!country.trim() || !policyTitle.trim()) return;
    setCreating(true);
    try {
      const ws = await api.createWorkspace({
        country: country.trim(),
        policy_title: policyTitle.trim(),
        // Framework selection is deterministic (backend routes frameworks per
        // governance dimension + region) — the UI no longer offers a picker.
        frameworks: [],
      });
      setCountry("");
      setPolicyTitle("");
      await loadWorkspaces();
      // Open the picker straight away — one less click in the common case.
      // The new workspace's own card is the fallback if the browser blocks
      // this programmatic click.
      setPendingUploads((prev) => [...prev, ws]);
      pendingInputRef.current?.click();
    } catch (e) {
      setError("Failed to create workspace");
    } finally {
      setCreating(false);
    }
  }

  async function handleUpload(workspaceId: string, file: File) {
    setUploadingId(workspaceId);
    setError(null);
    try {
      await api.uploadPolicy(workspaceId, file);
      await loadWorkspaces();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploadingId(null);
    }
  }

  async function handleRunAnalysis(workspaceId: string) {
    setStartingId(workspaceId);
    setError(null);
    setRunStartedAt((prev) => ({ ...prev, [workspaceId]: Date.now() }));
    try {
      await api.runAnalysis(workspaceId);
      await loadWorkspaces();
    } catch (e: unknown) {
      // Clear the timestamp again, otherwise a failed start leaves an
      // elapsed counter ticking against a workspace that never began.
      setRunStartedAt((prev) => {
        const next = { ...prev };
        delete next[workspaceId];
        return next;
      });
      setError(e instanceof Error ? e.message : "Could not start analysis");
    } finally {
      setStartingId(null);
    }
  }

  return (
    <div className="space-y-8">
      <div className="text-center">
        {/* Responsive size: 52px on narrow panes up to 64px on wide
            screens — larger than the old fixed 52px everywhere a real
            monitor can take it, without the heading wrapping to three
            ragged lines on smaller windows. */}
        <h1 className="text-[clamp(3.25rem,7vw,4rem)] leading-[1.05] font-extrabold text-undp-blue tracking-tight">
          <EditorialReveal text="Country Office Workspace" />
        </h1>
        <p className="text-gray-600 mt-3 max-w-2xl mx-auto">
          Create a workspace to analyze a national policy document against
          reference frameworks.
        </p>
      </div>

      {error && (
        <div className="bg-[#F6ECEB] border border-[#E4C9C6] text-[#A8483F] px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      <section className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-undp-blue mb-4">
          New Analysis
        </h2>
        <div className="grid md:grid-cols-2 gap-4 mb-4">
          <SmoothInput
            type="text"
            placeholder="Country (e.g., India)"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-undp-blue"
          />
          <SmoothInput
            type="text"
            placeholder="Policy Title (e.g., National AI Strategy)"
            value={policyTitle}
            onChange={(e) => setPolicyTitle(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-undp-blue"
          />
        </div>

        <div className="mb-4 text-sm text-gray-500">
          Reference frameworks are selected automatically based on each
          governance dimension and the document's region.
        </div>

        {/* Create button "comes alive": grey when the form is incomplete,
            navy the instant both fields are valid — the readiness affordance
            is kept via a conditional tint, and the specular edge shine
            tracks the cursor (SpecularButton, React Bits). */}
        {/* Always black and always clickable. createWorkspace() itself
            no-ops when either field is empty — the button never greys out
            or disables; it simply does nothing until there's real input. */}
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
          disabled={creating}
          onClick={createWorkspace}
        >
          {creating ? "Creating..." : "Create Workspace"}
        </SpecularButton>

        {/* Hidden picker for the freshly-created workspace (see createWorkspace). */}
        <input
          ref={pendingInputRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            // The auto-click is always for the most recent pending workspace.
            const wsId = pendingUploads[pendingUploads.length - 1]?.id;
            e.target.value = "";
            if (file && wsId) {
              setPendingUploads((prev) => prev.filter((w) => w.id !== wsId));
              handleUpload(wsId, file);
            }
          }}
        />
      </section>

      <section>
        <h2 className="text-lg font-semibold text-undp-blue mb-4">
          Recent Workspaces
        </h2>
        {loading ? (
          <p className="text-gray-500">Loading...</p>
        ) : workspaces.length === 0 ? (
          <p className="text-gray-500 text-sm">
            No workspaces yet. Create one above.
          </p>
        ) : (
          <div>
            {/* Internal scroll with NO visible scrollbar (the .no-scrollbar
                utility hides it). */}
            <div className="no-scrollbar max-h-[56vh] space-y-3 overflow-y-auto pb-2 pt-1 pr-1">
            {workspaces.map((ws) => (
              <TiltCard key={ws.id} className="rounded-lg">
              <div
                className="bg-white rounded-lg border border-gray-200 p-4 flex items-center justify-between shadow-sm hover:shadow-lg transition-shadow"
              >
                <div className="space-y-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <h3 className="font-medium text-gray-900">
                      {ws.country} — {ws.policy_title}
                    </h3>
                    <StatusBadge
                      status={ws.status}
                      showBar={
                        ws.status === "processing" ||
                        ws.status === "generating_report"
                      }
                    />
                  </div>
                  <p className="text-xs text-gray-500">
                    Frameworks: auto-selected per dimension &amp; region
                  </p>
                  {ws.status_detail && (
                    <p className="text-xs text-gray-400 italic">
                      {ws.status_detail}
                    </p>
                  )}
                  {(ws.pending_documents?.length ?? 0) > 0 && (
                    <p className="text-xs text-gray-500 truncate">
                      Attached: {ws.pending_documents.join(", ")}
                    </p>
                  )}
                  {/* The elapsed counter belongs to a run in flight. A queued
                      workspace is waiting on the user, so showing a timer
                      there would count up against nothing. */}
                  {(ws.status === "processing" ||
                    ws.status === "generating_report") && (
                    <p className="text-xs text-undp-blue font-medium">
                      {estimateLine(ws)}
                    </p>
                  )}
                </div>
                <div className="shrink-0 flex gap-2 flex-wrap">
                  {/* Completed analysis → View Analysis takes you straight
                      to the analysis page with this workspace preselected.
                      Otherwise the card offers Upload PDF, and Run Analysis
                      once at least one document is attached. Upload stays
                      available next to Run Analysis on purpose: adding a
                      second document (a strategy plus its implementation
                      plan) and starting are separate decisions, and the
                      user makes both in their own order. */}
                  {ws.status === "complete" ? (
                    <button
                      onClick={() => router.push(`/analysis?workspace=${ws.id}`)}
                      className="pressable text-sm px-4 py-2 rounded-lg transition-colors bg-undp-blue text-white hover:bg-undp-blue-light"
                    >
                      View Analysis
                    </button>
                  ) : (
                    <>
                      <label
                        className={`text-sm px-4 py-2 rounded-lg cursor-pointer transition-colors ${
                          canAttach(ws)
                            ? "border border-undp-blue text-undp-blue hover:bg-undp-blue/5"
                            : "bg-gray-100 text-gray-400 cursor-not-allowed"
                        }`}
                      >
                        {uploadingId === ws.id
                          ? "Uploading..."
                          : ws.pending_documents?.length
                            ? "Add another PDF"
                            : "Upload PDF"}
                        <input
                          type="file"
                          accept=".pdf,application/pdf"
                          className="hidden"
                          disabled={!canAttach(ws)}
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            e.target.value = "";
                            if (file) handleUpload(ws.id, file);
                          }}
                        />
                      </label>
                      {canAttach(ws) && (ws.pending_documents?.length ?? 0) > 0 && (
                        <button
                          onClick={() => handleRunAnalysis(ws.id)}
                          disabled={startingId === ws.id || uploadingId === ws.id}
                          className="pressable text-sm px-4 py-2 rounded-lg transition-colors bg-undp-blue text-white hover:bg-undp-blue-light disabled:bg-gray-100 disabled:text-gray-400"
                        >
                          {startingId === ws.id ? "Starting..." : "Run Analysis"}
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>
              </TiltCard>
            ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
