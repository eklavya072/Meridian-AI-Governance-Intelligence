import pytest

from src.analysis_prompts import (
    DIMENSION_DEFINITIONS,
    MODULE1_2_COMBINED_SYSTEM,
    MODULE3_4_COMBINED_SYSTEM,
    _national_context_block,
    build_dimension_definition_block,
    build_module1_2_combined_prompt,
    build_module3_4_combined_prompt,
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


def make_depth_dict(overrides: dict | None = None) -> dict:
    base = {
        "dimension": "Transparency",
        "depth_level": 2,
        "depth_label": "Governance Objectives Defined",
        "coverage": "Partial",
        "depth_reasoning": "Policy defines transparency objectives but lacks mechanisms",
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
        "implementation_depth_comparison": {},
        "synthesis": "Policy meets baseline disclosure but lacks audit mechanisms",
    }
    if overrides:
        base.update(overrides)
    return base


def make_pr_dict(overrides: dict | None = None) -> dict:
    base = {
        "validated_depth_level": 2,
        "validated_coverage": "Partial",
        "confidence_in_assessment": "Medium",
    }
    if overrides:
        base.update(overrides)
    return base


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


class TestAdviceIsSpecific:
    """Generic advice is what a policy adviser gets pulled up on."""

    def test_roadmap_citations_must_say_what_they_support(self):
        """Every stored roadmap citation had an empty claim field, because the
        schema shown to the model never asked for one."""
        from src import analysis_prompts

        source = analysis_prompts.__file__
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        assert '"claim": "which step this passage supports"' in text
        assert "A quote with no claim cannot be checked" in text
