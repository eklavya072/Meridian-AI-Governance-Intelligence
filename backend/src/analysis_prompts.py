from __future__ import annotations

from typing import Any


DIMENSION_DEFINITIONS: dict[str, list[str]] = {
    "Transparency": [
        "AI systems should be developed and operated in a transparent manner",
        "Disclosure of AI system capabilities, limitations, and decision-making processes",
        "Explainability of AI outcomes to affected individuals",
        "Auditability of AI systems through documentation and logging",
        "Openness about data sources, training methods, and model behavior",
    ],
    "Accountability": [
        "Clear allocation of responsibility for AI system outcomes",
        "Liability frameworks for harms caused by AI systems",
        "Grievance redressal mechanisms for individuals affected by AI decisions",
        "Oversight mechanisms to ensure responsible AI deployment",
        "Remediation pathways when AI systems cause harm",
    ],
    "Privacy": [
        "Protection of personal data used in AI training and inference",
        "Informed consent for data collection and processing",
        "Anonymization and de-identification of personal information",
        "Data security measures to prevent unauthorized access or misuse",
        "Compliance with data protection regulations and privacy-by-design principles",
    ],
    "Safety": [
        "Systematic identification and assessment of AI-related risks",
        "Impact assessment processes before AI system deployment",
        "Safety testing and validation of AI systems",
        "Due diligence requirements for AI developers and deployers",
        "Mitigation measures for identified AI risks",
        "Monitoring and reporting mechanisms for AI incidents",
    ],
    "Human Autonomy": [
        "Meaningful human control over AI decision-making processes",
        "Human-in-the-loop requirements for high-stakes AI decisions",
        "Human-on-the-loop supervision for automated systems",
        "Right to human review of AI-generated decisions",
        "Human judgment must prevail over automated determinations in critical contexts",
    ],
    "Inclusivity": [
        "Equitable access to AI technologies and their benefits",
        "Non-discrimination in AI system design and deployment",
        "Fairness across demographic groups in AI outcomes",
        "Accessibility of AI systems for persons with disabilities",
        "Bias detection and mitigation throughout AI lifecycle",
        "Participation of underrepresented groups in AI governance",
    ],
    "Fairness": [
        "Equitable treatment across all population groups in AI system design",
        "Bias testing and mitigation throughout the AI lifecycle",
        "Demographic parity considerations in AI outcomes",
        "Inclusive design practices for diverse user populations",
        "Protection against discrimination based on protected characteristics",
    ],
    "Environmental Sustainability": [
        "Energy efficiency of AI training and inference",
        "Carbon footprint reporting and reduction targets",
        "Computational resource optimization",
        "Hardware lifecycle and e-waste management",
        "Alignment with environmental sustainability goals",
    ],
}


def build_dimension_definition_block(dimension: str) -> str:
    items = DIMENSION_DEFINITIONS.get(dimension, [f"Principles related to {dimension} in AI governance"])
    lines = [f"Dimension: {dimension}"]
    for item in items:
        lines.append(f"  - {item}")
    return "\n".join(lines)


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."

# ── Integrated Governance Maturity Framework ──────────────────────────────
# Replaces DOCUMENT_TYPE_AWARENESS, MATURITY_LEVELS, FALSE_NEGATIVE_SAFEGUARDS,
# MULTI_CAPABILITY_ASSESSMENT, CAPABILITY_DISTINCTION_GUIDE, and UNCERTAINTY_LANGUAGE
# with a single integrated framework. Same logic, ~65% fewer tokens.

INTEGRATED_MATURITY_FRAMEWORK = """
Document Type:
- National AI strategy → assess governance direction, institutional commitments, and implementation roadmaps
- Legislation/regulation → assess enforceable operational mechanisms
- Technical standard → assess specificity and rigour
- Code of conduct → assess governance philosophy and principles
DO NOT penalise a strategy for lacking operational detail that belongs in companion legislation.

Maturity Levels (each level assumes all lower levels are met):

Level 0 — No Governance Intent (→ Missing)
After exhausting ALL checks below: strategic objectives, institutional arrangements,
implementation commitments, cross-cutting structures, and related programmes,
using alternative terminology. Must fail 6 checks before Level 0 is valid.

Level 1 — Governance Recognised (→ Partial)
Dimension acknowledged through principle, commitment, or reference to international norms.
(Policy Intent capability present, no operational mechanisms yet.)

Level 2 — Institutional Ownership Identified (→ Partial)
Specific bodies, offices, or roles charged with responsibility.
(Intent + Governance Mechanisms capability.)

Level 3 — Implementation Commitment Exists (→ Covered)
Commitment to future action, resource allocation, or roadmap established.
(Intent + Mechanisms + Operational Requirements capability.)

Level 4 — Operational Mechanisms Established (→ Covered)
Concrete processes, standards, obligations defined and operational.
(Intent + Mechanisms + Requirements + Oversight capability.)

Level 5 — Continuous Monitoring and Enforcement (→ Covered)
Active oversight, enforcement powers, audit cycles, redress mechanisms.
(All capabilities: Intent + Mechanisms + Requirements + Oversight + Enforcement + Improvement.)

Coverage: Level 0 → Missing. Levels 1-2 → Partial. Levels 3-5 → Covered.
A strategy that recognises, identifies ownership, or commits to implementation is NEVER Missing.

Before assigning Level 0 check ALL of:
A. Alternative terminology — capability exists under different phrasing
B. Embedded mechanisms — capability is part of another mechanism (e.g. privacy in data governance)
C. Distributed implementation — capability is spread across sections, not one place
D. Institutional implication — mandates imply this capability without explicit statement
E. Cross-cutting structure — centralised bodies address this through mandate or reporting
F. Existing programmes — referenced initiatives serve this governance function

If uncertain, prefer Partial over Missing.

Functional equivalence: evidence of strategic objectives, institutional arrangements,
implementation commitments, cross-cutting structures, or related programmes counts
even without the dimension's exact terminology.

Evidence Strength: Not Demonstrated → Weakly Demonstrated → Implicitly Addressed →
Explicitly Addressed → Strongly Operationalised.

A strategy addresses dimensions through cross-cutting structures (central authorities,
multi-stakeholder bodies) rather than dimension-specific sections. Recognise this.
"""

# ── Stage 1: Evidence Interpretation ──────────────────────────────────────

EVIDENCE_INTERPRETATION_SYSTEM = (
    "You are a senior AI governance policy analyst. "
    "Interpret what a national AI policy document reveals about a specific governance dimension.\n\n"
    "{dimension_definition}\n\n"
    "Analyse what the policy: (1) explicitly states, (2) reasonably implies, "
    "(3) demonstrates capability for, (4) clearly omits.\n\n"
    "Identify which evidence is strong (specific, actionable, enforceable) "
    "and which is weak (aspirational, vague, general).\n\n"
    "Base analysis solely on the document. Do not compare against international frameworks.\n\n"
    'Output JSON: dimension, explicit_evidence (list), implicit_evidence (list), '
    'demonstrated_capability (str), absent_capability (str), '
    'strong_evidence (list), weak_evidence (list), contradictory_evidence (list), '
    'evidence_strength ("Strongly Operationalised"|"Explicitly Addressed"|'
    '"Implicitly Addressed"|"Weakly Demonstrated"|"Not Demonstrated"), '
    "interpretation_summary (str)"
)


def build_evidence_interpretation_prompt(
    dimension: str,
    document_excerpt: str,
    dimension_definition: str,
) -> tuple[str, str]:
    system_prompt = EVIDENCE_INTERPRETATION_SYSTEM.format(
        dimension_definition=dimension_definition,
    )
    prompt = (
        f"Dimension: {dimension}\n\n"
        f"--- National Policy Document ---\n{truncate(document_excerpt, 4000)}\n\n"
        "Interpret the evidence above. Do not classify coverage. "
        "Do not compare against external frameworks. "
        "Simply analyse what the policy says, implies, and omits.\n\n"
        "Output valid JSON only."
    )
    return system_prompt, prompt


# ── Merged Stage 1+2: Evidence + Maturity (single LLM call) ───────────────

EVIDENCE_AND_MATURITY_SYSTEM = (
    "You are a senior AI governance policy analyst.\n\n"
    "{dimension_definition}\n\n"
    "{integrated_framework}\n\n"
    "Step 1 — Evidence Interpretation:\n"
    "Analyse what the policy: (1) explicitly states, (2) reasonably implies, "
    "(3) demonstrates capability for, (4) clearly omits.\n"
    "Base analysis solely on the document. Do not compare against international frameworks.\n\n"
    "Step 2 — Maturity Assessment:\n"
    "1. Identify the document type. If a strategy, assess governance direction "
    "and institutional commitments, not procedural completeness.\n"
    "2. Apply functional equivalence BEFORE assigning a level.\n"
    "3. Derive maturity level (0-5) from the framework above.\n"
    "4. Derive coverage from semantic substance, not mechanical level mapping:\n"
    "   - Covered: The document substantively addresses the dimension's core concepts, "
    "principles, or objectives — even if it uses different terminology, synonyms, or "
    "addresses the concept indirectly. A strategy-level document that sets direction "
    "on the topic is Covered, not Partial.\n"
    "   - Partial: The document touches on the dimension tangentially or names it "
    "without substantive treatment, or covers only narrow sub-aspects.\n"
    "   - Missing: No evidence of any substantive treatment, direct or indirect.\n"
    "5. Before Missing, verify all functional equivalence checks. If uncertain, prefer Partial.\n\n"
    'Output JSON with ALL of the following keys:\n'
    'dimension: str,\n'
    'explicit_evidence: list,\n'
    'implicit_evidence: list,\n'
    'demonstrated_capability: str,\n'
    'absent_capability: str,\n'
    'strong_evidence: list,\n'
    'weak_evidence: list,\n'
    'contradictory_evidence: list,\n'
    'evidence_strength: "Strongly Operationalised" | "Explicitly Addressed" | '
    '"Implicitly Addressed" | "Weakly Demonstrated" | "Not Demonstrated",\n'
    'interpretation_summary: str,\n'
    'maturity_level: int (0-5),\n'
    'maturity_label: str,\n'
    'coverage: "Covered" | "Partial" | "Missing",\n'
    'maturity_reasoning: str,\n'
    'level_justification: str,\n'
    'uncertainty_flags: list,\n'
    'false_negative_check: str,\n'
    'maturity_trace: str'
)


def build_evidence_and_maturity_prompt(
    dimension: str,
    document_excerpt: str,
    dimension_definition: str,
) -> tuple[str, str]:
    system_prompt = EVIDENCE_AND_MATURITY_SYSTEM.format(
        dimension_definition=dimension_definition,
        integrated_framework=INTEGRATED_MATURITY_FRAMEWORK,
    )
    prompt = (
        f"Dimension: {dimension}\n\n"
        f"--- National Policy Document ---\n{truncate(document_excerpt, 4000)}\n\n"
        "Proceed through both steps. Output valid JSON with all required keys."
    )
    return system_prompt, prompt

# ── Stage 2: Maturity Assessment (simplified, integrated framework) ───────

MATURITY_ASSESSMENT_SYSTEM = (
    "You are a senior AI governance policy analyst assessing the maturity "
    "of a national AI policy document.\n\n"
    "{dimension_definition}\n\n"
    "{integrated_framework}\n\n"
    "Instructions:\n"
    "1. Identify the document type. If a strategy, assess governance direction "
    "and institutional commitments, not procedural completeness.\n"
    "2. Apply functional equivalence BEFORE assigning a level. Check strategic "
    "objectives, institutional arrangements, commitments, cross-cutting structures, "
    "and related programmes regardless of terminology.\n"
    "3. Assess each governance capability independently. Mechanisms and enforcement "
    "carry more weight than intent alone.\n"
    "4. Derive maturity level (0-5) from the framework above.\n"
    "5. Derive coverage from semantic substance: Level 0→Missing, Levels 1-2→Partial, Levels 3-5→Covered.\n"
    "6. Before Missing, verify all functional equivalence checks were considered. "
    "If uncertain, prefer Partial.\n\n"
    'Output JSON: dimension (str), maturity_level (0-5), maturity_label (str), '
    'coverage ("Covered"|"Partial"|"Missing"), '
    "maturity_reasoning (str including document type, functional equivalence outcomes, "
    "and how each capability assessment contributed), "
    "level_justification (str with specific evidence per level), "
    "uncertainty_flags (list), "
    "false_negative_check (str confirming checks performed), "
    "maturity_trace (str with structured reasoning)"
)


def build_maturity_assessment_prompt(
    dimension: str,
    evidence_interpretation: dict[str, Any],
    dimension_definition: str,
) -> tuple[str, str]:
    interpretation_summary = evidence_interpretation.get("interpretation_summary", "")
    evidence_strength = evidence_interpretation.get("evidence_strength", "Not Demonstrated")
    strong = evidence_interpretation.get("strong_evidence", [])
    weak = evidence_interpretation.get("weak_evidence", [])
    explicit = evidence_interpretation.get("explicit_evidence", [])
    implicit = evidence_interpretation.get("implicit_evidence", [])
    absent = evidence_interpretation.get("absent_capability", [])

    system_prompt = MATURITY_ASSESSMENT_SYSTEM.format(
        dimension_definition=dimension_definition,
        integrated_framework=INTEGRATED_MATURITY_FRAMEWORK,
    )

    prompt_lines = [f"Dimension: {dimension}\n"]
    prompt_lines.append(f"Evidence Interpretation Summary: {interpretation_summary}")
    prompt_lines.append(f"Evidence Strength: {evidence_strength}\n")

    prompt_lines.append("Explicit Evidence:\n" + ("\n".join(f"- {e}" for e in explicit) if explicit else "None identified"))
    prompt_lines.append("Implicit Evidence:\n" + ("\n".join(f"- {e}" for e in implicit) if implicit else "None identified"))
    prompt_lines.append("Strong Evidence:\n" + ("\n".join(f"- {s}" for s in strong) if strong else "None identified"))
    prompt_lines.append("Weak Evidence:\n" + ("\n".join(f"- {w}" for w in weak) if weak else "None identified"))
    prompt_lines.append("Absent Capability:\n" + ("\n".join(f"- {a}" for a in absent) if absent else "None identified"))

    prompt_lines.append(
        "\nApply the maturity assessment framework. "
        "Include maturity_trace with: 1) Document Type, 2) Functional Equivalence "
        "findings, 3) Level selected, 4) Why that level, 5) Why final coverage label. "
        "Output valid JSON only."
    )

    return system_prompt, "\n".join(prompt_lines)

# ── Stage 3 (merged): Recommendation + Final Output ───────────────────────

RECOMMENDATION_AND_FINAL_SYSTEM = (
    "You are a senior AI governance policy advisor producing a professional "
    "advisory report.\n\n"
    "{dimension_definition}\n\n"
    "{uncertainty_note}\n\n"
    "Write as an experienced policy advisor. Begin with existing strengths. "
    "Every claim must trace to specific policy provisions.\n\n"
    "Core question: What is the smallest realistic improvement that would "
    "significantly strengthen governance for this dimension?\n\n"
    "Principles:\n"
    "1. Strengthen existing policy structures FIRST. Only recommend creating "
    "new dedicated sections if no existing mechanism can be extended.\n"
    "2. Each recommendation must identify WHICH existing mechanism it extends.\n"
    "3. Be specific about the mechanism, the change, and the expected impact.\n"
    "4. Reference relevant international framework expectations.\n"
    "5. Vary sentence openings. Do not start every section with 'The policy...'.\n"
    "6. Vary transitions. Avoid repeating 'However', 'Furthermore'.\n"
    "7. Vary recommendation phrasing: 'The government should consider...', "
    "'A priority is...', 'Building on existing capacity...'.\n\n"
    'Output JSON with these keys:\n'
    '- dimension: str\n'
    '- coverage: "Covered" | "Partial" | "Missing"\n'
    '- maturity_level: int (0-5)\n'
    '- maturity_label: str\n'
    '- existing_strengths: str\n'
    '- governance_capability: str\n'
    '- remaining_limitations: str\n'
    "- evidence_analysis: str (trace each claim to specific policy provisions)\n"
    "- framework_synthesis: str (compare against international expectations)\n"
    '- recommendations: list of str (each identifies which mechanism it extends)\n'
    '- smallest_effective_improvement: str\n'
    '- uncertainty_note: str\n'
    '- confidence_in_assessment: "High" | "Medium" | "Low"\n'
    '- reason_flagged: str\n'
    '- risk_level: "High" | "Medium" | "Low"\n'
    '- risk_reason: str\n'
    '- potential_consequence: str\n'
    '- evidence_quotes: list of str\n'
    '- gap_analysis: str'
)


# ── Module 1 + Module 2 — Combined single-call prompt ──────────────────
# One LLM call per dimension returns BOTH the Governance Dimension
# Evaluation (Module 1) and the Recommendations & Alignment (Module 2).
# The two reasoning tasks are separated with clear section headers so the
# model does not blend "what is true" with "what to do about it".

MODULE1_2_COMBINED_SYSTEM = """
You are a senior AI governance policy analyst and advisor producing a single
structured assessment for one governance dimension of a national policy
against two deliberately different reference sets:

  - MODULE 1 sources (normative): what good looks like — principles and
    obligations (e.g. OECD AI Principles, UNESCO Recommendation, EU AI Act,
    NIST AI RMF, UN instruments).
  - MODULE 2 sources (practical): how to actually implement it — toolkits and
    mechanisms (e.g. CDEI bias review, ICO/Turing explainability guidance,
    algorithmic impact assessments, model cards, OECD tools catalogue).

{dimension_definition}

{national_context}
WORK THROUGH THE TWO SECTIONS IN ORDER. Keep the reasoning separate.

════════════════════════════════════════════════════════════════════
SECTION 1 — GOVERNANCE DIMENSION EVALUATION (MODULE 1)
════════════════════════════════════════════════════════════════════
Evaluate what the uploaded document says about this dimension, using the
[UPLOADED DOCUMENT] chunks as primary evidence and the [MODULE 1] chunks as
the normative benchmark.

1. coverage: "Covered" | "Partial" | "Missing". Judge by semantic substance,
   not by exact terminology, and do NOT require the policy to use the same
   vocabulary as the reference frameworks — the frameworks are the benchmark
   for interpreting the policy, not a keyword checklist. Recognise
   FUNCTIONALLY EQUIVALENT mechanisms expressed in the policy's own words: a
   provision that serves the dimension's purpose counts even when it never
   uses the framework's terms (e.g. an advance-notification or labelling duty
   for transparency, a confidentiality or secrecy duty for privacy, a manual
   review or non-automated handling right for human oversight, an
   energy-efficient or green data-centre provision for environmental
   sustainability). If ANY dimension-relevant provision or mechanism exists
   but is incomplete, classify "Partial" — not "Missing". Only classify
   "Missing" when, after considering equivalent terminology, the document
   contains NO provision serving the dimension's purpose. If a mechanism
   exists but lacks operational detail, keep the mechanism (list it in
   operational_mechanisms) and let the maturity assessment reflect the
   detail gap — do not erase the mechanism by declaring the dimension
   Missing. A strategy that sets direction on the topic is Covered even
   without a dedicated section.

   PROCEDURAL AUTHORITY IS NOT A GOVERNANCE MECHANISM: a provision that
   merely assigns a minister, ministry, agency, or other body a power to
   approve, support, fund, administer, or announce something is NOT by
   itself a governance mechanism for the dimension unless the provision
   actually establishes a requirement that governs the dimension's content.
   Example: "the Minister may approve or support AI data centres" is NOT
   an Environmental Sustainability mechanism — it imposes no energy,
   carbon, or e-waste requirement. Only count such a provision if it
   imposes a dimension-specific obligation (e.g. data centres must report
   energy consumption, obtain consent for data, test for bias). A bare
   procedural power, like a passing principle mention, does not elevate the
   dimension beyond the level its substantive requirements justify.
2. gap_detected: true when coverage is Partial or Missing.
3. reason_flagged: the single most important reason the dimension was
   flagged, written for a POLICYMAKER READER — plain language, no internal
   process vocabulary ("ladder", "R1/R2", "deterministic check", "Level N",
   "coverage rule"). Say what is actually missing in the document itself
   (e.g. "No body is named to receive or act on AI incident reports" — not
   "Rule R1 floor not satisfied"). (For Covered coverage this is usually
   empty — nothing was flagged.)
4. coverage_reasoning: explain the coverage decision IN PLAIN LANGUAGE, and
   NAME THE ACTUAL SPECIFICS from the uploaded document — the real article/
   section number, the real name of any body/ministry/agency, the real
   title of any named programme or instrument. Never write a generic
   sentence that could describe any country's policy ("the document touches
   on this dimension but lacks detail") — write the sentence so a reader who
   has never seen the document understands exactly what IS and ISN'T there
   (e.g. "Article 12 requires the Ministry of Digital Affairs to publish an
   annual AI transparency report, but no provision gives affected
   individuals a right to an explanation of a specific automated decision.").
   Never reference internal process concepts (ladder rules, levels,
   thresholds) — only the document's own content. Write it as natural
   analytical prose, not a rote checklist of "body: X, law: Y, policy: Z" —
   name the specifics because they make the sentence clear, not for their
   own sake. (For Covered coverage this is usually empty; use
   coverage_example instead.)
5. coverage_example: ONLY when coverage is "Covered" — give 2-3 concrete
   examples from the UPLOADED DOCUMENT that led to the Covered conclusion.
   EACH EXAMPLE MUST NAME THE ACTUAL SPECIFIC THING: the real name of the
   governance body/ministry/authority the document establishes or assigns,
   the real title of the policy/programme/instrument, or the real article/
   section that imposes the requirement. NEVER write a generic, could-apply-
   to-any-country sentence like "the document establishes a governance body
   and reporting requirements" — write "the document establishes the
   National AI Safety Board (Section 14) and requires it to publish
   quarterly compliance reports." If the document does not name something
   specific enough to cite by name, describe the actual mechanism in the
   document's own words rather than a generic label. Write these as natural
   prose, not a rote "body: X, law: Y" listing — the name earns its place
   because it makes the example concrete, not as a box-ticking exercise.
   These are theoretical/substantive examples drawn from the document's
   content (not verbatim citations). When coverage is Partial or Missing,
   return "".
6. principle_acknowledged: true if the document acknowledges the dimension's
   principle even in passing (relevant to maturity computation).
7. operational_mechanisms: list concrete operational mechanisms the document
   actually specifies — a NAMED BODY (commission/board/authority/agency/
   ministry/council/office), a REPORTING REQUIREMENT (annual report, registry,
   register, disclosure), or an ENFORCEMENT/REDRESS mechanism (grievance
   process, sanctions, audit, oversight, monitoring). Recognise mechanisms
   expressed in the policy's own terminology: a duty phrased as "shall",
   "must", "is required to", or "prohibits" IS a mechanism. If a mechanism
   exists but lacks operational detail, list it anyway — the maturity and
   gap reasoning reflect the detail gap, the mechanism is not erased. If the
   document only names the principle without any mechanism, return [].
8. document_evidence: citations supporting the evaluation FROM THE UPLOADED
   DOCUMENT ONLY.
9. framework_evidence: citations FROM MODULE 1 SOURCES establishing the
   normative requirement — even when coverage is Missing, cite the specific
   framework text that establishes the requirement being unmet.

CITATION RULES (MANDATORY):
- Every field above requires a real citation. Even when coverage is "Missing",
  cite the specific framework text that establishes the requirement being unmet.
- Cite ONLY the REAL chunk ids shown in the provided context. Each context line
  carries its real id after 'chunk_id=' (e.g. a line reads
  "[DOC-1] chunk_id=9f3a… Source: …" — the value after 'chunk_id=' is the id to
  cite, NOT the display label like DOC-1). Copy that real id exactly.
- Never invent a chunk id. If no context line supports your claim, set
  chunk_id to "insufficient evidence for citation".
- Quote the passage VERBATIM from the chunk. If you cannot find a specific
  supporting passage, state "insufficient evidence for citation" rather than
  constructing a plausible-sounding one.

════════════════════════════════════════════════════════════════════
SECTION 2 — RECOMMENDATIONS & ALIGNMENT (MODULE 2)
════════════════════════════════════════════════════════════════════
Now derive what should be done about it, grounded in the [MODULE 2] practical
sources. Do not re-assess coverage here; use the Section 1 verdict as input.

Use your Section 1 coverage verdict to select EXACTLY ONE of these branches.
Do not mix them: a Covered dimension gets the Best Practices branch; a
Partial or Missing dimension gets the Recommendations branch.

──── BRANCH A — coverage is "Covered" (no critical gaps) ────
The policy already aligns strongly with international expectations. Do NOT
write gap-closing recommendations and do NOT set a priority.
1. recommendations: return [] (empty list).
2. priority: return "" (empty string).
3. future_strengthening_opportunities: 2-3 strengthening opportunities for
   future revisions phrased as "may further strengthen" — refinements, not
   fixes. (Do NOT frame them as optional: to governments, "optional" reads as
   "ignore".) EACH ONE MUST NAME THE SPECIFIC EXISTING MECHANISM in THIS
   document it builds on (the real body/report/programme name) AND the
   specific practical toolkit step from the MODULE 2 sources it would add.
   FORBIDDEN: a generic sentence that could be pasted into any country's
   report unchanged (e.g. "Consider adopting international best practices
   for transparency" is FORBIDDEN — instead write "Extend the National AI
   Council's existing annual transparency report (established under
   Section 9) to include model cards, per the Model Cards for Model
   Reporting practice.").
4. international_examples: 2-3 REAL, CITED practices from other countries or
   governance frameworks that exemplify this dimension well. Each MUST carry
   a real chunk_id from the provided context and a brief quote — never invent
   a country practice or a chunk id. For EACH example, also write one
   sentence in "alignment" stating how it relates to what THIS document
   already does for this dimension — the same underlying approach, a more
   advanced version of a mechanism the document already has, or a
   complementary practice the document's own mechanism could adopt next.
   Never describe the example in isolation from the document.
5. international_standard_reference: the standard/practice the enhancements
   align to, naming the source.
6. framework_synthesis: an OBJECT with three labeled fields — consensus,
   differences, overall_assessment. NOT a per-framework summary ("NIST says...
   UNESCO says... CDEI says..." is summarization and is FORBIDDEN). Write:
   - consensus: ONE sentence stating what the relevant international
     frameworks collectively require for this dimension (e.g. "All three
     frameworks require mandatory transparency obligations.").
   - differences: describe how the international frameworks differ from
     EACH OTHER **and** from what the UPLOADED DOCUMENT itself does — name
     the document's actual mechanism/body next to the frameworks' approach,
     and explain why the different approaches still both work for this
     dimension (e.g. "UNESCO frames this as a rights obligation and NIST as
     an operational transparency requirement; the uploaded policy takes a
     third route — its National AI Council publishes model-level disclosure
     reports rather than individual explanation rights, which satisfies the
     same underlying transparency goal through institutional reporting
     instead of individual recourse."). Never leave the document out of this
     field — a differences passage that only compares frameworks to each
     other is incomplete. Write it as one flowing analytical passage, not a
     rote "framework: X, document: Y" listing.
   - overall_assessment: the verdict on how the uploaded policy aligns with
     those requirements. For this branch it is a COMPLIANCE JUSTIFICATION,
     not a recommendation. It must explain how the policy ALREADY satisfies the international expectations
     for this dimension: (a) name each relevant
     normative principle, (b) cite the specific provisions,
     mechanisms, or commitments the UPLOADED DOCUMENT already contains that
     satisfy it (draw on coverage_example and the document evidence), and
     (c) state why that existing provision meets the requirement. Use
     present tense throughout. FORBIDDEN in a Covered synthesis: gap-filling
     or future-tense language such as "should", "would", "will", "needs
     to", "recommend", "adopt", "introduce", "establish a", "implement X
     to", "translate ... into", "close the gap", "in order to". If you
     CANNOT ground a compliance claim in the document's own provisions, do
     NOT write recommendation-style prose as a substitute — state plainly
     which principle the document does not substantively satisfy (that
     honesty flag signals the Coverage label may be over-stated and will be
     surfaced for review).
7. standard_citations: real citations FROM MODULE 2 SOURCES grounding the
   future strengthening opportunities and international examples.

──── BRANCH B — coverage is "Partial" or "Missing" (gap exists) ────
1. recommendations: 3-6 concrete, implementable actions. EACH ONE MUST NAME
   THE SPECIFIC EXISTING MECHANISM in the uploaded document it builds on —
   WHENEVER the document has any related mechanism to build on, even a
   partial or adjacent one — creating a brand-new mechanism from scratch is
   the LAST resort, only when nothing in the document relates. Also
   identify WHICH practical toolkit/step (from Module 2 sources) it
   operationalises.
   VARY THE ANCHOR, don't default to "Article N" every time — a document's
   mechanism can be named by its INSTITUTION ("the Safety Research
   Institute's existing testing mandate"), its PROGRAMME/INSTRUMENT ("the
   national AI certification scheme"), its PROCESS ("the pre-deployment
   registration step"), or its provision number when that really is the
   clearest handle. Across the 3-6 recommendations, lead with a mix of
   these — not the same "Article N" pattern repeated in every sentence,
   even when the document is a numbered legal text. Vary phrasing overall
   too. FORBIDDEN: generic advice with no document-specific anchor at all
   (e.g. "Establish a bias-testing framework" is FORBIDDEN on its own —
   instead anchor it: "Task the existing Standards Committee with adding
   the bias-testing results the CDEI review recommends to its current
   registration review." or "Extend the Ministry's registration duty
   (Art. 7) to also require those results at the point of registration.").
   INSTITUTION DISCIPLINE: when an action names a specific institution
   (ministry, board, standards body, office), that institution must be
   EXPLICITLY assigned that responsibility in the uploaded policy. If the
   policy names the institution only generally (e.g. a nodal ministry, a
   standards committee) without assigning this specific duty, do not assert
   the responsibility — phrase the action generically ("a designated
   standards body", "the ministry the policy designates for compliance
   schedules") or name the institution only as the body to be tasked. This
   keeps recommendations consistent with the implementation roadmap's
   responsible-agency verdict, which is grounded in the same rule.
2. priority: one of "Critical" | "High" | "Medium" | "Low" for the
   dimension as a whole. (Note: for Missing coverage, write the reasoning
   with explicit urgency — this is a governance gap that needs closing.)
3. future_strengthening_opportunities: return [] (empty list).
4. international_examples: return [] (empty list).
5. international_standard_reference: the specific standard/practice the
   recommendation aligns to (e.g. an OECD tool, an impact assessment template,
   a bias-audit method, a model-card practice), naming the source.
6. framework_synthesis: an OBJECT with three labeled fields — consensus,
   differences, overall_assessment. NOT a per-framework summary ("NIST says...
   UNESCO says... CDEI says..." is summarization and is FORBIDDEN). Write:
   - consensus: ONE sentence stating what the relevant international
     frameworks collectively require for this dimension (e.g. "All three
     frameworks require mandatory transparency obligations.").
   - differences: describe how the international frameworks differ from
     EACH OTHER **and**, specifically, how the uploaded document's current
     approach (name its actual mechanism, or its actual absence) falls
     short against those different approaches — this is where the GAP shows
     up, not just a framework comparison (e.g. "UNESCO frames oversight as a
     rights obligation, NIST as an operational requirement; the uploaded
     policy has neither — it acknowledges human oversight in principle
     (Section 4) but assigns no body and no review process, so it satisfies
     neither framework's minimum bar."). Never write a differences passage
     that only compares frameworks to each other — it must say where the
     document sits relative to them. Write it as one flowing analytical
     passage, not a rote "framework: X, document: Y" listing.
   - overall_assessment: the verdict on how the uploaded policy aligns,
     synthesising the Module 2 practical mechanism against what the Module 1
     normative principle requires. Example: "The OECD AI Principles require
     accountability for AI outcomes; the CDEI bias review operationalises
     this through algorithmic impact assessments before deployment. Adopting
     a mandatory algorithmic impact assessment before high-impact
     deployments would translate the normative commitment into a concrete
     reporting obligation, while model cards would close the transparency
     gap for citizens affected by automated decisions."
7. standard_citations: citations FROM MODULE 2 SOURCES grounding the
   recommendations and the international standard reference.

════════════════════════════════════════════════════════════════════
OUTPUT — return ONLY valid JSON with EXACTLY this shape:
{
  "dimension": "{dimension}",
  "coverage": "Covered",
  "gap_detected": false,
  "reason_flagged": "",
  "coverage_reasoning": "",
  "coverage_example": "The document establishes a National AI Ethics Board and mandates annual explainability reporting for high-risk systems...",
  "principle_acknowledged": true,
  "operational_mechanisms": ["National AI Council (named body)", "Annual transparency reporting"],
  "document_evidence": [{"chunk_id": "9f3a2b...", "quote": "verbatim passage", "page_number": 12}],
  "framework_evidence": [{"chunk_id": "c81d07...", "quote": "verbatim passage", "page_number": 4}],
  "recommendations": [],
  "priority": "",
  "future_strengthening_opportunities": ["Extend the existing annual transparency report to include model-level cards"],
  "international_examples": [{"practice": "Mandatory algorithmic impact assessment before high-impact deployments", "country_or_source": "adopting jurisdiction", "chunk_id": "b5e9c1...", "quote": "verbatim passage", "page_number": 8}],
  "international_standard_reference": "OECD Catalogue of Tools and Metrics for Trustworthy AI",
  "framework_synthesis": {
    "consensus": "All three frameworks require mandatory transparency obligations.",
    "differences": "UNESCO focuses on rights; NIST focuses on operational transparency; CDEI focuses on public-sector implementation.",
    "overall_assessment": "...one paragraph judging alignment..."
  },
  "standard_citations": [{"chunk_id": "b5e9c1...", "quote": "verbatim passage", "page_number": 8}]
}

Example of a well-formed framework_synthesis for BRANCH A (Covered —
compliance justification in present tense, grounded in the document):
{
  "consensus": "The UNESCO Recommendation and OECD AI Principles require human oversight of AI systems.",
  "differences": "UNESCO frames this as a rights obligation; the OECD operationalises it through risk-based system expectations.",
  "overall_assessment": "The UNESCO Recommendation requires human oversight of AI systems, and the policy satisfies this: it establishes a National AI Ethics Board with a formal human-in-the-loop review mandate for high-impact deployments, and it already mandates annual transparency reporting on automated decisions. These existing provisions give effect to the oversight principle at the institutional level, so the policy substantively meets the international expectation."
}

Example of a well-formed framework_synthesis for BRANCH B (Partial/Missing —
this recommendation style is ONLY correct when a gap exists):
{
  "consensus": "The UNESCO Recommendation requires human oversight of AI systems.",
  "differences": "UNESCO frames oversight as a human-rights obligation; the ICO/Turing explainability guidance operationalises it through layered explanations for different audiences.",
  "overall_assessment": "The uploaded policy aligns with UNESCO's oversight principle at a directional level but lacks the operational explanation mechanism. Mandating explanation statements at deployment — using the ICO's suggested format — would translate the normative human-autonomy commitment into a concrete, implementable reporting mechanism."
}

REMEMBER: Branch A (Covered) must NEVER use the Branch B recommendation
style — no "should/would/will", no "adopt/introduce/implement...". If the
document genuinely does not satisfy a principle, say so rather than
pretending compliance.

REMEMBER: never fabricate citations. If no supporting passage exists for a
claim, use "insufficient evidence for citation". Return JSON only.
"""


# ── Module 3 + Module 4 — Combined conditional second-call prompt ────────
# Fired ONLY for Partial/Missing dimensions (code gate: Fully Covered
# dimensions never run this call). One combined call returns BOTH the
# Implementation Roadmap (Module 3) and the Case Intelligence write-up
# (Module 4) — same single-call discipline as Module 1+2. The Module 1+2
# verdict (coverage, gap reasoning, maturity) is passed forward as text
# context so this call addresses the ACTUAL gap instead of re-deriving it.
#
# Two highest-fabrication-risk fields get explicit no-fabrication rules:
#   - responsible_agency: grounded in an institution the uploaded document
#     names/implies, else explicitly "none identified" + generic role.
#   - incident matches: only from the provided module_4_incident context;
#     the model writes the write-up around a REAL curated incident, never
#     invents one. The code additionally re-grounds both (see gap_analyzer).

MODULE3_4_COMBINED_SYSTEM = """
You are a senior AI governance policy advisor producing the implementation
and case-intelligence sections for ONE governance dimension of a national
policy that has been assessed as having a governance gap.

{dimension_definition}

{dimension_verdict}

{national_context}
WORK THROUGH THE TWO MODULES IN ORDER. Keep the reasoning separate.

════════════════════════════════════════════════════════════════════
MODULE 3 — IMPLEMENTATION ROADMAP
════════════════════════════════════════════════════════════════════
Build a concrete, sequenced implementation roadmap that addresses the gap
described in the verdict above. Use the [MODULE 3] context lines as the
practical source of named mechanisms to adopt (pilot programmes,
management-system standards, reporting frameworks, algorithmic impact
assessments, assurance toolkits) — never generic "improve oversight" filler.1. phases: exactly TWO phases, each with:
   - phase: "Phase 1" / "Phase 2"
   - timeline: ALWAYS leave "" (empty). The implementation timeline is
     computed deterministically by the system from the coverage tier, the
     document's existing mechanisms, governance maturity, and the
     responsible-agency grounding. NEVER guess a duration — any value you
     invent will be overwritten.
   - objective: one sentence on what this phase accomplishes
   - steps: 2-5 SEQUENTIAL, concrete steps. Ground each step in a named
     mechanism from the [MODULE 3] context where possible (e.g. "adopt a
     mandatory algorithmic impact assessment process before high-impact
     deployments"), not "improve oversight".
2. responsible_agency: the institution that should own implementation.
   HARD RULE (no fabrication):
   - If the UPLOADED DOCUMENT names or clearly implies a relevant body
     (a ministry, council, board, authority, task force, or office), name
     that exact body and set responsible_agency_grounding to
     "document_named" (or "document_implied" if it is implied but not
     named).
   - If the document names NO relevant body, write EXACTLY: "Not specified
     by policy — implementation responsibility should be assigned by the
     adopting government." and set responsible_agency_grounding to
     "none_identified". Do NOT invent an agency name and do NOT recommend
     creating a specific new office.
   - NEVER invent a plausible-sounding agency name that is not in the
     document.
   - Any BODIES NAMED IN THE DOCUMENT list below is drawn verbatim from
     passages about this dimension. Copy a name from it exactly if that body
     genuinely carries responsibility here. Appearing in the list is NOT
     evidence of responsibility — a privacy regulator mentioned in an
     inclusivity passage is still the privacy regulator — so choose
     "none_identified" over a body whose remit does not cover this dimension.
3. documentation_requirements: 2-4 concrete record-keeping/reporting
   requirements (e.g. registry, annual transparency report, audit trail).
4. monitoring_checklist: 3-6 concrete, checkable compliance items.

════════════════════════════════════════════════════════════════════
MODULE 4 — CASE INTELLIGENCE
════════════════════════════════════════════════════════════════════
Consider the [MODULE 4 — INCIDENT RECORDS] context lines. These are REAL,
curated AI incidents. Determine whether any is genuinely relevant to this
dimension's gap.

HARD RULES:
- You may ONLY reference incidents present in the [MODULE 4] context. Never
  invent an incident, a country case, or a headline.
- If an incident is only loosely related, DO NOT force a match — return
  incident_matches: [] and matched: false.
- For each matched incident, write the write-up as an explicit COMPARISON
  between what happened in the real incident and THIS document's actual
  gap — using the SAME four fields below, no new section:
    - dimension_relevance: state what mechanism failed or was absent in the
      real incident, in one sentence.
    - potential_consequence: state, specifically, why the SAME failure mode
      is plausible under the uploaded document AS IT CURRENTLY STANDS —
      name the document's actual gap (the missing body, missing review
      step, missing reporting duty — whatever this dimension's
      coverage_reasoning identified) and connect it directly to the
      incident's failure mode. Do not write a generic risk statement; write
      "because the document does not [specific gap], the same kind of
      [specific incident failure] could occur here."
    - lessons_learned: the concrete lesson from the real incident.
    - mitigation: the concrete step that would close the specific gap named
      in potential_consequence — tie it back to the roadmap phases above
      where possible.
  cite the real incident's chunk_id.
- If NO genuinely relevant incident exists in the provided context, return
  incident_matches: [] (do NOT lower the relevance bar to fill the section).

════════════════════════════════════════════════════════════════════
OUTPUT — return ONLY valid JSON with EXACTLY this shape:
{
  "dimension": "{dimension}",
  "phases": [
    {"phase": "Phase 1", "timeline": "", "objective": "Establish the foundational mechanism", "steps": ["step 1", "step 2"]},
    {"phase": "Phase 2", "timeline": "", "objective": "Operationalise and monitor", "steps": ["step 1", "step 2"]}
  ],
  "responsible_agency": "Ministry of Digital Affairs",
  "responsible_agency_grounding": "document_named",
  "documentation_requirements": ["req 1"],
  "monitoring_checklist": ["item 1"],
  "implementation_citations": [{"chunk_id": "9f3a2b...", "quote": "verbatim passage", "page_number": 4}],
  "incident_matches": [
    {"incident_name": "...", "source": "...", "dimension_relevance": "...", "potential_consequence": "...", "lessons_learned": "...", "mitigation": "...", "chunk_id": "c81d07...", "quote": "verbatim passage", "page_number": 2}
  ],
  "matched": true
}

CITATION RULES (MANDATORY):
- Cite ONLY the REAL chunk ids shown in the provided context (the value
  after 'chunk_id='), never the display label (IMPL-1 / INC-1).
- implementation_citations must cite passages SUBSTANTIVELY ABOUT
  {dimension} — never generic process boilerplate that could apply to any
  dimension (a generic risk-assessment or privacy-impact template is not
  evidence for Environmental Sustainability). Prefer the [MODULE 3]
  implementation-source lines; if a [UPLOADED DOCUMENT] line (DOC-n)
  contains a more dimension-specific passage (e.g. the policy's own
  environmental-responsibility provisions), cite that DOC-n line instead.
  incident chunk_id / quote come FROM [MODULE 4] lines.
- Never invent a chunk id. If no context line supports a claim, use
  "insufficient evidence for citation".

REMEMBER: no fabricated agencies, no invented incidents, no fabricated
citations. Return JSON only.
"""


def build_module3_4_combined_prompt(
    dimension: str,
    dimension_definition: str,
    dimension_verdict: str,
    module3_chunks: list[dict[str, Any]],
    module4_chunks: list[dict[str, Any]],
    document_chunks: list[dict[str, Any]],
    country: str = "",
    candidate_bodies: list[str] | None = None,
) -> tuple[str, str]:
    """Build the combined Module 3 + Module 4 prompt for one dimension.

    `candidate_bodies` are institutions the DOCUMENT names in passages about
    this dimension, extracted deterministically. Without them the model is
    asked to name a responsible body while seeing only two document chunks,
    and honestly answers "none_identified" for documents that do name one —
    see document_named_bodies.

    `dimension_verdict` is the carried-forward Module 1+2 result text (coverage,
    gap reasoning, maturity, recommendations) so this call addresses the actual
    gap rather than re-deriving it. `document_chunks` are included so the
    responsible-agency rule can be grounded in what the document actually names.
    `country` drives the same deterministic national-context block as Module 1+2
    so the roadmap never recommends adopting the country's own mechanisms.
    """
    system_prompt = (
        MODULE3_4_COMBINED_SYSTEM
        .replace("{dimension_definition}", dimension_definition)
        .replace("{dimension_verdict}", dimension_verdict)
        .replace("{dimension}", dimension)
        .replace("{national_context}", _national_context_block(country))
    )

    def fmt_chunk(idx: int, prefix: str, chunk: dict[str, Any]) -> str:
        text = chunk.get("text", "") or ""
        src = chunk.get("source_framework", "") or ""
        doc_name = chunk.get("document_name", "") or ""
        page = chunk.get("page_number")
        real_id = chunk.get("chunk_id", "") or ""
        page_str = f" (p.{page})" if page is not None else ""
        id_str = f" chunk_id={real_id}" if real_id else ""
        # Label precedence: the framework name (src) wins over document_name,
        # because ingest_document sets document_name for EVERY file including
        # framework PDFs (falling back to the raw PDF filename) — preferring
        # document_name would leak "OECD_Catalogue_...pdf" as the Source label
        # for framework chunks after the next framework sync. Uploaded-document
        # chunks have source_framework == "" so they fall through to their
        # document_name.
        source_label = src or doc_name or "Uploaded Document"
        return (
            f"[{prefix}-{idx}]{id_str}{page_str} Source: {source_label}\n{text}"
        )

    parts: list[str] = []
    parts.append(f"Dimension: {dimension}")
    parts.append("")

    parts.append("═══ [MODULE 3 — IMPLEMENTATION SOURCES] ═══")
    if module3_chunks:
        parts.extend(fmt_chunk(i, "IMPL", c) for i, c in enumerate(module3_chunks, 1))
    else:
        parts.append("(no Module 3 implementation chunks retrieved)")

    parts.append("")
    parts.append("═══ [MODULE 4 — INCIDENT RECORDS] ═══")
    if module4_chunks:
        parts.extend(fmt_chunk(i, "INC", c) for i, c in enumerate(module4_chunks, 1))
    else:
        parts.append("(no curated incident records retrieved)")

    parts.append("")
    parts.append("═══ [UPLOADED DOCUMENT — for responsible-agency grounding] ═══")
    if document_chunks:
        parts.extend(fmt_chunk(i, "DOC", c) for i, c in enumerate(document_chunks, 1))
    else:
        parts.append("(no document chunks retrieved)")

    parts.append("")
    parts.append(
        "Proceed through Module 3 then Module 4. Return the JSON object exactly "
        "as specified in the system prompt. For every citation, output the REAL "
        "chunk_id shown after 'chunk_id=' in the context — never the label like "
        "IMPL-1. If you cannot match a passage to a context line, use "
        "'insufficient evidence for citation'. Never invent an agency, an "
        "incident, or a chunk id."
    )

    return system_prompt, "\n\n".join(parts)


def _national_context_block(country: str = "") -> str:
    """Deterministic country-context instruction for the Module 1+2 and 3+4 prompts.

    Only fires for countries where the pipeline KNOWS specific governance
    infrastructure is domestic and already-operational (currently Singapore:
    AI Verify / AI Verify Foundation co-published the Model AI Governance
    Framework and run AI Verify as government-co-created infrastructure).
    For every other country this returns "" and AI Verify stays an external
    framework a country would adopt — never an LLM judgment, always a
    backend decision driven by the workspace country.
    """
    if not country or country.strip().lower() != "singapore":
        return ""
    return (
        "NATIONAL CONTEXT (Singapore):\n"
        "AI Verify and the AI Verify Foundation are DOMESTIC, "
        "government-co-created infrastructure already operational in Singapore "
        "(IMDA / AI Verify Foundation, Model AI Governance Framework for "
        "Generative AI, May 2024). When referencing AI Verify, the AI Verify "
        "Foundation, or the Model AI Governance Framework in this analysis, "
        "treat them as already-operational national mechanisms, NOT as external "
        "frameworks Singapore should adopt. For Module 2, recognise them as "
        "existing strengths where the uploaded document(s) evidence them. For "
        "Module 3, never recommend that Singapore 'adopt' or 'import' AI Verify "
        "— build on it as an existing asset.\n\n"
    )


# The evidence headers carry chunk ids, and "cite only numbers that literally
# appear above" reads as permission to cite one. India's Human Autonomy verdict
# shipped "in Section 3081a297-54ab-4efd-9c8c-492521016736" three times over.
_CHUNK_ID_PROHIBITION = (
    "The bracketed chunk identifiers in the evidence headers are retrieval "
    "bookkeeping, not provisions — never cite one as a Section, Article or "
    "Part."
)


def _citation_instruction(division_vocabulary: list[str] | None) -> str:
    """Tell the model to use the DOCUMENT's numbering words, not ours.

    This instruction used to read "Cite ONLY article, section or recital
    numbers...". That enumerates a closed vocabulary drawn from EU statutory
    drafting, and most instruments this tool reads are not drafted that way.
    Japan's AI Guidelines for Business organises itself into Parts — the word
    "Section" appears in it zero times. Handed a document full of Parts and an
    instruction permitting only article/section/recital, the model mapped
    Part 4 onto the nearest allowed word and wrote "Section 4".

    That reads as a fabricated citation and gets flagged as one, but the model
    was doing what it was told; the substance of the claim was correct and the
    surrounding references (P-7, P-4, U-6, U-7) were all real. The instruction
    was wrong, not the answer.

    So: name the forms the document actually uses when they are known, and
    otherwise tell the model to mirror the document rather than pick from a
    list.
    """
    if division_vocabulary:
        forms = ", ".join(f'"{v} N"' for v in division_vocabulary)
        return (
            "This document numbers its divisions as "
            f"{forms} — use that exact wording when you cite one. Do NOT "
            "translate it into another scheme (do not write \"Section\" for a "
            "document organised into Parts). Cite ONLY numbers that literally "
            "appear in the passages above; if you cannot see the number there, "
            "describe the provision without numbering it. "
            + _CHUNK_ID_PROHIBITION
        )
    return (
        "When you cite a numbered division, copy the document's own wording "
        "for it verbatim (Part, Chapter, Article, Section, Clause — whichever "
        "the text itself uses) and never substitute a different scheme. Cite "
        "ONLY numbers that literally appear in the passages above; if you "
        "cannot see the number there, describe the provision without "
        "numbering it. " + _CHUNK_ID_PROHIBITION
    )


def build_module1_2_combined_prompt(
    dimension: str,
    dimension_definition: str,
    document_chunks: list[dict[str, Any]],
    module1_chunks: list[dict[str, Any]],
    module2_chunks: list[dict[str, Any]],
    country: str = "",
    determined_verdict: dict[str, Any] | None = None,
    division_vocabulary: list[str] | None = None,
) -> tuple[str, str]:
    """Build the single combined Module 1 + Module 2 prompt for one dimension.

    `division_vocabulary` names how THIS document numbers its own internal
    divisions ("Part" for Japan's AI Guidelines, "Article" for the EU AI Act),
    detected from the document text. See the citation instruction below for
    why prescribing a fixed vocabulary instead was actively harmful.

    `country` (the workspace country, set at workspace creation — never an LLM
    guess) drives a deterministic national-context block so the model knows
    which mechanisms are DOMESTIC and already-operational for the analysed
    country (e.g. Singapore's AI Verify / AI Verify Foundation) versus external
    frameworks a country would adopt. Keeps Module 2 synthesis from telling a
    country to "adopt" its own already-running infrastructure.
    """
    # NOTE: use .replace(), NOT .format() — the prompt contains a literal JSON
    # output example with raw braces that would break str.format().
    system_prompt = (
        MODULE1_2_COMBINED_SYSTEM
        .replace("{dimension_definition}", dimension_definition)
        .replace("{dimension}", dimension)
        .replace("{national_context}", _national_context_block(country))
    )

    def fmt_chunk(idx: int, prefix: str, chunk: dict[str, Any]) -> str:
        text = chunk.get("text", "") or ""
        src = chunk.get("source_framework", "") or ""
        # Multi-document workspaces: name the actual source document for
        # [UPLOADED DOCUMENT] chunks so findings can be traced to NAIS vs the
        # Model AI Governance Framework (or any other uploaded document).
        doc_name = chunk.get("document_name", "") or ""
        page = chunk.get("page_number")
        real_id = chunk.get("chunk_id", "") or ""
        page_str = f" (p.{page})" if page is not None else ""
        id_str = f" chunk_id={real_id}" if real_id else ""
        # Label precedence: the framework name (src) wins over document_name,
        # because ingest_document sets document_name for EVERY file including
        # framework PDFs (falling back to the raw PDF filename) — preferring
        # document_name would leak "OECD_Catalogue_...pdf" as the Source label
        # for framework chunks after the next framework sync. Uploaded-document
        # chunks have source_framework == "" so they fall through to their
        # document_name.
        source_label = src or doc_name or "Uploaded Document"
        return (
            f"[{prefix}-{idx}]{id_str}{page_str} Source: {source_label}\n{text}"
        )

    parts: list[str] = []
    parts.append(f"Dimension: {dimension}")
    parts.append("")

    # The coverage and maturity verdict is decided BEFORE this call, from the
    # document's own provisions (see _compute_deterministic_verdict). It is
    # given to the model as a FIXED INPUT to explain, not a judgment to make.
    # Previously the model formed its own verdict, wrote prose justifying it,
    # and then had the verdict replaced downstream — which is why reports
    # carried gap language underneath a Covered result and recommendations
    # aimed at a different conclusion than the one shown.
    if determined_verdict:
        parts.append("═══ [DETERMINED VERDICT — EXPLAIN THIS, DO NOT RE-JUDGE] ═══")
        parts.append(f"Coverage: {determined_verdict.get('coverage_label')}")
        parts.append(f"Governance maturity: {determined_verdict.get('maturity_label')}")
        basis = determined_verdict.get("basis")
        if basis:
            parts.append(f"Basis: {basis}")
        missing = determined_verdict.get("missing_mechanisms") or []
        if missing:
            parts.append(
                "Governance mechanisms the reference frameworks expect that this "
                "document does NOT provide: " + ", ".join(missing)
            )
        present = determined_verdict.get("present_mechanisms") or []
        if present:
            parts.append(
                "Mechanisms the document DOES provide: " + ", ".join(present)
            )
        n_bind = determined_verdict.get("binding_provisions")
        n_enf = determined_verdict.get("enforceable_provisions")
        if n_bind is not None:
            parts.append(
                f"Measured instrument character: {n_bind} binding provision(s), "
                f"{n_enf} backed by enforcement or supervision."
            )
            if not n_bind:
                parts.append(
                    "This document imposes NO binding duty for this dimension. "
                    "Describe it accordingly — say it 'recommends', 'expects' or "
                    "'calls on' actors. Do NOT write that it 'mandates', "
                    "'requires', 'obliges' or 'enforces' anything."
                )
            elif not n_enf:
                parts.append(
                    "This document creates duties but attaches NO penalty, audit "
                    "or supervisory consequence for this dimension. Do not "
                    "describe it as 'enforced'."
                )
        parts.append(
            "This verdict is our computed reading of the document, shown to you "
            "as a REFERENCE. If you believe it is wrong — for example we missed "
            "a provision, or misread a passage's force — put your objection in "
            "the 'verdict_challenge' field: name the specific provision and say "
            "what coverage you would assign instead. Leave it empty if you agree. "
            "Your challenge is recorded for review; it does not change the "
            "reported result, so still write the fields below consistently with "
            "the Coverage value above."
        )
        parts.append(
            "Write coverage_reasoning and reason_flagged so they are consistent "
            "with the Coverage value above, citing the document's actual "
            "provisions. Do not argue for a different coverage level. Target "
            "recommendations at the mechanisms listed as not provided. "
            + _citation_instruction(division_vocabulary)
        )
        parts.append("")

    parts.append("═══ [UPLOADED DOCUMENT] — primary evidence ═══")
    if document_chunks:
        parts.extend(fmt_chunk(i, "DOC", c) for i, c in enumerate(document_chunks, 1))
    else:
        parts.append("(no document chunks retrieved for this dimension)")

    parts.append("")
    parts.append("═══ [MODULE 1 — NORMATIVE REQUIREMENTS] ═══")
    if module1_chunks:
        parts.extend(fmt_chunk(i, "NORM", c) for i, c in enumerate(module1_chunks, 1))
    else:
        parts.append("(no Module 1 normative chunks retrieved)")

    parts.append("")
    parts.append("═══ [MODULE 2 — PRACTICAL TOOLKITS & MECHANISMS] ═══")
    if module2_chunks:
        parts.extend(fmt_chunk(i, "PRAC", c) for i, c in enumerate(module2_chunks, 1))
    else:
        parts.append("(no Module 2 practical chunks retrieved)")

    parts.append("")
    parts.append(
        "Proceed through Section 1 then Section 2. Return the JSON object exactly "
        "as specified in the system prompt. For every citation, output the REAL "
        "chunk_id shown after 'chunk_id=' in the context (e.g. the value after "
        "'chunk_id=' on the [NORM-1] line) — never output the label like NORM-1. "
        "If you cannot match a passage to a context line, use 'insufficient evidence "
        "for citation'."
    )

    return system_prompt, "\n\n".join(parts)


def build_recommendation_and_final_prompt(
    dimension: str,
    evidence_interpretation: dict[str, Any],
    maturity_result: dict[str, Any],
    framework_synthesis: dict[str, Any],
    plausibility_result: dict[str, Any],
    dimension_definition: str,
    evidence_quotes: list[str] | None = None,
) -> tuple[str, str]:
    validated_level = plausibility_result.get("validated_maturity_level",
                                               maturity_result.get("maturity_level", 0))
    validated_coverage = plausibility_result.get("validated_coverage",
                                                  maturity_result.get("coverage", "Missing"))
    confidence = plausibility_result.get("confidence_in_assessment", "Medium")

    fm = framework_synthesis or {}
    existing = fm.get("existing_mechanisms", [])
    missing = fm.get("missing_mechanisms", [])
    synthesis_text = fm.get("synthesis", "")

    uncertainty_block = (
        "Evidence Strength Descriptors:\n"
        "Not Demonstrated — No evidence exists.\n"
        "Weakly Demonstrated — Indirectly touched.\n"
        "Implicitly Addressed — Reasonably inferred.\n"
        "Explicitly Addressed — Clearly stated.\n"
        "Strongly Operationalised — Implemented with specific processes and oversight."
    )

    system_prompt = RECOMMENDATION_AND_FINAL_SYSTEM.format(
        dimension_definition=dimension_definition,
        uncertainty_note=uncertainty_block,
    )

    prompt_lines = [
        f"Dimension: {dimension}",
        f"Validated Maturity: Level {validated_level}",
        f"Validated Coverage: {validated_coverage}",
        f"Confidence: {confidence}",
        "",
        "Evidence Interpretation:",
        evidence_interpretation.get("interpretation_summary", ""),
        "",
        "Maturity Reasoning:",
        maturity_result.get("maturity_reasoning", ""),
        "",
        "Framework Synthesis:",
        synthesis_text,
        "",
    ]
    if existing:
        prompt_lines.append(f"Existing Policy Mechanisms: {'; '.join(existing[:5])}")
    if missing:
        prompt_lines.append(f"Missing Universal Mechanisms: {'; '.join(missing[:5])}")
    if evidence_quotes:
        quote_str = "\n".join(f'- "{q}"' for q in evidence_quotes[:3])
        prompt_lines.append(f"\nRelevant Evidence Quotes:\n{quote_str}")

    prompt_lines.append(
        "\nBefore writing, identify the smallest realistic improvement. "
        "Then generate recommendations that strengthen existing mechanisms first. "
        "Every recommendation must name the specific mechanism it extends. "
        "Output valid JSON only."
    )

    return system_prompt, "\n".join(prompt_lines)
