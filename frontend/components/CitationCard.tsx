"use client";

import { motion } from "motion/react";
import type { RetrievedEvidence } from "@/lib/api";
import { verifiedSnap } from "@/lib/motion";

// A section label a reader can look up: a numbered division, as ingestion now
// records it. Stored runs predate that and can carry any line of the PDF as
// their "section" ("available;", "EN OJ L, 12.7.2024"), so the same rule is
// applied here rather than trusting the stored value.
const DIVISION_RE =
  /^(?:Article|Section|Chapter|Part|Title|Annex|Schedule|Appendix|Principle|ARTICLE|SECTION|CHAPTER|PART|TITLE|ANNEX|SCHEDULE|APPENDIX)\s+[0-9IVXLC]+[A-Za-z]?(?:\s*[-–:]?\s+[A-Z][^.;]*)?\s*$/;
const SENTENCE_VERB_RE = /\b(?:shall|must|may|is|are|be|will|should)\b/;

function sectionLabel(title: string | null | undefined): string | null {
  const t = (title || "").replace(/\s+/g, " ").trim();
  if (!t || !DIVISION_RE.test(t)) return null;
  if (t.length > 80 || SENTENCE_VERB_RE.test(t)) return t.split(" ").slice(0, 2).join(" ");
  return t;
}

export default function CitationCard({
  evidence,
}: {
  evidence: RetrievedEvidence;
}) {
  const verified = evidence.verified;
  const verification = evidence.verification;
  const section = sectionLabel(evidence.section_title);

  return (
    <div className="border rounded-lg p-4 space-y-2 bg-grey-50">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-grey-950 line-clamp-3 flex-1">
          {evidence.text}
        </p>
        {verified ? (
          <motion.span
            {...verifiedSnap}
            className="shrink-0 text-xs font-medium px-2 py-0.5 rounded bg-status-green-tint text-status-green-ink"
          >
            ✓ Verified
          </motion.span>
        ) : (
          <span className="shrink-0 text-xs font-medium px-2 py-0.5 rounded bg-status-red-tint text-status-red">
            Unverified
          </span>
        )}
      </div>

      {/* Where to find it, and nothing else. The storage id and the raw
          retrieval similarity used to sit here too; neither tells a reader
          anything they can check against the document. */}
      <div className="flex flex-wrap gap-3 text-xs font-medium text-grey-900">
        {evidence.document_name ? (
          <span className="text-grey-950">
            Document: {evidence.document_name}
          </span>
        ) : (
          <span>Framework: {evidence.source_framework}</span>
        )}
        {section && <span>{section}</span>}
        {evidence.page_number && <span>Page {evidence.page_number}</span>}
      </div>

      {verification && !verified && (
        <details className="text-xs text-status-red">
          <summary className="cursor-pointer font-medium">
            Verification details
          </summary>
          <ul className="mt-1 space-y-0.5 list-disc list-inside">
            <li>
              Passage found in the document: {verification.chunk_exists ? "✓" : "✗"}
            </li>
            <li>
              Page number matches: {verification.page_exists ? "✓" : "✗"}
            </li>
            <li>
              Passage supports the claim:{" "}
              {verification.text_supports_claim ? "✓" : "✗"}
            </li>
            {verification.failure_reason && (
              <li className="text-status-red">{verification.failure_reason}</li>
            )}
          </ul>
        </details>
      )}
    </div>
  );
}
