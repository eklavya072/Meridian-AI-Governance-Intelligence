const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

/** The message a failed response carries. FastAPI puts it in `detail`, as a
 *  plain string or as {error, message}; an object passed straight to
 *  `new Error` read "[object Object]". */
async function errorMessage(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => ({ detail: res.statusText }));
  const detail = body?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail.message === "string") return detail.message;
  return `${fallback}: ${res.status}`;
}

/** Thrown when the API can't be reached at all: fetch rejects with a bare
 *  TypeError ("Failed to fetch", "Load failed") that means nothing to a reader. */
export const API_UNREACHABLE =
  "Couldn't reach the Meridian API. Check that the backend is running, then try again.";

async function send(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new Error(API_UNREACHABLE);
  }
}

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await send(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(await errorMessage(res, "Request failed"));
  }
  return res.json();
}

export interface Workspace {
  id: string;
  country: string;
  policy_title: string;
  frameworks: string[];
  status: string;
  status_detail: string | null;
  /** The workspace's documents. Non-empty means "Run Analysis" is available. */
  pending_documents: string[];
  /** A read-only example on the public demo: no upload, no re-run. */
  locked?: boolean;
  created_at: string;
  updated_at: string;
}

export interface Framework {
  name: string;
  version: string;
  website: string;
  official_source_url: string;
  indexed: boolean;
  chunk_count: number;
  status: string;
}

export interface FrameworkPosition {
  framework: string;
  position: string;
  supporting_text: string;
  chunk_id: string;
  verified: boolean;
  failure: string;
}

export interface GovernanceGap {
  dimension: string;
  coverage: "Covered" | "Partial" | "Missing" | "Insufficient Evidence";
  gap_found: boolean;
  evidence: RetrievedEvidence[];
  reason_flagged: string;
  recommendation: string;
  risk_level: string;
  risk_reason: string;
  potential_consequence: string;
  un_recommendation: string;
  framework_synthesis: string;
  framework_positions: FrameworkPosition[];
  confidence_score: number;
  confidence_method: string;
  // ── Module 1 + Module 2 (expanded analysis) ──
  coverage_reasoning?: string;
  /** Real provisions cited from memory: in the document, not in the retrieved evidence. */
  unverifiable_citations?: string[];
  /** Citation numbers that appear nowhere in the uploaded document. */
  fabricated_citations?: string[];
  implementation_depth?: string;
  depth_reasoning?: string;
  /**
   * Which of the dimension's expected governance mechanisms the document
   * provides, and at what normative force (0 Aspirational -> 4 Enforceable).
   * The aggregate "38 of 45" is meaningless on its own — a reader has no way
   * to know what the 45 are — so the checklist names every one.
   */
  mechanisms_present?: Record<string, number>;
  /** Expected mechanisms the document does not address at all. */
  mechanisms_absent?: string[];
  /**
   * The absent mechanisms ordered by how many reference instruments name
   * each. Ordering only — nothing here changes a verdict. "You provide 4 of
   * 6" does not tell a ministry which of the missing two to fix first, and
   * that is the question they have.
   */
  priority_gaps?: { mechanism: string; expected_by: number }[];
  /** How many instruments the expected_by counts were taken over. */
  framework_corpus_size?: number;
  /**
   * How much evidence stands behind THIS cell: strong | moderate |
   * insufficient | none. A verdict resting on 171 binding provisions and one
   * resting on 1 otherwise render identically, so a reader cannot tell which
   * to verify before quoting it.
   */
  evidence_confidence?: string;
  /** Why that band, in the counters the verdict itself was computed on. */
  evidence_confidence_reason?: string;
  /** "applied" | "unavailable" | "" — whether mechanisms were adjudicated. */
  mechanism_adjudication?: string;
  module_1?: Module1Evaluation | null;
  module_2?: Module2Recommendation | null;
  // ── Module 3 + Module 4 (conditional, Part 2) ──
  /** Present ONLY for Partial/Missing dimensions (null for Fully Covered — no Module 3+4 call fired). */
  module_3?: Module3Implementation | null;
  /** Present ONLY when a genuinely relevant incident match exists. */
  module_4?: Module4CaseIntelligence | null;
  /** Set ONLY when the dimension could not be analysed (LLM quota/provider error) — NOT a finding. */
  analysis_error?: string | null;
}

export interface ModuleCitation {
  quote: string;
  chunk_id: string;
  source: string;
  source_type: "document" | "framework";
  /** Which uploaded document the citation's chunk came from (multi-doc). */
  document_name?: string;
  page_number: number | null;
  claim?: string;
  verified: boolean;
  /** True when the model declined to fabricate a citation (no supporting passage). */
  no_citation?: boolean;
  verification?: Record<string, unknown> | null;
}

export interface Module1Evaluation {
  dimension: string;
  coverage: "Covered" | "Partial" | "Missing";
  gap_detected: boolean;
  reason_flagged: string;
  coverage_reasoning: string;
  /** Fully Covered tier only: document-grounded examples leading to the Covered verdict. */
  coverage_example?: string;
  implementation_depth: string;
  depth_reasoning: string;
  document_evidence: ModuleCitation[];
  framework_evidence: ModuleCitation[];
}

export interface InternationalExample {
  practice: string;
  country_or_source: string;
  reference: string;
  /** How the practice relates to what the assessed document already does. */
  alignment?: string;
  citation: ModuleCitation | null;
}

export interface BestPractices {
  opening: string;
  /** Renamed from 'optional_enhancements' — "optional" reads as "ignore" to governments. */
  future_strengthening_opportunities: string[];
  international_examples: InternationalExample[];
}

export interface Module2Recommendation {
  dimension: string;
  recommendations: string[];
  /** null when coverage is Fully Covered (nothing to prioritise) or Insufficient Evidence. */
  priority: string | null;
  international_standard_reference: string;
  framework_synthesis: string;
  /** Structured synthesis — Consensus / Differences / Overall assessment. */
  framework_synthesis_consensus?: string;
  framework_synthesis_differences?: string;
  framework_synthesis_overall_assessment?: string;
  standard_citations: ModuleCitation[];
  /** Set ONLY for Fully Covered dimensions; null/absent otherwise. */
  best_practices?: BestPractices | null;
}

export interface Module3Phase {
  phase: string;
  timeline: string;
  /** Deterministic estimate rationale (code-computed, never LLM guesswork). */
  timeline_reasoning?: string;
  objective: string;
  steps: string[];
}

/** Module 3 — Implementation Roadmap. Present ONLY for Partial/Missing dimensions. */
export interface Module3Implementation {
  dimension: string;
  coverage_tier: string;
  phases: Module3Phase[];
  responsible_agency: string;
  /** "document_named" | "document_implied" | "none_identified" (code-verified, never fabricated). */
  responsible_agency_grounding: string;
  documentation_requirements: string[];
  monitoring_checklist: string[];
  citations: ModuleCitation[];
}

export interface IncidentMatch {
  incident_name: string;
  source: string;
  /** The incident's concrete facts, drawn from the cited passage. */
  what_happened?: string;
  dimension_relevance: string;
  potential_consequence: string;
  lessons_learned: string;
  mitigation: string;
  citation: ModuleCitation | null;
}

/** Module 4 — Case Intelligence. Populated ONLY when a genuine match exists. */
export interface Module4CaseIntelligence {
  dimension: string;
  matched: boolean;
  incident_matches: IncidentMatch[];
  summary: string;
}

export interface RetrievedEvidence {
  chunk_id: string;
  text: string;
  page_number: number | null;
  source_framework: string;
  /** Which uploaded document the chunk came from (multi-doc workspaces). */
  document_name?: string;
  similarity_score: number | null;
  section_title: string | null;
  verification?: {
    chunk_exists: boolean;
    page_exists: boolean;
    text_supports_claim: boolean;
    passed: boolean;
    failure_reason: string | null;
  };
  verified?: boolean;
}

export interface DecisionAnalytics {
  covered: number;
  partial: number;
  missing: number;
  insufficient_evidence: number;
  analysis_failed: number;
  /** IMPLEMENTATION DEPTH, 0-100: how far the governance has been built out,
   *  from stated intent to enforced machinery. The mean of the per-dimension
   *  stage scores (Unaddressed 0 / Emerging 50 / Delegated 65 /
   *  Operationalized 78 / Institutionalized 100). Paired with coverage_index
   *  below; the interesting cases are the ones where the two diverge. */
  implementation_depth_index: number;
  /** COVERAGE, 0-100: share of framework-required mechanisms addressed at all,
   *  regardless of the force behind them. Deliberately not tier-weighted. */
  coverage_index: number;
  mechanisms_met: number;
  mechanisms_total: number;
  mechanisms_binding: number;
  /** Of the mechanisms present, the share carried by an actual duty (tier >= 3). */
  binding_share: number;
  /** Per-stage counts (Unaddressed/Emerging/Delegated/Operationalized/Institutionalized) for histograms. */
  depth_distribution: Record<string, number>;
  assessed_dimensions: number;
  average_confidence: number;
  highest_priority_dimensions: string[];
  strongest_dimension: string;
}

export interface GeneratedBy {
  provider: string;
  tier: string;
}

export interface Analysis {
  analysis_id: string;
  document_name: string;
  frameworks_used: string[];
  governance_gaps: GovernanceGap[];
  summary: string;
  total_retrieved: number;
  similarity_scores: number[];
  llm_latency: number;
  total_processing_time: number;
  generated_by?: GeneratedBy;
  created_at: string;
  /** Model calls this run: one per dimension analysed, one Module 3+4 per
   *  Partial/Missing dimension, one mechanism adjudication. */
  llm_call_count?: number;
  /** Per-coverage-tier module_2 output sizes (chars) for token-reduction reporting. */
  tier_stats?: Record<string, { count: number; module2_chars: number; module2_avg_chars: number }> | null;
  /** Executive decision analytics (deterministic aggregates) for dashboards & research. */
  decision_analytics?: DecisionAnalytics | null;
  /** Deterministic scope disclaimer: evaluates provided document(s), not the country's full apparatus. */
  scope_disclaimer?: string;
  /** The document(s) actually ingested and evaluated for this workspace. */
  evaluated_documents?: string[];
  /** Dimensions the provider failed on this run; empty on a complete run. */
  failed_dimensions?: string[];
  /** Complete, but mechanism evidence was not adjudicated, so depth is provisional. */
  provisional?: boolean;
}

// --- Executive Brief types ---

export interface BriefRecommendation {
  recommendation: string;
  rationale: string;
}

export interface BriefDimensionRow {
  dimension: string;
  coverage: string;
  depth: string;
  basis: string;
  absent_mechanisms: string[];
  /** Bodies, registers and articles the document names for the dimension. */
  in_place?: string[];
  /** One verified provision from the document, with "<document>, p. N". */
  key_provision?: { quote: string; source: string } | null;
}

export interface BriefRoadmapPhase {
  phase: string;
  timeline: string;
  objective: string;
  steps: string[];
}

export interface BriefRoadmapItem {
  dimension: string;
  coverage: string;
  responsible_agency: string;
  phases: BriefRoadmapPhase[];
  monitoring: string[];
}

export interface BriefEvidenceBase {
  citations_total: number;
  citations_verified: number;
  /** Quotes from the assessed document only, each with "<document>, p. N". */
  representative_quotes: { dimension: string; quote: string; source?: string }[];
}

export interface BriefSections {
  executive_summary: string;
  areas_of_strength: string[];
  areas_requiring_attention: string[];
  /** Deterministic per-dimension detail — coverage, depth, evidence basis. */
  dimension_assessment?: BriefDimensionRow[];
  priority_recommendations: BriefRecommendation[];
  /** Sequenced Module 3 actions for the gapped dimensions. */
  implementation_roadmap?: BriefRoadmapItem[];
  /** Verified-citation counts plus representative passages. */
  evidence_base?: BriefEvidenceBase;
  relevant_precedent: string | null;
  scope_and_methodology: string;
}

/** Full structured executive brief — generated once, cached server-side,
 * rendered from the same data by the frontend preview, DOCX and PDF. */
export interface BriefDocument {
  workspace_id: string;
  country: string;
  policy_title: string;
  document_name: string;
  documents: string[];
  generated_at: string;
  num_dimensions: number;
  frameworks_used: string[];
  scope_disclaimer: string;
  coverage_summary: Record<string, number>;
  sections: BriefSections;
  decision_analytics?: Record<string, unknown>;
}

// --- Chat types ---

export interface ChatCitation {
  source: string;
  quote: string;
  verified: boolean;
}

export interface ChatResponse {
  session_id: string;
  reply: string;
  citations: ChatCitation[];
  blocked: boolean;
  reason: string | null;
  retrieval_count: number;
  citation_pass_count: number;
  citation_fail_count: number;
  intent?: string;
  dimension?: string | null;
  provider?: string;
  /** "advisor" (analysis-aware) | "framework_qa" (knowledge-base only) */
  mode?: string;
  /** Real provisions cited from memory: in the document, not in the retrieved evidence. */
  unverifiable_citations?: string[];
  /** Citation numbers that appear nowhere in the uploaded document. */
  fabricated_citations?: string[];
}

/** "auditor" = the merged AI Auditor bot (document + framework questions). */
export type ChatMode = "advisor" | "framework_qa" | "document_overview" | "auditor";

export interface ChatSessionInfo {
  session_id: string;
  workspace_id: string;
  finding_id: string | null;
  mode?: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessageData {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: ChatCitation[];
  created_at: string;
}

export interface ChatSessionDetail {
  session: ChatSessionInfo;
  messages: ChatMessageData[];
}

export const api = {
  listFrameworks: () => request<Framework[]>("/frameworks"),

  listWorkspaces: () => request<Workspace[]>("/workspace"),
  /** One workspace's status: the cheap thing to poll while a run is live. */
  getWorkspace: (workspaceId: string) => request<Workspace>(`/workspace/${workspaceId}`),
  createWorkspace: (data: {
    country: string;
    policy_title: string;
    frameworks: string[];
  }) =>
    request<Workspace>("/workspace", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  uploadPolicy: async (workspaceId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const url = `${API_BASE}/upload/${workspaceId}`;
    const res = await send(url, { method: "POST", body: formData });
    if (!res.ok) {
      throw new Error(await errorMessage(res, "Upload failed"));
    }
    return res.json() as Promise<{
      status: string;
      file_name: string;
      pending_documents: string[];
      notice?: string;
    }>;
  },

  /** Start the pipeline over every document queued on the workspace. */
  runAnalysis: async (workspaceId: string) => {
    const res = await send(`${API_BASE}/analyze/${workspaceId}/run`, {
      method: "POST",
    });
    if (!res.ok) {
      throw new Error(await errorMessage(res, "Could not start analysis"));
    }
    return res.json() as Promise<{
      status: string;
      workspace_id: string;
      documents: string[];
    }>;
  },

  /** AI Auditor: ingest a PDF for chat only (no dimension analysis run). */
  auditorUpload: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const url = `${API_BASE}/auditor/upload`;
    const res = await send(url, { method: "POST", body: formData });
    if (!res.ok) {
      throw new Error(await errorMessage(res, "Upload failed"));
    }
    return res.json() as Promise<{
      workspace_id: string;
      file_name: string;
      policy_title: string;
      chunk_count: number;
    }>;
  },

  getAnalysis: (workspaceId: string) =>
    request<{
      workspace_id: string;
      status: string;
      status_detail: string | null;
      /** Newest complete run — what the page opens on. */
      preferred_analysis_id?: string | null;
      analyses: Analysis[];
    }>(`/analyze/${workspaceId}`),

  /** Generate the executive brief (ONE synthesis call) for a workspace. */
  generateBrief: (workspaceId: string) =>
    request<BriefDocument>(`/brief/${workspaceId}/generate`, {
      method: "POST",
    }),

  /** Fetch the cached brief without regenerating (404 when none exists). */
  getBrief: (workspaceId: string) =>
    request<BriefDocument>(`/brief/${workspaceId}`),

  /** Download the cached brief as PDF or DOCX (blob download, no LLM call). */
  downloadBrief: async (workspaceId: string, format: "pdf" | "docx") => {
    const res = await send(`${API_BASE}/brief/${workspaceId}/export?format=${format}`);
    if (!res.ok) {
      throw new Error(await errorMessage(res, "Export failed"));
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `meridian-brief-${workspaceId.slice(0, 8)}.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  // --- Chat API ---

  chat: {
    sendMessage: (
      workspaceId: string | null,  // null/"" = Mode A (general, unscoped)
      message: string,
      sessionId?: string | null,
      findingContext?: Record<string, unknown> | null,
      mode?: ChatMode,
      /** The run the question is about. Without it the backend answers from
       *  the newest run, which is the wrong one whenever a workspace holds
       *  more than one — i.e. every country scored guidelines-then-statutes. */
      analysisId?: string | null
    ) =>
      request<ChatResponse>("/chat", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          message,
          session_id: sessionId || null,
          finding_context: findingContext || null,
          mode: mode || "advisor",
          analysis_id: analysisId || null,
        }),
      }),

    listSessions: (workspaceId: string, mode?: ChatMode) =>
      request<ChatSessionInfo[]>(
        `/chat/sessions?workspace_id=${workspaceId}${
          mode ? `&mode=${mode}` : ""
        }`
      ),

    getSession: (sessionId: string) =>
      request<ChatSessionDetail>(`/chat/sessions/${sessionId}`),

    deleteSession: (sessionId: string) =>
      request<{ status: string }>(`/chat/sessions/${sessionId}`, {
        method: "DELETE",
      }),
  },
};
