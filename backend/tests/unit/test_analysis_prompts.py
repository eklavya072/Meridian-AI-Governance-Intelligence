import pytest

from src.analysis_prompts import (
    DIMENSION_DEFINITIONS,
    INTEGRATED_MATURITY_FRAMEWORK,
    MODULE1_2_COMBINED_SYSTEM,
    MODULE3_4_COMBINED_SYSTEM,
    _national_context_block,
    build_dimension_definition_block,
    build_evidence_interpretation_prompt,
    build_maturity_assessment_prompt,
    build_module1_2_combined_prompt,
    build_module3_4_combined_prompt,
    build_recommendation_and_final_prompt,
    truncate,
)

ALL_DIMENSIONS = list(DIMENSION_DEFINITIONS.keys())


def make_ei_dict(overrides: dict | None = None) -> dict:
    base = {
        "dimension": "Transparency",
        "explicit_evidence": ["Section 3 requires explainability"],
        "implicit_evidence": ["Transparency may be inferred from reporting requirements"],
        "demonstrated_capability": "Policy requires AI system disclosure",
        "absent_capability": "No audit requirements found",
        "strong_evidence": ["Mandatory transparency reports"],
        "weak_evidence": ["General principles without mechanisms"],
        "contradictory_evidence": [],
        "evidence_strength": "Explicitly Addressed",
        "interpretation_summary": "Policy addresses transparency through disclosure requirements",
    }
    if overrides:
        base.update(overrides)
    return base


def make_maturity_dict(overrides: dict | None = None) -> dict:
    base = {
        "dimension": "Transparency",
        "maturity_level": 2,
        "maturity_label": "Governance Objectives Defined",
        "coverage": "Partial",
        "maturity_reasoning": "Policy defines transparency objectives but lacks mechanisms",
        "level_justification": "Section 3 establishes transparency principles",
        "uncertainty_flags": ["Scope of transparency undefined"],
        "false_negative_check": "All checks evaluated: alternative terminology checked, no embedded mechanisms found",
    }
    if overrides:
        base.update(overrides)
    return base


def make_fs_dict(overrides: dict | None = None) -> dict:
    base = {
        "universal_requirements": ["Disclosure requirements"],
        "framework_agreements": ["All frameworks require transparency"],
        "framework_differences": ["UNESCO emphasises explainability"],
        "existing_mechanisms": ["Disclosure requirements exist"],
        "missing_mechanisms": ["Audit requirements"],
        "framework_specific_requirements": {"UNESCO": ["Explainability"]},
        "implementation_maturity_comparison": {},
        "synthesis": "Policy meets baseline disclosure but lacks audit mechanisms",
    }
    if overrides:
        base.update(overrides)
    return base


def make_pr_dict(overrides: dict | None = None) -> dict:
    base = {
        "validated_maturity_level": 2,
        "validated_coverage": "Partial",
        "confidence_in_assessment": "Medium",
    }
    if overrides:
        base.update(overrides)
    return base


class TestTruncate:
    def test_short_text_unchanged(self):
        assert truncate("short", 100) == "short"

    def test_long_text_truncated(self):
        result = truncate("a" * 200, 100)
        assert len(result) == 103  # 100 + "..."
        assert result.endswith("...")

    def test_exact_length_not_truncated(self):
        text = "a" * 100
        assert truncate(text, 100) == text


class TestBuildDimensionDefinitionBlock:
    def test_known_dimension(self):
        block = build_dimension_definition_block("Transparency")
        assert "Dimension: Transparency" in block
        assert len(block) > 50

    def test_unknown_dimension(self):
        block = build_dimension_definition_block("Unknown")
        assert "Dimension: Unknown" in block
        assert "Principles related to Unknown" in block

    def test_all_defined_dimensions(self):
        for dim in ALL_DIMENSIONS:
            block = build_dimension_definition_block(dim)
            assert dim in block
            assert block.startswith(f"Dimension: {dim}")

    def test_environmental_sustainability(self):
        block = build_dimension_definition_block("Environmental Sustainability")
        assert "Energy efficiency" in block
        assert "Carbon footprint" in block


class TestBuildEvidenceInterpretationPrompt:
    def test_returns_tuple_of_two_strings(self):
        sys_p, prompt = build_evidence_interpretation_prompt(
            dimension="Privacy",
            document_excerpt="The policy requires data protection...",
            dimension_definition=build_dimension_definition_block("Privacy"),
        )
        assert isinstance(sys_p, str)
        assert isinstance(prompt, str)
        assert len(sys_p) > 100
        assert len(prompt) > 50

    def test_contains_dimension_name(self):
        sys_p, prompt = build_evidence_interpretation_prompt(
            dimension="Accountability",
            document_excerpt="some text",
            dimension_definition=build_dimension_definition_block("Accountability"),
        )
        assert "Accountability" in sys_p or "Accountability" in prompt

    def test_contains_interpretation_instruction(self):
        sys_p, prompt = build_evidence_interpretation_prompt(
            dimension="Safety",
            document_excerpt="some text",
            dimension_definition=build_dimension_definition_block("Safety"),
        )
        assert "Do not compare" in sys_p
        assert "interpretation_summary" in sys_p

    def test_document_excerpt_in_prompt(self):
        sys_p, prompt = build_evidence_interpretation_prompt(
            dimension="Fairness",
            document_excerpt="unique excerpt for testing",
            dimension_definition=build_dimension_definition_block("Fairness"),
        )
        assert "unique excerpt for testing" in prompt

    def test_empty_excerpt_handled(self):
        sys_p, prompt = build_evidence_interpretation_prompt(
            dimension="Inclusivity",
            document_excerpt="",
            dimension_definition=build_dimension_definition_block("Inclusivity"),
        )
        assert isinstance(prompt, str)

    def test_long_excerpt_truncated(self):
        long_text = "word " * 5000
        sys_p, prompt = build_evidence_interpretation_prompt(
            dimension="Privacy",
            document_excerpt=long_text,
            dimension_definition=build_dimension_definition_block("Privacy"),
        )
        assert len(prompt) < len(long_text)

    def test_output_json_instruction(self):
        sys_p, prompt = build_evidence_interpretation_prompt(
            dimension="Transparency",
            document_excerpt="text",
            dimension_definition=build_dimension_definition_block("Transparency"),
        )
        assert "Output JSON" in sys_p or "Output valid JSON" in prompt


class TestBuildMaturityAssessmentPrompt:
    def test_returns_tuple_of_two_strings(self):
        sys_p, prompt = build_maturity_assessment_prompt(
            dimension="Accountability",
            evidence_interpretation=make_ei_dict(),
            dimension_definition=build_dimension_definition_block("Accountability"),
        )
        assert isinstance(sys_p, str)
        assert isinstance(prompt, str)
        assert len(sys_p) > 200

    def test_contains_integrated_framework(self):
        sys_p, prompt = build_maturity_assessment_prompt(
            dimension="Privacy",
            evidence_interpretation=make_ei_dict(),
            dimension_definition=build_dimension_definition_block("Privacy"),
        )
        assert "Level 0" in sys_p
        assert "Level 5" in sys_p
        lower = sys_p.lower()
        assert "alternative terminology" in lower
        assert "embedded mechanisms" in lower
        assert "distributed implementation" in lower

    def test_evidence_interpretation_data_in_prompt(self):
        ei = make_ei_dict({"interpretation_summary": "custom summary for testing"})
        sys_p, prompt = build_maturity_assessment_prompt(
            dimension="Transparency",
            evidence_interpretation=ei,
            dimension_definition=build_dimension_definition_block("Transparency"),
        )
        assert "custom summary for testing" in prompt

    def test_missing_keys_handled_gracefully(self):
        sys_p, prompt = build_maturity_assessment_prompt(
            dimension="Human Autonomy",
            evidence_interpretation={},
            dimension_definition=build_dimension_definition_block("Human Autonomy"),
        )
        assert "None identified" in prompt

    def test_maturity_mapping_present(self):
        sys_p, prompt = build_maturity_assessment_prompt(
            dimension="Inclusivity",
            evidence_interpretation=make_ei_dict(),
            dimension_definition=build_dimension_definition_block("Inclusivity"),
        )
        assert "Level 0" in sys_p and "Level 5" in sys_p
        assert "Missing" in sys_p

    def test_output_json_instruction(self):
        sys_p, prompt = build_maturity_assessment_prompt(
            dimension="Safety",
            evidence_interpretation=make_ei_dict(),
            dimension_definition=build_dimension_definition_block("Safety"),
        )
        assert "Output JSON" in sys_p or "Output valid JSON" in prompt

    def test_maturity_trace_instruction(self):
        sys_p, prompt = build_maturity_assessment_prompt(
            dimension="Accountability",
            evidence_interpretation=make_ei_dict(),
            dimension_definition=build_dimension_definition_block("Accountability"),
        )
        assert "maturity_trace" in sys_p

    def test_all_dimensions(self):
        for dim in ALL_DIMENSIONS:
            sys_p, prompt = build_maturity_assessment_prompt(
                dimension=dim,
                evidence_interpretation=make_ei_dict({"dimension": dim}),
                dimension_definition=build_dimension_definition_block(dim),
            )
            assert "Level 0" in sys_p


class TestBuildRecommendationAndFinalPrompt:
    def test_returns_tuple_of_two_strings(self):
        sys_p, prompt = build_recommendation_and_final_prompt(
            dimension="Accountability",
            evidence_interpretation=make_ei_dict(),
            maturity_result=make_maturity_dict(),
            framework_synthesis=make_fs_dict(),
            plausibility_result=make_pr_dict(),
            dimension_definition=build_dimension_definition_block("Accountability"),
        )
        assert isinstance(sys_p, str)
        assert isinstance(prompt, str)
        assert len(sys_p) > 100

    def test_smallest_improvement_question(self):
        sys_p, prompt = build_recommendation_and_final_prompt(
            dimension="Privacy",
            evidence_interpretation=make_ei_dict(),
            maturity_result=make_maturity_dict(),
            framework_synthesis=make_fs_dict(),
            plausibility_result=make_pr_dict(),
            dimension_definition=build_dimension_definition_block("Privacy"),
        )
        assert "smallest realistic improvement" in sys_p

    def test_strengths_first(self):
        sys_p, prompt = build_recommendation_and_final_prompt(
            dimension="Safety",
            evidence_interpretation=make_ei_dict(),
            maturity_result=make_maturity_dict(),
            framework_synthesis=make_fs_dict(),
            plausibility_result=make_pr_dict(),
            dimension_definition=build_dimension_definition_block("Safety"),
        )
        assert "existing strengths" in sys_p.lower()

    def test_framework_synthesis_in_prompt(self):
        fs = make_fs_dict({"synthesis": "Policy meets baseline requirements"})
        sys_p, prompt = build_recommendation_and_final_prompt(
            dimension="Fairness",
            evidence_interpretation=make_ei_dict(),
            maturity_result=make_maturity_dict(),
            framework_synthesis=fs,
            plausibility_result=make_pr_dict(),
            dimension_definition=build_dimension_definition_block("Fairness"),
        )
        assert "Policy meets baseline requirements" in prompt

    def test_maturity_data_in_prompt(self):
        maturity = make_maturity_dict({"maturity_reasoning": "specific reasoning"})
        sys_p, prompt = build_recommendation_and_final_prompt(
            dimension="Transparency",
            evidence_interpretation=make_ei_dict(),
            maturity_result=maturity,
            framework_synthesis=make_fs_dict(),
            plausibility_result=make_pr_dict(),
            dimension_definition=build_dimension_definition_block("Transparency"),
        )
        assert "specific reasoning" in prompt

    def test_evidence_quotes_in_prompt(self):
        sys_p, prompt = build_recommendation_and_final_prompt(
            dimension="Inclusivity",
            evidence_interpretation=make_ei_dict(),
            maturity_result=make_maturity_dict(),
            framework_synthesis=make_fs_dict(),
            plausibility_result=make_pr_dict(),
            dimension_definition=build_dimension_definition_block("Inclusivity"),
            evidence_quotes=["Section 5 requires accessibility"],
        )
        assert "Section 5 requires accessibility" in prompt

    def test_output_json_instruction(self):
        sys_p, prompt = build_recommendation_and_final_prompt(
            dimension="Transparency",
            evidence_interpretation=make_ei_dict(),
            maturity_result=make_maturity_dict(),
            framework_synthesis=make_fs_dict(),
            plausibility_result=make_pr_dict(),
            dimension_definition=build_dimension_definition_block("Transparency"),
        )
        assert "Output JSON" in sys_p or "Output valid JSON" in prompt

    def test_style_diversity_instructions(self):
        sys_p, prompt = build_recommendation_and_final_prompt(
            dimension="Transparency",
            evidence_interpretation=make_ei_dict(),
            maturity_result=make_maturity_dict(),
            framework_synthesis=make_fs_dict(),
            plausibility_result=make_pr_dict(),
            dimension_definition=build_dimension_definition_block("Transparency"),
        )
        assert "Vary sentence openings" in sys_p
        assert "Vary transitions" in sys_p

    def test_all_dimensions(self):
        for dim in ALL_DIMENSIONS:
            sys_p, prompt = build_recommendation_and_final_prompt(
                dimension=dim,
                evidence_interpretation=make_ei_dict({"dimension": dim}),
                maturity_result=make_maturity_dict({"dimension": dim}),
                framework_synthesis=make_fs_dict(),
                plausibility_result=make_pr_dict(),
                dimension_definition=build_dimension_definition_block(dim),
            )
            assert "smallest realistic improvement" in sys_p


class TestIntegratedMaturityFramework:
    def test_contains_all_levels(self):
        assert "Level 0" in INTEGRATED_MATURITY_FRAMEWORK
        assert "Level 1" in INTEGRATED_MATURITY_FRAMEWORK
        assert "Level 2" in INTEGRATED_MATURITY_FRAMEWORK
        assert "Level 3" in INTEGRATED_MATURITY_FRAMEWORK
        assert "Level 4" in INTEGRATED_MATURITY_FRAMEWORK
        assert "Level 5" in INTEGRATED_MATURITY_FRAMEWORK

    def test_contains_functional_equivalence_checks(self):
        lower = INTEGRATED_MATURITY_FRAMEWORK.lower()
        assert "alternative terminology" in lower
        assert "embedded mechanisms" in lower
        assert "distributed implementation" in lower

    def test_contains_coverage_mapping(self):
        assert "Missing" in INTEGRATED_MATURITY_FRAMEWORK
        assert "Partial" in INTEGRATED_MATURITY_FRAMEWORK
        assert "Covered" in INTEGRATED_MATURITY_FRAMEWORK

    def test_contains_document_type_guidance(self):
        assert "strategy" in INTEGRATED_MATURITY_FRAMEWORK
        assert "legislation" in INTEGRATED_MATURITY_FRAMEWORK

    def test_contains_prefer_partial_instruction(self):
        assert "prefer Partial" in INTEGRATED_MATURITY_FRAMEWORK

    def test_contains_all_original_logic(self):
        assert "cross-cutting" in INTEGRATED_MATURITY_FRAMEWORK.lower()
        assert "functional equivalence" in INTEGRATED_MATURITY_FRAMEWORK.lower()
        assert "institutional" in INTEGRATED_MATURITY_FRAMEWORK.lower()


class TestModule12CombinedCoveredTierPrompt:
    def test_branch_a_framework_synthesis_is_compliance_justification(self):
        # Fix #1: the Fully Covered branch must demand compliance
        # justification grounded in document evidence — never
        # recommendation-style language.
        assert "COMPLIANCE JUSTIFICATION" in MODULE1_2_COMBINED_SYSTEM
        assert "not a recommendation" in MODULE1_2_COMBINED_SYSTEM
        # newline-tolerant: the phrase wraps across lines inside the prompt
        assert "ALREADY satisfies the international expectations" in MODULE1_2_COMBINED_SYSTEM
        assert "FORBIDDEN in a Covered" in MODULE1_2_COMBINED_SYSTEM
        assert "close the gap" in MODULE1_2_COMBINED_SYSTEM

    def test_branch_a_forbids_should_would_will(self):
        # The covered branch must forbid future-tense / gap-filling verbs.
        assert '"should",' in MODULE1_2_COMBINED_SYSTEM
        assert '"would",' in MODULE1_2_COMBINED_SYSTEM
        assert '"will",' in MODULE1_2_COMBINED_SYSTEM

    def test_branch_a_honesty_flag_instruction(self):
        # If the model cannot ground compliance in document evidence, it must
        # say so — surfacing a potential over-stated Coverage label.
        # (newline-tolerant: the prompt wraps the phrase across lines)
        assert "CANNOT ground a compliance claim" in MODULE1_2_COMBINED_SYSTEM
        assert "surfaced for review" in MODULE1_2_COMBINED_SYSTEM

    def test_covered_example_is_compliance_flavored(self):
        # The Branch A example must justify compliance from existing document
        # provisions (present tense), not recommend future action.
        assert "it establishes a National AI Ethics Board" in MODULE1_2_COMBINED_SYSTEM
        assert "already mandates annual transparency reporting" in MODULE1_2_COMBINED_SYSTEM

    def test_recommendation_example_only_in_branch_b(self):
        # The old leaky shared example is now explicitly scoped to Branch B
        # (Partial/Missing), with a REMEMBER warning against using it for
        # Covered dimensions.
        assert (
            "this recommendation style is ONLY correct when a gap exists"
            in MODULE1_2_COMBINED_SYSTEM
        )
        assert (
            "Branch A (Covered) must NEVER use the Branch B recommendation"
            in MODULE1_2_COMBINED_SYSTEM
        )

    def test_build_module1_2_combined_prompt_contains_compliance_instruction(self):
        sys_p, prompt = build_module1_2_combined_prompt(
            dimension="Transparency",
            dimension_definition=build_dimension_definition_block("Transparency"),
            document_chunks=[{"text": "doc text", "source_framework": "doc", "chunk_id": "aaa"}],
            module1_chunks=[{"text": "norm text", "source_framework": "fw", "chunk_id": "bbb"}],
            module2_chunks=[{"text": "prac text", "source_framework": "fw2", "chunk_id": "ccc"}],
        )
        assert "COMPLIANCE JUSTIFICATION" in sys_p
        assert "FORBIDDEN in a Covered" in sys_p


class TestNationalContextBlock:
    def test_singapore_fires(self):
        block = _national_context_block("Singapore")
        assert "AI Verify" in block
        assert "DOMESTIC" in block
        assert "already-operational" in block or "already operational" in block
        # The block must frame AI Verify as existing infrastructure — never
        # recommend Singapore adopt it.
        assert "NOT as external frameworks Singapore should adopt" in block
        assert "never recommend that Singapore" in block

    def test_singapore_case_insensitive(self):
        block = _national_context_block("  SINGAPORE ")
        assert "AI Verify" in block

    def test_other_country_empty(self):
        assert _national_context_block("India") == ""
        assert _national_context_block("United Kingdom") == ""

    def test_empty_country_empty(self):
        assert _national_context_block("") == ""
        assert _national_context_block(None) == ""

    def test_module12_prompt_contains_singapore_block(self):
        sys_p, _ = build_module1_2_combined_prompt(
            dimension="Transparency",
            dimension_definition="def",
            document_chunks=[{"text": "t", "source_framework": "", "chunk_id": "a"}],
            module1_chunks=[],
            module2_chunks=[],
            country="Singapore",
        )
        assert "NATIONAL CONTEXT (Singapore)" in sys_p
        assert "AI Verify" in sys_p

    def test_module12_prompt_other_country_no_block(self):
        sys_p, _ = build_module1_2_combined_prompt(
            dimension="Transparency",
            dimension_definition="def",
            document_chunks=[{"text": "t", "source_framework": "", "chunk_id": "a"}],
            module1_chunks=[],
            module2_chunks=[],
            country="India",
        )
        assert "NATIONAL CONTEXT (Singapore)" not in sys_p
        assert "{national_context}" not in sys_p  # placeholder always filled

    def test_module34_prompt_singapore_block(self):
        sys_p, _ = build_module3_4_combined_prompt(
            dimension="Safety",
            dimension_definition="def",
            dimension_verdict="verdict",
            module3_chunks=[],
            module4_chunks=[],
            document_chunks=[],
            country="Singapore",
        )
        assert "NATIONAL CONTEXT (Singapore)" in sys_p

    def test_no_literal_placeholder_in_any_country(self):
        for country in ("", "India", "Singapore"):
            sys_p, _ = build_module1_2_combined_prompt(
                dimension="Transparency",
                dimension_definition="def",
                document_chunks=[],
                module1_chunks=[],
                module2_chunks=[],
                country=country,
            )
            assert "{national_context}" not in sys_p


class TestDocumentNameLabelPrecedence:
    def test_framework_chunk_prefers_framework_name_over_document_name(self):
        # A framework chunk has BOTH source_framework (human name) and
        # document_name (PDF filename after sync) — the prompt label must be
        # the framework name, never the filename.
        sys_p, prompt = build_module1_2_combined_prompt(
            dimension="Transparency",
            dimension_definition="def",
            document_chunks=[],
            module1_chunks=[
                {
                    "text": "framework text",
                    "source_framework": "OECD AI Principles",
                    "document_name": "OECD_AI_Principles.pdf",
                    "chunk_id": "aaa",
                }
            ],
            module2_chunks=[],
        )
        assert "Source: OECD AI Principles" in prompt
        assert "OECD_AI_Principles.pdf" not in prompt

    def test_document_chunk_prefers_document_name(self):
        # Uploaded-document chunks have empty source_framework, so the label
        # falls through to document_name (NAIS vs Model AI Gov Framework).
        sys_p, prompt = build_module1_2_combined_prompt(
            dimension="Transparency",
            dimension_definition="def",
            document_chunks=[
                {
                    "text": "policy text",
                    "source_framework": "",
                    "document_name": "nais2023-4.pdf",
                    "chunk_id": "aaa",
                }
            ],
            module1_chunks=[],
            module2_chunks=[],
        )
        assert "Source: nais2023-4.pdf" in prompt

    def test_document_chunk_falls_back_to_uploaded_document(self):
        # Old single-doc chunks have no document_name — label stays as before.
        sys_p, prompt = build_module1_2_combined_prompt(
            dimension="Transparency",
            dimension_definition="def",
            document_chunks=[
                {
                    "text": "policy text",
                    "source_framework": "",
                    "chunk_id": "aaa",
                }
            ],
            module1_chunks=[],
            module2_chunks=[],
        )
        assert "Source: Uploaded Document" in prompt


class TestAllPromptOutputFormats:
    def test_all_prompts_output_json_instruction(self):
        dim = "Transparency"
        dd = build_dimension_definition_block(dim)
        ei = make_ei_dict()
        ma = make_maturity_dict()
        fs = make_fs_dict()
        pr = make_pr_dict()

        _, p1 = build_evidence_interpretation_prompt(dim, "text", dd)
        _, p2 = build_maturity_assessment_prompt(dim, ei, dd)
        _, p3 = build_recommendation_and_final_prompt(dim, ei, ma, fs, pr, dd)

        for i, p in enumerate([p1, p2, p3], 1):
            assert "Output valid JSON only" in p or "Output JSON" in p, (
                f"Prompt {i} missing JSON instruction"
            )

    def test_all_system_prompts_non_empty(self):
        dim = "Accountability"
        dd = build_dimension_definition_block(dim)
        ei = make_ei_dict()
        ma = make_maturity_dict()
        fs = make_fs_dict()
        pr = make_pr_dict()

        sps = [
            build_evidence_interpretation_prompt(dim, "text", dd)[0],
            build_maturity_assessment_prompt(dim, ei, dd)[0],
            build_recommendation_and_final_prompt(dim, ei, ma, fs, pr, dd)[0],
        ]
        for i, sp in enumerate(sps, 1):
            assert len(sp) > 50, f"System prompt {i} too short"
