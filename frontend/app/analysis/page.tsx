"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import {
  api,
  Workspace,
  Analysis,
  GovernanceGap,
  ModuleCitation,
  Module2Recommendation,
  DecisionAnalytics,
  Framework,
} from "@/lib/api";
import CitationCard from "@/components/CitationCard";
import HighlightedText from "@/components/HighlightedText";
import ProviderBadge from "@/components/ProviderBadge";
import DepthBadge from "@/components/DepthBadge";
import AnimatedSelect from "@/components/AnimatedSelect";
import { byCountryOrder } from "@/lib/countryOrder";
import ModuleStack, { type ModuleStackItem } from "@/components/ModuleStack";
import SpecularButton from "@/components/SpecularButton";
import {
  CoverageDonut,
  DepthGauge,
  StageHistogram,
} from "@/components/DashboardCharts";
import { RunComparisonHeatmap, analysisDocuments, byStage } from "@/components/Heatmaps";
import ProvisionChecklist from "@/components/ProvisionChecklist";
import {
  RadarChart,
  RadarGrid,
  RadarAxis,
  RadarLabels,
  RadarArea,
  type RadarTooltip,
} from "@/components/RadarChart";
import { useChat } from "@/components/ChatProvider";
import CitationAccordion from "@/components/CitationAccordion";
import { resolveFrameworkLinks } from "@/lib/frameworkLinks";
import {
  EASE,
  DUR,
  staggerContainer,
  staggerChild,
  verifiedSnap,
} from "@/lib/motion";

import palette from "@/lib/palette.json";
// Framework Library entries, loaded once on the analysis page. Module 2's
// International Standard Reference uses them to render clickable links to the
// Framework Library page; an empty list simply leaves the reference as text.
const FrameworkLibraryContext = createContext<Framework[]>([]);

const COVERAGE_LABEL: Record<string, string> = {
  Covered: "Fully Covered",
  Partial: "Partially Covered",
  Missing: "Missing",
};

// Coverage tier accent colors — exact muted chart tokens. These carry the
// Covered/Partial/Missing semantic. Partial is a soft gold rather than amber:
// it softens the red-vs-green contrast at the tier that sits between them,
// for a calmer, more elegant read than the harsher stock traffic-light amber.
const TIER_DOT: Record<string, string> = {
  Covered: palette.status.green, // --chart-covered (muted forest green)
  Partial: palette.chart.partial, // --chart-partial (soft gold)
  Missing: palette.status.red, // --chart-missing (muted red)
  "Insufficient Evidence": palette.status.amber, // cannot tell — caution amber
};

// ── Dimension Radar — coverage tier → ring position ─────────────────────
// Each dimension's value is its coverage tier on a 0–100 scale, so every
// vertex lands exactly on one of the radar's three rings (33 Missing /
// 66 Partial / 100 Fully Covered). "Not assessed" dimensions (LLM failure
// or Insufficient Evidence) sit at the centre — the same grey lump the
// coverage donut treats as "Not Assessed" — and are footnoted below.
const RADAR_SCORE: Record<string, number> = {
  Covered: 100,
  Partial: 66,
  Missing: 33,
};

// Compact axis labels so long dimension names stay inside the viewBox.
const RADAR_DISPLAY: Record<string, string> = {
  "Environmental Sustainability": "Env. Sustainability",
};

const RADAR_TIER_LEGEND = [
  { label: "Missing", color: palette.status.red },
  { label: "Partially Covered", color: palette.chart.partial },
  { label: "Fully Covered", color: palette.status.green },
] as const;

// Hover tooltip on the radar — reverse-maps the 0-100 ring position back
// to the coverage tier it encodes (0 = not assessed, 33 = Missing, 66 =
// Partial, 100 = Fully Covered), in the same muted status colours as the
// legend and donut.
const radarTooltip = (value: number): RadarTooltip => {
  if (value >= 100) return { label: "Fully Covered", color: palette.status.green };
  if (value >= 66) return { label: "Partially Covered", color: palette.chart.partial };
  if (value >= 33) return { label: "Missing", color: palette.status.red };
  return { label: "Not assessed", color: palette.grey["500"] };
};

function RadarRingLegend({ label, color }: { label: string; color: string }) {
  return (
    <span className="flex items-center gap-1.5 text-sm font-medium text-grey-950">
      <span
        className="w-2.5 h-2.5 rounded-full border-2 shrink-0"
        style={{ borderColor: color }}
      />
      <span>{label}</span>
    </span>
  );
}

// WHAT THE WORD MEANS, AND WHY THIS CELL EARNED IT.
//
// "Covered" and "Operationalized" are terms of art in this instrument and
// they do not mean what a reader assumes. Covered is a statement about legal
// FORCE — it says the provisions clear a duty bar — while a reader hearing
// "fully covered" naturally hears "this topic is well handled", which is a
// claim about breadth the verdict never made. A ministry quoting the word
// without the definition quotes something we did not say.
//
// Two lines, not a paragraph: the rule that produced the verdict, then the
// counts from THIS dimension that satisfied it. The second line is what
// makes it an explanation rather than a glossary — the same sentence under
// every cell would be documentation, not evidence.
const COVERAGE_GLOSS: Record<string, string> = {
  Covered:
    "The provisions for this dimension clear the binding-force bar: two or more impose a duty, " +
    "or one duty is backed by enforcement. This is a finding about legal force, not about how " +
    "much the document says on the subject.",
  Partial:
    "Provisions for this dimension exist and were read, but they fall short of a governed " +
    "regime — commitments are stated without a duty, a single duty stands alone, or the duties " +
    "reach too few of the mechanisms this dimension calls for. The subject is addressed; it is " +
    "not yet fully obliged.",
  Missing:
    "Every provision of the supplied documents was read, and this dimension appears only in " +
    "passing: no duty, no named owner, no commitment to act. It describes the supplied text, " +
    "not the country's wider governance, which may sit in instruments not provided.",
  "Insufficient Evidence":
    "Nothing relevant to this dimension could be retrieved from the supplied documents or the " +
    "reference frameworks, so no verdict was formed. It is withheld rather than guessed.",
};

const DEPTH_GLOSS: Record<string, string> = {
  Unaddressed: "No provision for this dimension was scored, so there is no regime to describe.",
  Emerging:
    "Intent is on the record — the document states what it wants for this dimension — but " +
    "nothing yet assigns the work or requires it of anyone.",
  Delegated:
    "Responsibility has landed somewhere: an owner is named or a duty is stated, but the " +
    "machinery that would make it operate is not yet in the text.",
  Operationalized:
    "Binding requirements exist and carry mechanisms this dimension expects, but without the " +
    "audit, enforcement or redress machinery that would make the regime self-sustaining.",
  Institutionalized:
    "Binding requirements are paired with the enforcement, oversight or redress machinery that " +
    "makes them answerable — the highest stage this instrument recognises.",
};

function CoverageIndicator({ coverage }: { coverage: string }) {
  return (
    <span className="dot-indicator">
      <span
        className="dot"
        style={{ background: TIER_DOT[coverage] || palette.black }}
      />
      <span>{COVERAGE_LABEL[coverage] || coverage}</span>
    </span>
  );
}

// ── Module citation row with verification badge ──────────────────────────

// ── Structured framework synthesis (Consensus / Differences / Overall) ───
// The backend now emits framework_synthesis as three labeled parts. Rendered
// as distinct blocks; falls back to the composed legacy string when the
// structured fields are absent (e.g. older saved analyses).

function FrameworkSynthesisBlock({
  m2,
  gap,
  heading = "Framework Synthesis",
}: {
  m2?: Module2Recommendation | null;
  gap: GovernanceGap;
  heading?: string;
}) {
  const consensus = m2?.framework_synthesis_consensus?.trim();
  const differences = m2?.framework_synthesis_differences?.trim();
  const overall = m2?.framework_synthesis_overall_assessment?.trim();

  return (
    <div>
      <p className="module-heading mb-2">{heading}</p>
      {consensus || differences || overall ? (
        <div className="space-y-3">
          {consensus && (
            <div>
              <p className="module-label font-bold mb-1">Consensus</p>
              <p className="module-body"><HighlightedText text={consensus} /></p>
            </div>
          )}
          {differences && (
            <div>
              <p className="module-label font-bold mb-1">Differences</p>
              <p className="module-body"><HighlightedText text={differences} /></p>
            </div>
          )}
          {overall && (
            <div>
              <p className="module-label font-bold mb-1">Overall Assessment</p>
              <p className="module-body"><HighlightedText text={overall} /></p>
            </div>
          )}
        </div>
      ) : (
        <p className="module-body">
          <HighlightedText text={m2?.framework_synthesis || gap.framework_synthesis || "—"} />
        </p>
      )}
    </div>
  );
}

// Anti-fabrication display rule: a citation that cannot be attributed to a
// real named source ("Unknown" / empty) is HIDDEN entirely, never shown to
// users — either it is verified against a real source or it does not appear.
function citationIsVisible(citation: ModuleCitation): boolean {
  if (citation.no_citation === true) return true; // honest decline, shown
  return Boolean(citation.source && citation.source !== "Unknown");
}

// Verified badge: "snaps into place" with a controlled spring — a deliberate
// micro-interaction. It reinforces the project's core trust mechanic (a
// citation is confirmed against a real chunk), so the settle is meaningful.
function VerifiedBadge() {
  return (
    <motion.span {...verifiedSnap} className="dot-indicator shrink-0 !text-xs">
      <motion.span
        className="dot !w-1.5 !h-1.5"
        style={{ background: palette.status.green }}
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ delay: 0.08, duration: 0.2 }}
        aria-hidden
      />
      <span className="text-grey-950">Verified</span>
    </motion.span>
  );
}

function CitationRow({ citation }: { citation: ModuleCitation }) {
  const verified = citation.verified;
  const noCitation = citation.no_citation === true;

  // Anti-fabrication display rule: a citation that cannot be attributed to a
  // real named source ("Unknown" / empty) is HIDDEN entirely, never shown to
  // users — either it is verified against a real source or it does not appear.
  if (!citationIsVisible(citation)) {
    return null;
  }

  // Explicit "model declined to fabricate" state — NOT a failed verification.
  if (noCitation) {
    return (
      <div className="border rounded-lg p-3 bg-grey-50/70">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-grey-900 italic">
            No supporting passage was found in the retrieved context — the
            model declined to fabricate a citation.
          </p>
          <span className="shrink-0 text-xs font-bold px-2 py-0.5 rounded bg-grey-950 text-white">
            No citation
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="border rounded-lg p-3 space-y-1.5 bg-grey-50/70">
      {/* The claim first, then the passage under it. A quote alone makes the
          reader reverse-engineer what it was offered to prove; naming the
          finding turns the card into an argument they can disagree with.
          line-clamp was 3 — a clause — which cut the operative passage off
          before the duty-bearer or the consequence. Provisions carry their
          force at the end, so the clamp is now generous enough to show one
          whole provision and only bites on a genuinely long extract. */}
      {citation.claim && (
        <p className="text-[13px] font-medium leading-snug text-grey-950">
          {citation.claim}
        </p>
      )}
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-grey-900 line-clamp-[8] flex-1 italic">
          “{citation.quote}”
        </p>
        {verified ? (
          <VerifiedBadge />
        ) : (
          <span className="dot-indicator shrink-0 !text-xs">
            <span className="dot !w-1.5 !h-1.5" style={{ background: palette.status.red }} />
            <span className="text-grey-950">Unverified</span>
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-3 text-xs font-medium text-grey-900">
        {citation.document_name ? (
          <span className="text-grey-950 underline underline-offset-2">
            Document: {citation.document_name}
          </span>
        ) : (
          citation.source && <span>Source: {citation.source}</span>
        )}
        {citation.page_number && <span>Page {citation.page_number}</span>}
      </div>
      {citation.verification && !verified && (
        <p className="text-xs font-medium text-grey-900 italic">
          {String(
            (citation.verification as Record<string, unknown>)?.failure_reason || ""
          )}
        </p>
      )}
    </div>
  );
}

// ── Section 1: Evaluation ────────────────────────────────────────────────

function Module1Panel({ gap }: { gap: GovernanceGap }) {
  const m1 = gap.module_1;
  const depth = m1?.implementation_depth || gap.implementation_depth;
  const isCovered = gap.coverage === "Covered";

  // Evidence accordion data. "Sources" = real chunk-backed citations only
  // (honest-decline entries are rendered inside the panel but are not
  // counted as sources); the verified rate is over the real sources only.
  const docCards = (m1?.document_evidence || []).filter(citationIsVisible);
  const fwCards = (m1?.framework_evidence || []).filter(citationIsVisible);
  const realDoc = docCards.filter((c) => Boolean(c.chunk_id));
  const realFw = fwCards.filter((c) => Boolean(c.chunk_id));
  const totalSources = realDoc.length + realFw.length;
  // The sentence above states the rule; this states what THIS dimension
  // brought to it. Mechanisms carry the tier they were found at, so a count
  // of those at Obligatory or above is the number actually carried by a duty
  // — the quantity the bar is about, and the one a reader would otherwise
  // have to reconstruct from the mechanism list further down the page.
  const mechanismTally = (() => {
    const present = gap.mechanisms_present || {};
    const names = Object.keys(present);
    if (!names.length) return "";
    const total = names.length + (gap.mechanisms_absent?.length || 0);
    const bound = names.filter((k) => Number(present[k]) >= 3).length;
    return `Here, ${names.length} of ${total} expected mechanisms appear and ${bound} ${
      bound === 1 ? "is" : "are"
    } carried by a duty.`;
  })();
  const verifiedCount = [...realDoc, ...realFw].filter((c) => c.verified).length;

  return (
    <div className="space-y-5">
      {/* Label/value grid — quiet uppercase labels, dark values. The value
          is the emphasis; the label is the whisper. */}
      <div className="grid md:grid-cols-2 gap-x-6 gap-y-5">
        <div>
          <p className="module-label mb-1.5">Coverage</p>
          <CoverageIndicator coverage={gap.coverage} />
          {COVERAGE_GLOSS[gap.coverage] && (
            <p className="text-[11px] leading-[1.5] text-grey-600 mt-1.5">
              {COVERAGE_GLOSS[gap.coverage]}
              {mechanismTally && ` ${mechanismTally}`}
            </p>
          )}
        </div>
        <div>
          <p className="module-label font-bold mb-1.5">Implementation Depth</p>
          <DepthBadge level={depth} />
          {depth && DEPTH_GLOSS[depth] && (
            <p className="text-[11px] leading-[1.5] text-grey-600 mt-1.5">
              {DEPTH_GLOSS[depth]}
            </p>
          )}
        </div>
        {/* How much this particular cell is worth. Per-dimension external
            validation reaches 38% of cells; for the rest the only honest
            answer is to say what the verdict rests on, so "verify before you
            quote this" points at something specific rather than at the whole
            instrument. */}
        {gap.evidence_confidence && (
          <div>
            <p className="module-label mb-1.5">Evidence Behind This Verdict</p>
            <p className="module-value capitalize">{gap.evidence_confidence}</p>
            {gap.evidence_confidence_reason && (
              <p className="text-[11px] text-grey-600 mt-1">
                {gap.evidence_confidence_reason}
              </p>
            )}
          </div>
        )}
        <div>
          <p className="module-label mb-1.5">Gap Detected</p>
          <p className="module-value">
            {m1 ? (m1.gap_detected ? "Yes" : "No") : gap.gap_found ? "Yes" : "No"}
          </p>
        </div>
        {!isCovered && (
          <div>
            <p className="module-label mb-1.5">Reason Flagged</p>
            <p className="module-body">
              <HighlightedText text={m1?.reason_flagged || gap.reason_flagged || ""} />
            </p>
          </div>
        )}
      </div>

      <ProvisionChecklist gap={gap} />

      {/* Fully Covered tier: coverage_example (what led to the Covered
          verdict) replaces reason_flagged. When the model produced no
          coverage_example, fall back to coverage_reasoning so the verdict
          is never left unexplained. */}
      {isCovered ? (
        m1?.coverage_example ? (
          <div>
            <p className="module-heading mb-2">Coverage Examples</p>
            <p className="module-body">
              <HighlightedText text={m1.coverage_example} />
            </p>
          </div>
        ) : (
          (m1?.coverage_reasoning || gap.coverage_reasoning) && (
            <div>
              <p className="module-heading mb-2">Coverage Reasoning</p>
              <p className="module-body">
                <HighlightedText text={m1?.coverage_reasoning || gap.coverage_reasoning || ""} />
              </p>
            </div>
          )
        )
      ) : (
        (m1?.coverage_reasoning || gap.coverage_reasoning) && (
          <div>
            <p className="module-heading mb-2">Coverage Reasoning</p>
            <p className="module-body">
              <HighlightedText text={m1?.coverage_reasoning || gap.coverage_reasoning || ""} />
            </p>
          </div>
        )
      )}

      {/* Citation caveats — FABRICATED ONLY.
          A caveat is worth a reader's attention when they cannot check the
          reference themselves. Two severities are computed: fabricated (the
          number appears nowhere in the uploaded document) and unsupported
          (real and present in the document, but not in the passages retrieved
          for this dimension).
          Only the first is shown. Surfacing the second told readers to doubt
          citations they could look up and confirm — on the EU AI Act run it
          flagged "Article 10" for Fairness, which is the data-governance and
          bias-examination provision and exactly the right reference, plus a
          recital that occurs verbatim in the text. That is a retrieval-coverage
          signal about us, not a defect in the analysis, and putting it in front
          of the reader made correct work look unreliable. It is still recorded
          on the gap and logged server-side. */}
      {(gap.fabricated_citations?.length ?? 0) > 0 && (
        <div className="rounded-lg border border-status-red-line bg-status-red-tint px-3 py-2">
          <p className="module-heading mb-1 text-status-red">Citation caveat</p>
          <p className="module-body text-status-red">
            Not found anywhere in the uploaded document —{" "}
            {gap.fabricated_citations!.join(", ")}. Treat as unreliable.
          </p>
        </div>
      )}

      {m1?.depth_reasoning && (
        <div>
          <p className="module-heading mb-2">Implementation depth Reasoning</p>
          <p className="module-body"><HighlightedText text={m1.depth_reasoning} /></p>
        </div>
      )}

      {/* Evidence — one toggle, closed by default (shared CitationAccordion,
          same pattern as Module 2's Grounding Citations). The one-line
          summary shows the source split and verification rate without
          expanding. */}
      {totalSources === 0 ? (
        <p className="module-meta italic pt-1">
          No specific document or framework evidence found.
        </p>
      ) : (
        <CitationAccordion
          label="Evidence"
          total={totalSources}
          summary={`${realDoc.length} document · ${realFw.length} framework · ${verifiedCount}/${totalSources} verified`}
        >
          {docCards.length > 0 && (
            <div className="space-y-2">
              <p className="eyebrow !mb-1.5">From uploaded document</p>
              {docCards.map((c, i) => (
                <CitationRow key={`${c.chunk_id}-doc-${i}`} citation={c} />
              ))}
            </div>
          )}
          {fwCards.length > 0 && (
            <div className="space-y-2">
              <p className="eyebrow !mb-1.5">From reference frameworks</p>
              {fwCards.map((c, i) => (
                <CitationRow key={`${c.chunk_id}-fw-${i}`} citation={c} />
              ))}
            </div>
          )}
        </CitationAccordion>
      )}
    </div>
  );
}

// ── Section 2: Recommendations & Alignment ───────────────────────────────

const PRIORITY_DOT: Record<string, string> = {
  Critical: palette.status.red, // muted red
  High: palette.status.red, // muted red
  Medium: palette.status.amber, // muted amber
  Low: palette.status.green, // muted forest green
};

// ── Fully Covered tier: Best Practices panel (replaces Recommendations) ─

function BestPracticesPanel({ gap }: { gap: GovernanceGap }) {
  const m2 = gap.module_2;
  const best = m2?.best_practices;
  if (!best) return null;

  // Grounding-citations accordion data (same semantics as Module 1 Evidence:
  // "sources" = real chunk-backed citations, verified rate over those).
  const stdCards = (m2?.standard_citations || []).filter(citationIsVisible);
  const realStd = stdCards.filter((c) => Boolean(c.chunk_id));
  const stdVerified = realStd.filter((c) => c.verified).length;

  return (
    <div className="space-y-5">
      <p className="module-body"><HighlightedText text={best.opening} /></p>

      {best.future_strengthening_opportunities.length > 0 && (
        <div>
          <p className="module-heading mb-2">
            Future Strengthening Opportunities
          </p>
          <ul className="module-list">
            {best.future_strengthening_opportunities.map((e, i) => (
              <li key={i}><HighlightedText text={e} /></li>
            ))}
          </ul>
        </div>
      )}

      {best.international_examples.length > 0 && (
        <div>
          <p className="module-heading mb-2">
            International Examples
          </p>
          <div className="space-y-3">
            {best.international_examples.map((ex, i) => (
              <div key={i} className="border rounded-lg p-3.5 bg-white/70 space-y-2">
                <p className="module-body"><HighlightedText text={ex.practice} /></p>
                {ex.alignment && (
                  <p className="module-body text-grey-800">
                    <span className="font-semibold">Relation to this policy: </span>
                    {ex.alignment}
                  </p>
                )}
                <div className="flex flex-wrap gap-3 module-meta">
                  {ex.country_or_source && <span>{ex.country_or_source}</span>}
                  {ex.reference && <span>Source: {ex.reference}</span>}
                </div>
                {ex.citation && <CitationRow citation={ex.citation} />}
              </div>
            ))}
          </div>
        </div>
      )}

      <FrameworkSynthesisBlock
        m2={m2}
        gap={gap}
        heading="Framework Synthesis — why this is compliant"
      />

      {realStd.length > 0 && (
        <CitationAccordion
          label="Sources"
          total={realStd.length}
          summary={`${realStd.length} practical ${
            realStd.length === 1 ? "source" : "sources"
          } · ${stdVerified}/${realStd.length} verified`}
        >
          {stdCards.map((c, i) => (
            <CitationRow key={`${c.chunk_id}-std-${i}`} citation={c} />
          ))}
        </CitationAccordion>
      )}
    </div>
  );
}

function Module2Panel({ gap }: { gap: GovernanceGap }) {
  const m2 = gap.module_2;
  const frameworks = useContext(FrameworkLibraryContext);

  // Fully Covered tier → Best Practices panel; nothing to prioritise.
  if (gap.coverage === "Covered" && m2?.best_practices) {
    return <BestPracticesPanel gap={gap} />;
  }

  const recommendations = m2?.recommendations?.length
    ? m2.recommendations
    : gap.recommendation
    ? gap.recommendation.split("\n").filter(Boolean)
    : [];
  const priority = m2?.priority || "";

  // Clickable International Standard Reference: named sources that match a
  // Framework Library entry link to it; unmatched text stays plain.
  const referenceSegments = resolveFrameworkLinks(
    m2?.international_standard_reference || gap.un_recommendation || "",
    frameworks
  );
  // Grounding-citations accordion data (same semantics as Module 1 Evidence).
  const stdCards = (m2?.standard_citations || []).filter(citationIsVisible);
  const realStd = stdCards.filter((c) => Boolean(c.chunk_id));
  const stdVerified = realStd.filter((c) => c.verified).length;

  return (
    <div className="space-y-5">
      <div>
        <p className="module-label mb-1.5">Priority</p>
        {priority ? (
          <span className="dot-indicator">
            <span
              className="dot"
              style={{ background: PRIORITY_DOT[priority] || palette.black }}
            />
            <span>{priority}</span>
          </span>
        ) : (
          <span className="module-meta italic">—</span>
        )}
      </div>

      <div>
        <p className="module-heading mb-2">Recommendations</p>
        {/* Each recommendation is constrained twice — it must extend a
            mechanism that already exists in this document, and it must name
            the instrument that expects it. Saying so converts the list from
            advice a reader has to trust into advice they can check. */}
        {recommendations.length > 0 && (
          <p className="text-[11px] leading-[1.5] text-grey-600 mb-2">
            Each action extends something already in this document rather than proposing a new
            regime, and names the international instrument that expects it — so both ends of the
            recommendation can be checked against a source.
          </p>
        )}
        {recommendations.length ? (
          <ul className="module-list">
            {recommendations.map((r, i) => (
              <li key={i}><HighlightedText text={r} /></li>
            ))}
          </ul>
        ) : (
          <p className="module-meta italic">No recommendations.</p>
        )}
      </div>

      <div>
        <p className="module-heading mb-2">
          International Standard Reference
        </p>
        <p className="module-body">
          {referenceSegments.length
            ? referenceSegments.map((seg, i) =>
                seg.framework ? (
                  <Link
                    key={i}
                    href={`/frameworks?framework=${encodeURIComponent(
                      seg.framework.name
                    )}`}
                    // A real highlight, not just a color swap: `text-grey-950`
                    // resolves to the same near-black as ordinary body text
                    // (the palette killed blue), so underline alone read as a
                    // stray line under plain prose rather than a link. The
                    // background carries the "clickable" signal color cannot.
                    className="font-semibold text-grey-950 underline decoration-grey-950/50 underline-offset-2 bg-grey-950/[0.06] hover:bg-grey-950/[0.11] rounded px-1 py-0.5 -mx-1 transition-colors"
                    title={`Open ${seg.framework.name} in the Framework Library`}
                  >
                    {seg.text}
                  </Link>
                ) : (
                  <span key={i}>{seg.text}</span>
                )
              )
            : "—"}
        </p>
      </div>

      <FrameworkSynthesisBlock m2={m2} gap={gap} />

      {realStd.length > 0 && (
        <CitationAccordion
          label="Sources"
          total={realStd.length}
          summary={`${realStd.length} practical ${
            realStd.length === 1 ? "source" : "sources"
          } · ${stdVerified}/${realStd.length} verified`}
        >
          {stdCards.map((c, i) => (
            <CitationRow key={`${c.chunk_id}-std-${i}`} citation={c} />
          ))}
        </CitationAccordion>
      )}
    </div>
  );
}

// ── Section 3: Implementation Roadmap (Partial/Missing only) ─────────────
// Rendered ONLY when the dimension is Partial or Missing — Fully Covered
// dimensions show no Module 3 section at all (not even a header), per the
// coverage-tier design: don't dwell on what's fine, focus on what needs work.

const AGENCY_GROUNDING_DOT: Record<string, string> = {
  document_named: palette.status.green, // named in document — muted green
  document_implied: palette.status.amber, // implied — muted amber
  none_identified: palette.status.red, // none — muted red
};

function Module3Panel({ gap }: { gap: GovernanceGap }) {
  const m3 = gap.module_3;
  if (!m3) return null;
  const grounding = m3.responsible_agency_grounding || "none_identified";

  // Grounding citations — collapsed "Show Sources" toggle, same pattern as
  // Module 2. Rows are visible citations; the count/verified rate are over
  // real chunk-backed citations only.
  const citations = (m3.citations || []).filter(citationIsVisible);
  const realCitations = citations.filter((c) => Boolean(c.chunk_id));
  const citationsVerified = realCitations.filter((c) => c.verified).length;

  return (
    <div className="space-y-5">
      {/* The timelines are the part a reader is most likely to distrust, and
          the part with the best answer: they are computed, not written. The
          note says where they come from so the "why 0-10 months" question is
          answered before it is asked. */}
      {m3.phases.length > 0 && (
        <p className="text-[11px] leading-[1.5] text-grey-600">
          Phase timelines are calculated from this dimension&apos;s own profile — its coverage
          tier, depth stage, how many mechanisms the document already operates, and whether it
          names a responsible agency. Each phase carries the reasoning that produced its range.
        </p>
      )}
      {m3.phases.length > 0 && (
        <div className="space-y-3">
          {m3.phases.map((ph, i) => (
            <div key={i} className="border rounded-lg p-4 bg-white/70">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <p className="text-sm font-bold text-grey-900">
                  {ph.phase || `Phase ${i + 1}`}
                </p>
                {ph.timeline && (
                  <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-grey-950 text-white">
                    {ph.timeline}
                  </span>
                )}
              </div>
              {ph.objective && (
                <p className="module-body mt-2"><HighlightedText text={ph.objective} /></p>
              )}
              {ph.steps.length > 0 && (
                <ol className="mt-3 space-y-2.5">
                  {ph.steps.map((s, j) => (
                    <li key={j} className="module-body flex gap-2.5">
                      <span className="font-bold text-grey-950 shrink-0 tabular-nums">
                        {j + 1}.
                      </span>
                      <span><HighlightedText text={s} /></span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="border rounded-lg p-4 bg-white/70">
        <p className="module-label mb-1.5">Responsible Agency</p>
        <p className="module-value">{m3.responsible_agency || "—"}</p>
        <div className="mt-1.5 flex items-center gap-2">
          <span className="dot-indicator !gap-1.5 !text-xs">
            <span
              className="dot !w-1.5 !h-1.5"
              style={{ background: AGENCY_GROUNDING_DOT[grounding] || palette.status.red }}
            />
            <span className="text-grey-950">
              {grounding === "document_named"
                ? "Named in document"
                : grounding === "document_implied"
                ? "Implied by document"
                : "Not specified by policy"}
            </span>
          </span>
          {grounding === "none_identified" && (
            <span className="text-[11px] font-medium text-grey-900 italic">
              No invented agency — implementation responsibility is for the
              adopting government to assign.
            </span>
          )}
        </div>
      </div>

      {m3.documentation_requirements.length > 0 && (
        <div>
          <p className="module-heading mb-2">
            Documentation Requirements
          </p>
          <ul className="module-list">
            {m3.documentation_requirements.map((d, i) => (
              <li key={i}><HighlightedText text={d} /></li>
            ))}
          </ul>
        </div>
      )}

      {m3.monitoring_checklist.length > 0 && (
        <div>
          <p className="module-heading mb-2">
            Monitoring / Compliance Checklist
          </p>
          <ul className="space-y-2.5">
            {m3.monitoring_checklist.map((m, i) => (
              <li key={i} className="module-body flex items-start gap-2.5">
                <span className="font-bold text-grey-950 mt-0.5 shrink-0 text-sm leading-relaxed">☐</span>
                <span><HighlightedText text={m} /></span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {realCitations.length > 0 && (
        <CitationAccordion
          label="Sources"
          total={realCitations.length}
          summary={`${realCitations.length} implementation ${
            realCitations.length === 1 ? "source" : "sources"
          } · ${citationsVerified}/${realCitations.length} verified`}
        >
          {citations.map((c, i) => (
            <CitationRow key={`${c.chunk_id}-${i}`} citation={c} />
          ))}
        </CitationAccordion>
      )}
    </div>
  );
}

// ── Section 4: Case Intelligence (only when a genuine match exists) ──────
// Shown inside a dimension block ONLY when module_4.matched is true — a
// Partial/Missing dimension with no relevant curated incident shows nothing.

function Module4Panel({ gap }: { gap: GovernanceGap }) {
  const m4 = gap.module_4;
  if (!m4 || !m4.matched || m4.incident_matches.length === 0) return null;

  return (
    <div className="space-y-5">
        {/* A curated incident is shown to make a gap concrete, not to predict
            one. The lead-in says so, because a documented failure printed
            under a dimension implies a forecast unless something states the
            opposite — and this instrument reads documents, not futures. */}
        <p className="text-[11px] leading-[1.5] text-grey-600">
          These are documented incidents from the curated case library that turned on the
          governance this dimension is missing. They are shown to make the gap concrete — what
          has already gone wrong elsewhere when this control was absent — not as a prediction
          about this jurisdiction.
        </p>
        {m4.incident_matches.map((inc, i) => {
          // Source citation — collapsed "Show Sources" toggle (same pattern
          // as Module 2) when the incident has a real chunk-backed citation;
          // a citation without a chunk stays plain so it isn't hidden by a
          // zero-count accordion.
          const citation = inc.citation;
          const realCitation = Boolean(
            citation && citation.chunk_id && citationIsVisible(citation)
          );
          return (
            <motion.div
              key={i}
              whileHover={{ scale: 1.01, y: -1 }}
              transition={{ duration: DUR.fast, ease: EASE.out }}
              className="border rounded-lg p-4 bg-white/70 space-y-2.5 hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between gap-2 flex-wrap">
                <p className="text-sm font-bold text-grey-950">
                  {inc.incident_name}
                </p>
                {inc.source && (
                  <span className="module-meta">{inc.source}</span>
                )}
              </div>
              {/* Facts first. The panel used to name a case and then jump
                  straight to why it is relevant, which asks the reader to
                  take the incident on trust. */}
              {inc.what_happened && (
                <p className="module-body">
                  <span className="font-semibold">What happened: </span>
                  <HighlightedText text={inc.what_happened} />
                </p>
              )}
              {inc.dimension_relevance && (
                <p className="module-body">
                  <span className="font-semibold">Relevance: </span>
                  <HighlightedText text={inc.dimension_relevance} />
                </p>
              )}
              {inc.potential_consequence && (
                <p className="module-body">
                  <span className="font-semibold">Potential Consequence: </span>
                  <HighlightedText text={inc.potential_consequence} />
                </p>
              )}
              {inc.lessons_learned && (
                <p className="module-body">
                  <span className="font-semibold">Lessons Learned: </span>
                  <HighlightedText text={inc.lessons_learned} />
                </p>
              )}
              {inc.mitigation && (
                <p className="module-body">
                  <span className="font-semibold">Mitigation: </span>
                  <HighlightedText text={inc.mitigation} />
                </p>
              )}
              {citation &&
                (realCitation ? (
                  <CitationAccordion
                    label="Sources"
                    total={1}
                    summary={`1 source · ${citation.verified ? "1/1" : "0/1"} verified`}
                  >
                    <CitationRow citation={citation} />
                  </CitationAccordion>
                ) : (
                  <CitationRow citation={citation} />
                ))}
            </motion.div>
          );
        })}
    </div>
  );
}

// ── Per-dimension block ──────────────────────────────────────────────────

// ── Dimension analysis-failure state (LLM quota/provider error) ──────────

function AnalysisFailedPanel({ gap }: { gap: GovernanceGap }) {
  return (
    <div className="rounded-xl border border-[color:var(--border)] bg-white p-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="dot-indicator !gap-1.5 !text-xs">
          <span className="dot !w-1.5 !h-1.5" style={{ background: palette.status.red }} />
          <span className="font-semibold text-grey-950">Analysis failed</span>
        </span>
        <span className="text-xs font-bold text-grey-950">
          This dimension was NOT assessed — no coverage verdict exists.
        </span>
      </div>
      <p className="text-sm font-medium text-grey-950">
        The analysis service did not return a result for this dimension on
        this run, so nothing here is a finding about the document.
      </p>
      <p className="text-xs font-medium text-grey-900 italic">
        Use Re-run above to assess it. Dimensions that completed are kept, so
        only this one is redone.
      </p>
    </div>
  );
}

function DimensionBlock({ gap, index }: { gap: GovernanceGap; index: number }) {
  const [open, setOpen] = useState(false);
  const depth = gap.module_1?.implementation_depth || gap.implementation_depth;
  const failed = Boolean(gap.analysis_error);

  // Skiper16-style scroll deck: one sticky card per module, in order
  // (Evaluation → Recommendations/Best Practices → Roadmap → Case). The deck
  // card provides the module name + status meta, so panels are content-only.
  // Items are conditional per the coverage tier — Fully Covered shows Best
  // Practices (no roadmap), Partial/Missing show Recommendations + Roadmap,
  // and Case Intelligence only when a genuine curated incident match exists.
  const isBestPractices =
    gap.coverage === "Covered" && Boolean(gap.module_2?.best_practices);
  const hasRoadmap =
    gap.coverage !== "Covered" && Boolean(gap.module_3);
  const m4 = gap.module_4;
  const hasCase = Boolean(
    m4 && m4.matched && m4.incident_matches.length > 0
  );

  const moduleItems: ModuleStackItem[] = [
    {
      id: "evaluation",
      title: "Evaluation",
      content: <Module1Panel gap={gap} />,
    },
    {
      id: "alignment",
      title: isBestPractices
        ? "Best Practices & Alignment"
        : "Recommendations & Alignment",
      meta: isBestPractices ? (
        <span className="dot-indicator !gap-1.5 !text-xs">
          <span className="dot !w-1.5 !h-1.5" style={{ background: palette.status.green }} />
          <span className="text-grey-950">No critical gaps</span>
        </span>
      ) : gap.module_2?.priority ? (
        <span className="dot-indicator !gap-1.5 !text-xs">
          <span
            className="dot !w-1.5 !h-1.5"
            style={{
              background: PRIORITY_DOT[gap.module_2.priority] || palette.black,
            }}
          />
          <span className="text-grey-950">{gap.module_2.priority}</span>
        </span>
      ) : undefined,
      content: <Module2Panel gap={gap} />,
    },
    ...(hasRoadmap
      ? [
          {
            id: "roadmap",
            title: "Implementation Roadmap",
            content: <Module3Panel gap={gap} />,
          },
        ]
      : []),
    ...(hasCase
      ? [
          {
            id: "case",
            title: "Case Intelligence",
            meta: (
              <span className="dot-indicator !gap-1.5 !text-xs">
                <span className="dot !w-1.5 !h-1.5" style={{ background: palette.black }} />
                <span className="text-grey-950">Curated incident match</span>
              </span>
            ),
            content: <Module4Panel gap={gap} />,
          },
        ]
      : []),
  ];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      // Once per card, a little into the viewport — the reveal a reader
      // scrolling down the dimension list used to see. `once: true` so an
      // opened-then-scrolled-past card never re-plays the entrance.
      viewport={{ once: true, amount: 0.2 }}
      className={`bg-white rounded-xl shadow-sm border ${
        failed ? "border-status-red-line" : "border-[color:var(--border)]"
      }`}
      transition={{
        layout: { duration: DUR.slow, ease: EASE.outSoft },
        opacity: { duration: DUR.base, ease: EASE.out, delay: Math.min(index * 0.05, 0.25) },
        y: { duration: DUR.base, ease: EASE.out, delay: Math.min(index * 0.05, 0.25) },
      }}
    >
      {/* Header — owns its own corner rounding now that the card no longer
          clips with overflow-hidden (which would break the sticky deck). */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={`pressable w-full flex items-center justify-between gap-3 px-5 py-4 text-left transition-colors ${
          open ? "rounded-t-xl" : "rounded-xl"
        } ${failed ? "hover:bg-status-red-tint/60" : "hover:bg-grey-50/70"}`}
      >
        <div className="flex items-center gap-3 flex-wrap">
          <h3 className="font-bold text-lg text-grey-950">{gap.dimension}</h3>
          {failed ? (
            <span className="dot-indicator">
              <span className="dot" style={{ background: palette.status.red }} />
              <span>Analysis failed</span>
            </span>
          ) : (
            <motion.span
              initial={{ scale: 0.7, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{
                type: "spring",
                stiffness: 520,
                damping: 30,
                mass: 0.6,
                delay: 0,
              }}
              className="inline-flex"
            >
              <CoverageIndicator coverage={gap.coverage} />
            </motion.span>
          )}
          {/* An un-assessed dimension has no depth — a stage badge beside
              'Analysis failed' or 'Insufficient Evidence' would describe a
              regime nobody assessed. Risk labels (Low/Medium/High) were removed from the
              UI; risk_level stays in the data for backend priority logic. */}
          {!failed && gap.coverage !== "Insufficient Evidence" && (
            <motion.span
              initial={{ scale: 0.7, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{
                type: "spring",
                stiffness: 520,
                damping: 30,
                mass: 0.6,
                delay: 0.05,
              }}
              className="inline-flex"
            >
              <DepthBadge level={depth} />
            </motion.span>
          )}
        </div>
        {/* Chevron: rotation communicates the open/closed state — transform
            only, no layout jump. */}
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: DUR.fast, ease: EASE.out }}
          className="text-grey-950 text-sm shrink-0 inline-block"
          aria-hidden
        >
          ▼
        </motion.span>
      </button>

      {/* Expand/collapse: content fades in; the card's own layout animation
          handles the height growth (no overflow-hidden, so the sticky deck
          cards keep sticking to the viewport while scrolling). */}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="dim-content"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: DUR.base, ease: EASE.out }}
            className="px-5 pb-5 space-y-4"
          >
            <motion.div variants={staggerChild}>
              {failed ? (
                <AnalysisFailedPanel gap={gap} />
              ) : (
                <ModuleStack items={moduleItems} />
              )}
            </motion.div>

              {gap.evidence.length > 0 && (
                <motion.details variants={staggerChild} className="border-t pt-3">
                  <summary className="text-sm font-semibold text-grey-950 cursor-pointer hover:opacity-70 transition-opacity">
                    Retrieved passages ({gap.evidence.length})
                  </summary>
                  <div className="mt-3 space-y-3">
                    {gap.evidence.map((ev) => (
                      <CitationCard key={ev.chunk_id} evidence={ev} />
                    ))}
                  </div>
                </motion.details>
              )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ── Executive decision analytics (deterministic aggregates) ──────────────

// Weakest dimensions rule: take the lowest coverage tier present (Missing is
// weaker than Partial, Partial weaker than Covered), then keep only the
// highest-priority dimensions in that tier — Critical/High only, no Medium/
// Low. Priority is the Module 2 recommendation priority, used purely as a
// sort/filter key so the card stays factual (coverage tier is deterministic
// from the ladder). If none of the weakest tier carry Critical/High priority
// the tier is shown as-is, so the card is never empty while gaps exist.
const PRIORITY_RANK: Record<string, number> = {
  Critical: 0,
  High: 1,
  Medium: 2,
  Low: 3,
};

const WEAK_TIER: Record<string, number> = {
  Missing: 0,
  Partial: 1,
  Covered: 2,
};

function DecisionAnalyticsCard({
  analytics,
  gaps,
  analyses,
  currentAnalysisId,
}: {
  analytics: DecisionAnalytics;
  gaps: GovernanceGap[];
  analyses: Analysis[];
  currentAnalysisId: string;
}) {
  // Every dimension's absent mechanisms, pooled and ranked across the whole
  // run. Pooling is the point: a reader wants the most consequential gaps in
  // the document, not the worst gap inside each dimension separately.
  const priorityGaps = useMemo(() => {
    const rows = gaps.flatMap((g) =>
      (g.priority_gaps || []).map((pg) => ({
        dimension: g.dimension,
        mechanism: pg.mechanism,
        expected_by: pg.expected_by,
      })),
    );
    return rows
      .filter((r) => r.expected_by > 0)
      .sort((a, b) => b.expected_by - a.expected_by)
      .slice(0, 8);
  }, [gaps]);

  const corpusSize = useMemo(
    () => Math.max(0, ...gaps.map((g) => g.framework_corpus_size || 0)),
    [gaps],
  );

  // The trajectory compares this run against what came before it — on the
  // very first run there is no "before", so it has nothing to show. Gated on
  // the run actually being VIEWED, not just on the workspace having more than
  // one run overall: opening run 1 of a two-run workspace must not show a
  // trajectory into a future run the reader hasn't gotten to yet.
  const isBaselineRun = useMemo(() => {
    if (analyses.length < 2) return true;
    return [...analyses].sort(byStage)[0]?.analysis_id === currentAnalysisId;
  }, [analyses, currentAnalysisId]);
  const radar = useMemo(() => {
    const values: Record<string, number> = {};
    let notAssessed = 0;
    for (const g of gaps) {
      const assessed =
        !g.analysis_error && g.coverage !== "Insufficient Evidence";
      if (!assessed) notAssessed += 1;
      values[g.dimension] = assessed ? RADAR_SCORE[g.coverage] ?? 0 : 0;
    }
    return { values, notAssessed };
  }, [gaps]);

  const radarMetrics = useMemo(
    () =>
      gaps.map((g) => ({
        key: g.dimension,
        label: RADAR_DISPLAY[g.dimension] || g.dimension,
      })),
    [gaps]
  );
  const radarSeries = useMemo(
    () => [{ label: "Coverage", color: palette.black, values: radar.values }],
    [radar.values]
  );

  // Weakest dimensions — see the rule above. Pairs with Strongest Dimension.
  const weakestDimensions = useMemo(() => {
    const assessed = gaps.filter(
      (g) => !g.analysis_error && g.coverage !== "Insufficient Evidence"
    );
    if (!assessed.length) return [];
    const weakestRank = Math.min(
      ...assessed.map((g) => WEAK_TIER[g.coverage] ?? 9)
    );
    // Nothing is below Covered — every dimension is fully covered, so there
    // is no weakest class to report. "None flagged" is the honest answer.
    if (weakestRank >= 2) return [];
    const weakest = assessed.filter(
      (g) => (WEAK_TIER[g.coverage] ?? 9) === weakestRank
    );
    const high = weakest.filter(
      (g) =>
        g.module_2?.priority === "Critical" || g.module_2?.priority === "High"
    );
    const list = high.length ? high : weakest;
    return list
      .slice()
      .sort(
        (a, b) =>
          (PRIORITY_RANK[a.module_2?.priority ?? ""] ?? 9) -
          (PRIORITY_RANK[b.module_2?.priority ?? ""] ?? 9)
      )
      .map((g) => g.dimension);
  }, [gaps]);

  return (
    <motion.div
      variants={staggerContainer(0.08, 0.05)}
      initial="hidden"
      animate="show"
      className="card"
    >
      <div className="flex items-center justify-between mb-4">
        <motion.h2
          variants={staggerChild}
          className="text-lg font-bold text-grey-950"
        >
          Decision Analytics
        </motion.h2>
        <motion.span variants={staggerChild} className="eyebrow">
          Dashboard-ready
        </motion.span>
      </div>

      {/* Row 1: the two charts side by side — coverage donut and depth
          gauge, both animating their fill on load. These are the visual
          centerpiece of the section. Panels are solid white on the card
          surface — clean, not glass. */}
      <div className="grid md:grid-cols-2 gap-4">
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4"
        >
          <p className="eyebrow mb-3">Coverage Distribution</p>
          <CoverageDonut analytics={analytics} />
        </motion.div>
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4"
        >
          <p className="eyebrow mb-3">Implementation Depth</p>
          <DepthGauge analytics={analytics} />
          <StageHistogram analytics={analytics} />
        </motion.div>
      </div>

      {/* Row 2: the dimension radar — every dimension at a glance, each
          vertex on the ring of its coverage tier, sitting right below the
          donut + gauge. Uses the reference composite API (RadarChart +
          RadarGrid/Axis/Labels/Area). */}
      {radarMetrics.length > 0 && (
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4 mt-4"
        >
          <div className="flex items-center justify-between flex-wrap gap-2 mb-1">
            <p className="eyebrow">Dimension Radar</p>
            {radar.notAssessed > 0 && (
              <p className="text-[11px] font-medium text-grey-900 italic">
                {radar.notAssessed} dimension
                {radar.notAssessed > 1 ? "s" : ""} not assessed (centre)
              </p>
            )}
          </div>
          <div className="flex flex-col items-center">
            <RadarChart
              data={radarSeries}
              metrics={radarMetrics}
              size={380}
              ariaLabel="Dimension coverage radar chart"
            >
              <RadarGrid />
              <RadarAxis />
              <RadarLabels />
              <RadarArea index={0} showPoints tooltip={radarTooltip} />
            </RadarChart>
            <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 mt-2 text-xs">
              {RADAR_TIER_LEGEND.map((tier) => (
                <RadarRingLegend key={tier.label} {...tier} />
              ))}
            </div>
            <p className="text-[11px] font-medium text-grey-900 mt-1.5 italic">
              Ring position = coverage tier
            </p>
          </div>
        </motion.div>
      )}

      {/* Row 3: the two highlight cards — weakest + strongest dimension,
          below the radar. Weakest = the lowest coverage tier present, kept
          only when it carries Critical/High priority (no Medium/Low), sorted
          by priority; the strongest is the highest-depth dimension. */}
      <div className="grid md:grid-cols-2 gap-4 mt-4">
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4"
        >
          <p className="eyebrow mb-2">Weakest Dimensions</p>
          {weakestDimensions.length ? (
            <div className="flex flex-wrap gap-2 mt-2">
              {weakestDimensions.map((d) => (
                <span key={d} className="dot-indicator">                <span
                  className="dot"
                  style={{ background: palette.status.red }}
                />
                  <span>{d}</span>
                </span>
              ))}
            </div>
          ) : (
            <p className="text-sm font-medium text-grey-950 mt-1">None flagged</p>
          )}
        </motion.div>
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4"
        >
          <p className="eyebrow mb-2">Strongest Dimension</p>
          <p className="text-lg font-semibold text-grey-950 mt-1">
            {analytics.strongest_dimension || "—"}
          </p>
        </motion.div>
      </div>

      {/* Row 4: what to fix first.

          The mechanism inventory was computed, persisted and never shown. A
          flat "4 of 6 provided" cannot answer the only question a ministry
          actually has, which is which of the absent two matters more. Ordering
          the gaps by how many reference instruments name each one answers it,
          and grounds the answer outside our own opinion.

          Deliberately NOT a score. Nothing here feeds coverage or depth; it
          decides what a reader sees at the top of a list. */}
      {priorityGaps.length > 0 && (
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4 mt-4"
        >
          <p className="eyebrow mb-1">Priority Gaps</p>
          <p className="text-[11px] text-grey-600 mb-3">
            Mechanisms with no supporting provision in the evidence scored for
            their dimension, shown only where at least half of the{" "}
            {corpusSize || 43} indexed instruments expect them. Ordered by how
            many expect each. This ranks what to look at first; it does not
            affect any score.
          </p>
          <ul className="space-y-1.5">
            {priorityGaps.map((g) => (
              <li
                key={`${g.dimension}-${g.mechanism}`}
                className="flex items-center gap-3 text-sm"
              >
                <span
                  className="h-1.5 rounded-full shrink-0"
                  style={{
                    width: `${Math.max(8, (g.expected_by / (corpusSize || 43)) * 84)}px`,
                    background: palette.status.red,
                  }}
                />
                <span className="font-medium text-grey-950">{g.mechanism}</span>
                <span className="text-grey-600 text-[11px]">{g.dimension}</span>
                <span className="ml-auto text-[11px] text-grey-600 tabular-nums">
                  expected by {g.expected_by} of {corpusSize || 43}
                </span>
              </li>
            ))}
          </ul>
        </motion.div>
      )}

      {/* Row 4: regulatory trajectory — only meaningful once a workspace
          holds more than one run. Shows what each added instrument actually
          moved, per dimension, without opening two run tabs to read two
          tables from memory. */}
      {!isBaselineRun && (
        <motion.div
          variants={staggerChild}
          className="rounded-xl border border-[color:var(--border)] bg-white p-4 mt-4"
        >
          <p className="eyebrow mb-1">Regulatory Trajectory</p>
          <p className="text-[11px] text-grey-600 mb-3">
            Coverage and depth stage per dimension, across every run in
            this workspace — what each added instrument actually moved.
          </p>
          <RunComparisonHeatmap analyses={analyses} />
        </motion.div>
      )}
    </motion.div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────

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
      if (seq === loadSeq.current) setError("Failed to load analysis");
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
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function loadAnalysis() {
    loadAnalysisFor(selectedWs);
  }

  return (
    <FrameworkLibraryContext.Provider value={frameworks}>
    <div className="space-y-8">
      {/* Centred heading with the Ask AI button anchored right. Symmetric
          side columns — the left one mirrors the button's reserved width —
          keep the centre column optically centred whether or not the
          button is present. */}
      <div className="flex items-center">
        <div aria-hidden className="w-24 shrink-0" />
        <div className="min-w-0 flex-1 text-center">
          {/* Static heading — the previous BlurText reveal effect was
              removed at the user's request. Size, weight and colour
              (clamp 3.25rem → 4rem, 800, #0A0A0A) are unchanged. */}
          <h1 className="text-[clamp(3.25rem,7vw,4rem)] leading-[1.05] font-extrabold text-grey-950 tracking-tight text-center">
            Governance Analysis
          </h1>
          <p className="text-grey-950 font-medium mt-4 max-w-2xl mx-auto">
            Evidence-based gap analysis of the policy across eight governance
            dimensions.
          </p>
        </div>
        <div className="flex w-24 shrink-0 justify-end">
        {analysis && (
          <button
            onClick={() => {
              // Force advisor mode: the side chat answers ONLY about this
              // analysis — how each finding was reached, why, the evidence
              // and reasoning — scoped to the loaded workspace.
              setWorkspaceId(selectedWs);
              setFindingContext(null, null);
              setMode("advisor");
              openPanel();
            }}
            className="pressable shrink-0 bg-grey-950 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-grey-800 transition-colors"
          >
            Ask AI
          </button>
        )}
        </div>
      </div>

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
                label: `${ws.country} — ${ws.policy_title}`,
              }))}
            />
          </div>
          {/* Always black and always clickable-looking — loadAnalysis()
              itself no-ops when no workspace is selected. */}
          <SpecularButton
            size="md"
            className="specular-button--compact"
            radius={12}
            tint={palette.black}
            tintOpacity={1}
            blur={0}
            textColor={palette.white}
            lineColor={palette.white}
            baseColor={palette.black}
            intensity={1.2}
            shineSize={10}
            shineFade={40}
            thickness={1.2}
            speed={0.35}
            followMouse
            proximity={250}
            autoAnimate={false}
            disabled={loading}
            onClick={loadAnalysis}
          >
            {loading ? "Loading..." : "View Analysis"}
          </SpecularButton>
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
              ? " Showing the most recently completed results below — this will update automatically once the new run finishes."
              : " Results will appear here automatically once it finishes."}
          </span>
        </div>
      )}

      {error && (            <div className="bg-status-amber-tint border border-status-amber-line text-status-amber-ink px-4 py-3 rounded-lg text-sm">
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
            <h2 className="text-xl font-semibold text-grey-950">
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
