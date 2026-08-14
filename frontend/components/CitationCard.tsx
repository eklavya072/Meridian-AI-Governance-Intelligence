"use client";

import { motion } from "motion/react";
import type { RetrievedEvidence } from "@/lib/api";
import { verifiedSnap } from "@/lib/motion";

export default function CitationCard({
  evidence,
}: {
  evidence: RetrievedEvidence;
}) {
  const verified = evidence.verified;
  const verification = evidence.verification;

  return (
    <div className="border rounded-lg p-4 space-y-2 bg-gray-50">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-navy-950 line-clamp-3 flex-1">
          {evidence.text}
        </p>
        {verified ? (
          <motion.span
            {...verifiedSnap}
            className="shrink-0 text-xs font-medium px-2 py-0.5 rounded bg-[#EAF1EC] text-[#3F7A52]"
          >
            ✓ Verified
          </motion.span>
        ) : (
          <span className="shrink-0 text-xs font-medium px-2 py-0.5 rounded bg-[#F6ECEB] text-[#A8483F]">
            Unverified
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-3 text-xs font-medium text-navy-900">
        <span className="font-mono">
          Chunk: {evidence.chunk_id.slice(0, 8)}...
        </span>
        {evidence.page_number && <span>Page: {evidence.page_number}</span>}
        {evidence.document_name ? (
          <span className="text-undp-blue">
            Document: {evidence.document_name}
          </span>
        ) : (
          <span>Framework: {evidence.source_framework}</span>
        )}
        {evidence.similarity_score != null && (
          <span>Score: {evidence.similarity_score.toFixed(3)}</span>
        )}
        {evidence.section_title && <span>Section: {evidence.section_title}</span>}
      </div>

      {verification && !verified && (
        <details className="text-xs text-[#A8483F]">
          <summary className="cursor-pointer font-medium">
            Verification details
          </summary>
          <ul className="mt-1 space-y-0.5 list-disc list-inside">
            <li>
              Chunk exists: {verification.chunk_exists ? "✓" : "✗"}
            </li>
            <li>
              Page exists: {verification.page_exists ? "✓" : "✗"}
            </li>
            <li>
              Text supports claim:{" "}
              {verification.text_supports_claim ? "✓" : "✗"}
            </li>
            {verification.failure_reason && (
              <li className="text-[#A8483F]">{verification.failure_reason}</li>
            )}
          </ul>
        </details>
      )}
    </div>
  );
}
