class TestRiskTableMatchesComputeRisk:
    """The validator's allowed-risk table must accept compute_risk's own output.

    compute_risk applies a documented cluster-compounding escalation
    (LOW->MEDIUM, MEDIUM->HIGH) when a related dimension is also a genuine
    gap, so a core Partial dimension legitimately reaches HIGH. The table
    allowed only [LOW, MEDIUM] for Partial, so the pipeline reported its own
    correct output as a risk_coverage_mismatch error whenever compounding
    fired.
    """

    def test_every_compute_risk_result_is_permitted_by_the_table(self):
        from src.consistency import RISK_COVERAGE_MAP
        from src.gap_analyzer import GOVERNANCE_DIMENSIONS, compute_risk
        from src.models import CoverageLevel, GovernanceGap

        def gap(dimension, coverage):
            return GovernanceGap(
                dimension=dimension,
                coverage=coverage,
                reason_flagged="",
                recommendation="",
            )

        assessed = (
            CoverageLevel.COVERED,
            CoverageLevel.PARTIAL,
            CoverageLevel.MISSING,
            CoverageLevel.INSUFFICIENT_EVIDENCE,
        )
        for dimension in GOVERNANCE_DIMENSIONS:
            for coverage in (CoverageLevel.PARTIAL, CoverageLevel.MISSING, CoverageLevel.COVERED):
                for neighbour in assessed:
                    others = [gap(d, neighbour) for d in GOVERNANCE_DIMENSIONS if d != dimension]
                    risk, _ = compute_risk(coverage, dimension, others)
                    allowed = RISK_COVERAGE_MAP.get(coverage)
                    if allowed:
                        assert risk in allowed, (
                            f"{dimension}/{coverage.value} with {neighbour.value} "
                            f"neighbours produced {risk.value}, not in "
                            f"{[r.value for r in allowed]}"
                        )
