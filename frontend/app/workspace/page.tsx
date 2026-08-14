"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Workspace } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import TiltCard from "@/components/TiltCard";
import SpecularButton from "@/components/SpecularButton";
import EditorialReveal from "@/components/EditorialReveal";
import SmoothInput from "@/components/SmoothInput";

/* Progressive edge blur for the Recent Workspaces history list — adapted
   from the Skiper 41 (ProgressiveBlur) technique: a gradient background
   matching the page surface fades the rows into the page colour, while a
   mask reveals only the outer band of the backdrop blur, so the softening
   builds progressively instead of being a hard-edged strip. Pure overlay —
   it never touches the cards themselves. */
function ProgressiveBlur({
  position,
  // Resolves to the page surface (#F5F5F5) — var() works inside inline
  // style strings, so the gradient stays in sync with the design token.
  backgroundColor = "var(--surface)",
  height = "48px",
  blurAmount = "4px",
}: {
  position: "top" | "bottom";
  backgroundColor?: string;
  height?: string;
  blurAmount?: string;
}) {
  const isTop = position === "top";
  const maskGradient = isTop
    ? `linear-gradient(to bottom, ${backgroundColor} 50%, transparent)`
    : `linear-gradient(to top, ${backgroundColor} 50%, transparent)`;
  // React's vendor-prefix normalizer drops WebkitBackdropFilter/
  // WebkitMaskImage camelCase keys, so the Safari prefixes are written
  // verbatim as hyphenated string keys (typed via Record spread).
  const webkit: Record<string, string> = {
    "-webkit-mask-image": maskGradient,
    "-webkit-backdrop-filter": `blur(${blurAmount})`,
  };
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-x-0 z-10 select-none"
      style={{
        [isTop ? "top" : "bottom"]: 0,
        height,
        background: isTop
          ? `linear-gradient(to top, transparent, ${backgroundColor})`
          : `linear-gradient(to bottom, transparent, ${backgroundColor})`,
        maskImage: maskGradient,
        backdropFilter: `blur(${blurAmount})`,
        ...webkit,
      }}
    />
  );
}

export default function WorkspacePage() {
  const router = useRouter();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [country, setCountry] = useState("");
  const [policyTitle, setPolicyTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const [uploadingId, setUploadingId] = useState<string | null>(null);
  const [pollInterval, setPollInterval] = useState<ReturnType<typeof setInterval> | null>(null);
  // Freshly-created workspaces awaiting their first document: held locally
  // so the Upload PDF picker can open immediately (a queued workspace is
  // filtered out of the history list — it only reappears once processing).
  // Rendered as visible "awaiting document" rows so that if the browser
  // blocks the programmatic picker click (user activation is consumed by
  // the create await), the user still has an explicit Upload PDF button.
  // A list (not a single slot) so creating a second workspace can never
  // strand an earlier one that is still awaiting its document.
  const [pendingUploads, setPendingUploads] = useState<Workspace[]>([]);
  const pendingInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadWorkspaces();
  }, []);

  useEffect(() => {
    const hasProcessing = workspaces.some(
      (w) => w.status === "processing" || w.status === "queued"
    );
    if (hasProcessing && !pollInterval) {
      const id = setInterval(loadWorkspaces, 3000);
      setPollInterval(id);
    } else if (!hasProcessing && pollInterval) {
      clearInterval(pollInterval);
      setPollInterval(null);
    }
    return () => {
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [workspaces, pollInterval]);

  async function loadWorkspaces() {
    try {
      const data = await api.listWorkspaces();
      // AI Auditor uploads are chat-only workspaces (document ingested for
      // chat, never analysed) — they live on the AI Auditor page, not here.
      // Queued workspaces (created, no document yet) are also hidden from
      // history — they only appear once processing begins.
      setWorkspaces(
        data.filter(
          (w) => w.status !== "chat_only" && w.status !== "queued"
        )
      );
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
      // Queued workspaces are hidden from history, so open the file picker
      // for the brand-new workspace immediately — it appears in the list as
      // soon as the upload starts processing. The pending rows (below) are
      // the fallback if the browser blocks this programmatic click.
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

      {/* Freshly-created workspaces awaiting their first document. Not part
          of the history list (queued is filtered out) — dedicated rows with
          explicit Upload PDF buttons so a blocked auto-picker can never
          leave a workspace stranded and invisible. Each row clears the
          moment its upload starts. */}
      {pendingUploads.length > 0 && (
        <div className="space-y-3">
          {pendingUploads.map((pw) => (
            <div
              key={pw.id}
              className="bg-white rounded-lg border border-dashed border-undp-blue/40 p-4 flex items-center justify-between gap-3"
            >
              <div className="space-y-0.5 min-w-0">
                <p className="font-medium text-gray-900">
                  {pw.country} — {pw.policy_title}
                </p>
                <p className="text-xs text-gray-500">
                  Workspace created. Upload a policy document to start the
                  analysis.
                </p>
              </div>
              <label className="shrink-0 text-sm px-4 py-2 rounded-lg cursor-pointer transition-colors bg-undp-blue text-white hover:bg-undp-blue-light">
                Upload PDF
                <input
                  type="file"
                  accept=".pdf,application/pdf"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (file) {
                      setPendingUploads((prev) =>
                        prev.filter((w) => w.id !== pw.id)
                      );
                      handleUpload(pw.id, file);
                    }
                  }}
                />
              </label>
            </div>
          ))}
        </div>
      )}

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
          <div className="relative">
            {/* Progressive edge blur (Skiper 41 technique): a taller,
                gradient + masked overlay so rows passing the top and bottom
                edges fade into the page colour and soften progressively,
                rather than hitting a hard-edged blur strip. */}
            <ProgressiveBlur position="top" />
            <ProgressiveBlur position="bottom" />
            {/* Internal scroll with NO visible scrollbar (the .no-scrollbar
                utility hides it) — the edge blur overlays are the only cue
                that more rows wait above/below. */}
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
                        ws.status === "queued" ||
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
                </div>
                <div className="shrink-0 flex gap-2 flex-wrap">
                  {/* Completed analysis → View Analysis takes you straight
                      to the analysis page with this workspace preselected.
                      Upload is only offered while a document is still
                      needed (queued / error). */}
                  {ws.status === "complete" ? (
                    <button
                      onClick={() => router.push(`/analysis?workspace=${ws.id}`)}
                      className="pressable text-sm px-4 py-2 rounded-lg transition-colors bg-undp-blue text-white hover:bg-undp-blue-light"
                    >
                      View Analysis
                    </button>
                  ) : (
                    <label
                      className={`text-sm px-4 py-2 rounded-lg cursor-pointer transition-colors ${
                        ws.status === "queued" || ws.status === "error"
                          ? "bg-undp-blue text-white hover:bg-undp-blue-light"
                          : "bg-gray-100 text-gray-400 cursor-not-allowed"
                      }`}
                    >
                      {uploadingId === ws.id ? "Uploading..." : "Upload PDF"}
                      <input
                        type="file"
                        accept=".pdf,application/pdf"
                        className="hidden"
                        disabled={
                          ws.status !== "queued" && ws.status !== "error"
                        }
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) handleUpload(ws.id, file);
                        }}
                      />
                    </label>
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
