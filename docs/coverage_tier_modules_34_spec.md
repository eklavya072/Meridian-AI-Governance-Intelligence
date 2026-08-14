# Coverage-Tiered Output — Modules 3 & 4 (Future Build Spec)

> **Status:** Deferred. Modules 3 & 4 are NOT built yet. This file preserves the
> user's exact spec so the future Part-2/Part-3 build can implement it verbatim
> without needing the original prompt. Modules 1 & 2 (with the same tiering
> logic) are already live — see `gap_analyzer.resolve_priority()` and the
> `best_practices`/`coverage_example` fields.

## Master rule (applies to ALL modules)

Enforce tiering **in code** via a conditional on the `coverage` field
(`Covered` / `Partial` / `Missing`). Never leave it to LLM judgment.

## Fully Covered tier

- **Module 1:** full, as always. Remove `reason_flagged` and
  `coverage_reasoning` from display; instead show `coverage_example` — concrete
  examples from the uploaded document that led to the Covered conclusion
  (substantive/theoretical, not verbatim citations). Fields shown: Coverage,
  Evidence, Governance Maturity, Confidence.
- **Module 2:** replaces Recommendations/Priority with **Best Practices**:
  - Fixed opening line (already code-emitted as `BEST_PRACTICES_OPENING` in
    `gap_analyzer.py`):
    > "This policy already aligns strongly with international governance
    > expectations. The following international practices may further
    > strengthen future revisions, but no critical governance gaps were
    > identified."
  - 2–3 **Future Strengthening Opportunities** (renamed from "Optional
    Enhancements" — "optional" reads as "ignore" to governments).
  - Relevant **International Examples** — must be REAL, CITED practices from
    other countries/frameworks, never invented (anti-fabrication rule; already
    enforced via `_verify_international_examples` — ungrounded examples are
    dropped).
  - Framework Synthesis stays (justifies why the policy is compliant).
- **Module 3:** skip entirely — no Implementation Roadmap, no Responsible
  Agency, no Compliance Checklist (not even a lightweight version).
- **Module 4:** skip entirely — no incident matching, no "cautionary example"
  framing. A Fully Covered finding gets no case-study content.
- **Priority field:** omit or set to `null` (nothing to prioritise).

## Partially Covered tier

- **Module 1:** full, as always, including Gap Detected.
- **Module 2:** full Recommendations + Priority (**Medium by default**,
  escalating per the existing risk-compounding rule) + full Framework
  Synthesis.
- **Module 3:** full Implementation Roadmap (Phase 1 / Phase 2) +
  Monitoring/Compliance Checklist.
- **Module 4:** attempt incident matching, but ONLY include it if a genuinely
  relevant match exists — do NOT force a weak/loosely-related incident just to
  fill the section. If no good match, omit Module 4 for that dimension.

## Missing tier

- **Module 1:** full, as always.
- **Module 2:** full Recommendations + Priority **defaulting to High** (per
  existing core-vs-supporting/compounding rule) + full Framework Synthesis,
  with explicit urgency framing in reasoning fields (prompt-level tone
  instruction, not a separate field).
- **Module 3:** full Implementation Roadmap, Responsible Agency, Compliance
  Checklist. **Responsible Agency must be grounded in a real institutional
  structure already referenced in the document if one exists**; otherwise
  explicitly state "Not specified by policy — implementation responsibility
  should be assigned by the adopting government." — never invent a
  plausible-sounding agency.
- **Module 4:** incident matching more assertive than Partial — if the curated
  incident database has any reasonably relevant match, include it with explicit
  "Potential Consequence" framing. Only omit if truly nothing relevant exists
  in the curated set. Never fabricate an incident.

## Cross-cutting requirements

- **Pydantic schema:** Module 2/3/4 fields conditionally required by coverage —
  Fully Covered dimensions have `recommendations`, `priority`,
  `implementation_roadmap`, and `case_intelligence` all nullable/absent, never
  populated with filler.
- **Token reduction:** Fully Covered must measurably reduce output tokens (no
  Module 3/4 generation at all). Per-tier token/char stats are already logged
  (`tier_output_stats` log event + `GapAnalysisResult.tier_stats`).
- **Frontend:** three tiers visually distinct at a glance — Covered blocks
  noticeably shorter/lighter (2–3 sections); Partial full; Missing full.
  "International Examples" must be real, cited practices — same anti-fabrication
  rule as the rest of the project.

## Open question (parked)

How sharply should Missing vs. Partial differ in Module 4's incident-inclusion
threshold? (Asked by the user as the one place the two tiers could look too
similar. Decide when Module 4 is built.)
