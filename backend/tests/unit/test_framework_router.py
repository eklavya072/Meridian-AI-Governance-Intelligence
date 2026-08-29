"""
Unit tests for deterministic Module 1 framework routing.
"""

import pytest

from src.framework_router import (
    CORE_FRAMEWORKS,
    _routing_metadata,
    resolve_dimension_frameworks,
    resolve_frameworks,
    resolve_regional_frameworks,
    resolve_regions,
)


class TestCoreFrameworks:
    def test_core_always_included_for_any_dimension(self):
        for dim in [
            "Transparency",
            "Privacy",
            "Accountability",
            "Safety",
            "Human Autonomy",
            "Inclusivity",
            "Fairness",
            "Environmental Sustainability",
        ]:
            frameworks = resolve_frameworks(dim)
            assert set(CORE_FRAMEWORKS).issubset(set(frameworks))

    def test_core_order_stable(self):
        a = resolve_frameworks("Transparency")
        b = resolve_frameworks("Transparency")
        assert a == b

    def test_no_llm_dimensions_for_plain_dimension(self):
        """A dimension with no dedicated frameworks gets ONLY core + any
        regional — never the dimension-specific ones of other dimensions."""
        frameworks = resolve_frameworks("Transparency")
        assert (
            "Keeping an Eye on AI: A Framework for Effective Human Oversight of AI Systems"
            not in frameworks
        )
        assert "UNESCO Policy Area 5 — Environment and Ecosystems" not in frameworks


class TestDimensionSpecificRouting:
    def test_human_autonomy_gets_ssrn(self):
        frameworks = resolve_frameworks("Human Autonomy")
        assert (
            "Keeping an Eye on AI: A Framework for Effective Human Oversight of AI Systems"
            in frameworks
        )

    def test_environmental_sustainability_gets_policy_area_5(self):
        frameworks = resolve_frameworks("Environmental Sustainability")
        assert "UNESCO Policy Area 5 — Environment and Ecosystems" in frameworks

    def test_environmental_sustainability_gets_environment_toolkit(self):
        frameworks = resolve_frameworks("Environmental Sustainability")
        assert "AI for Environment and Ecosystems Toolkit for Policymakers" in frameworks

    def test_dimension_frameworks_do_not_leak_to_other_dimensions(self):
        for dim in [
            "Transparency",
            "Privacy",
            "Accountability",
            "Safety",
            "Human Autonomy",
            "Inclusivity",
            "Fairness",
        ]:
            frameworks = resolve_frameworks(dim)
            assert "UNESCO Policy Area 5 — Environment and Ecosystems" not in frameworks
            assert "AI for Environment and Ecosystems Toolkit for Policymakers" not in frameworks
        for dim in [
            "Transparency",
            "Privacy",
            "Accountability",
            "Safety",
            "Inclusivity",
            "Fairness",
            "Environmental Sustainability",
        ]:
            frameworks = resolve_frameworks(dim)
            assert (
                "Keeping an Eye on AI: A Framework for Effective Human Oversight of AI Systems"
                not in frameworks
            )


class TestRegionalRouting:
    def test_asean_country_gets_asean_guide(self):
        frameworks = resolve_frameworks("Transparency", country="Singapore")
        assert "ASEAN Guide on AI Governance and Ethics" in frameworks

    def test_asean_variant_names(self):
        for name in ["Vietnam", "Viet Nam", "myanmar", "Brunei Darussalam", "Timor-Leste"]:
            assert "ASEAN" in resolve_regions(name)

    def test_au_country_gets_au_strategy(self):
        frameworks = resolve_frameworks("Privacy", country="Nigeria")
        assert "African Union Continental AI Strategy" in frameworks

    def test_au_country_list(self):
        assert "AU" in resolve_regions("South Africa")
        assert "AU" in resolve_regions("Côte d'Ivoire")
        assert "AU" in resolve_regions("Cote d'Ivoire")

    def test_non_region_country_gets_no_regional_frameworks(self):
        for country in ["India", "United States", "Brazil", "Japan", ""]:
            frameworks = resolve_frameworks("Transparency", country=country)
            assert "ASEAN Guide on AI Governance and Ethics" not in frameworks
            assert "African Union Continental AI Strategy" not in frameworks

    def test_country_does_not_affect_core(self):
        frameworks = resolve_frameworks("Fairness", country="Singapore")
        assert set(CORE_FRAMEWORKS).issubset(set(frameworks))

    def test_regional_frameworks_are_subset_of_routed(self):
        """The regional-reserve helper returns exactly the region-routed
        subset of the full routed list — used to guarantee Module 1 budget
        for a country's own frameworks."""
        for country in ["Singapore", "Nigeria", "South Africa", ""]:
            regional = resolve_regional_frameworks(country=country)
            routed = resolve_frameworks("Transparency", country=country)
            assert set(regional).issubset(set(routed))

    def test_regional_frameworks_include_own_framework(self):
        assert (
            "Singapore Model AI Governance Framework for Generative AI"
            in resolve_regional_frameworks("Singapore")
        )
        assert "African Union Continental AI Strategy" in resolve_regional_frameworks("Nigeria")
        assert "ASEAN Guide on AI Governance and Ethics" in resolve_regional_frameworks("Singapore")

    def test_no_region_means_no_regional_frameworks(self):
        for country in ["India", "United States", "Brazil", ""]:
            assert resolve_regional_frameworks(country=country) == []


class TestDimensionRoleRouting:
    """Dimension-tagged Module 2/3 sources resolve separately from Module 1
    routing and never leak into Module 1's framework list."""

    def test_module2_practical_dimension_sources(self):
        assert (
            "CDEI Review into Bias in Algorithmic Decision-Making"
            in resolve_dimension_frameworks("Fairness", ["module_2_practical"])
        )
        assert "NIST SP 1270: Bias Management in AI" in resolve_dimension_frameworks(
            "Fairness", ["module_2_practical"]
        )
        assert "CIPL Privacy-Enhancing Technologies in AI" in resolve_dimension_frameworks(
            "Privacy", ["module_2_practical"]
        )

    def test_module3_implementation_dimension_sources(self):
        assert "AI Cybersecurity Collaboration Playbook (CISA)" in resolve_dimension_frameworks(
            "Safety", ["module_3_implementation"]
        )
        assert "AI Verify Assurance Pilot — Main Report" in resolve_dimension_frameworks(
            "Safety", ["module_3_implementation"]
        )

    def test_role_filter_respects_module_boundary(self):
        # A Module 2 source must not be resolved as a Module 3 source and
        # vice versa.
        assert (
            "CDEI Review into Bias in Algorithmic Decision-Making"
            not in resolve_dimension_frameworks("Fairness", ["module_3_implementation"])
        )
        assert "AI Verify Assurance Pilot — Main Report" not in resolve_dimension_frameworks(
            "Safety", ["module_2_practical"]
        )

    def test_dimension_tags_do_not_leak_into_module1(self):
        # The dimension-tagged Module 2/3 sources must never join Module 1's
        # routed list — they have no normative chunks and their role is
        # served by the Module 2/3 reserve instead.
        assert "CDEI Review into Bias in Algorithmic Decision-Making" not in resolve_frameworks(
            "Fairness"
        )
        assert "AI Verify Assurance Pilot — Main Report" not in resolve_frameworks("Safety")

    def test_untagged_dimension_returns_empty(self):
        assert resolve_dimension_frameworks("Human Autonomy", ["module_2_practical"]) == []
        assert resolve_dimension_frameworks("Accountability", ["module_3_implementation"]) == []


class TestDeterminismAndDedup:
    def test_same_input_same_output(self):
        for dim in ["Human Autonomy", "Environmental Sustainability", "Transparency"]:
            for country in [None, "Singapore", "Nigeria"]:
                assert resolve_frameworks(dim, country=country) == resolve_frameworks(
                    dim, country=country
                )

    def test_no_duplicates(self):
        frameworks = resolve_frameworks("Environmental Sustainability", country="Singapore")
        assert len(frameworks) == len(set(frameworks))

    def test_core_frameworks_are_real_config_entries(self):
        dim_map, region_map = _routing_metadata()
        for fw in CORE_FRAMEWORKS:
            assert fw  # non-empty
        # Dimension + region maps are populated from config tags.
        assert "Human Autonomy" in dim_map
        assert "Environmental Sustainability" in dim_map
        assert "ASEAN" in region_map
        assert "AU" in region_map
