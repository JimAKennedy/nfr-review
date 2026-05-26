# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for bottleneck and resilience risk analysis."""

from __future__ import annotations

from nfr_review.arch_models import (
    Component,
    ComponentBoundary,
    ComponentTestCoverage,
    IntegrationPoint,
    RiskFinding,
)
from nfr_review.arch_risk_analysis import (
    _build_adjacency,
    _compute_fan_in_out,
    _coverage_for_component,
    _find_sync_chains,
    analyze_risks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_component(
    name: str,
    comp_type: str = "service",
    repo: str = "test-repo",
) -> Component:
    """Create a minimal Component for testing."""
    return Component(
        id=f"comp-{name}",
        name=name,
        description=f"Test component {name}",
        component_type=comp_type,
        boundaries=[
            ComponentBoundary(
                boundary_type="directory",
                path=name,
                repo=repo,
            )
        ],
        repo=repo,
    )


def _make_integration(
    source: str,
    target: str,
    style: str = "synchronous",
    is_cross_repo: bool = False,
    intg_id: str | None = None,
) -> IntegrationPoint:
    """Create a minimal IntegrationPoint for testing."""
    eid = intg_id or f"intg-{source}-{target}"
    return IntegrationPoint(
        id=eid,
        source_component_id=f"comp-{source}",
        target_component_id=f"comp-{target}",
        style=style,
        description=f"{source} -> {target}",
        is_cross_repo=is_cross_repo,
    )


def _make_coverage(
    component_name: str,
    functional: str = "adequate",
    nonfunctional: str = "partial",
    test_types: list[str] | None = None,
    gaps: list[str] | None = None,
) -> ComponentTestCoverage:
    """Create a minimal ComponentTestCoverage for testing."""
    return ComponentTestCoverage(
        component_id=f"comp-{component_name}",
        functional_coverage=functional,
        nonfunctional_coverage=nonfunctional,
        test_types_present=test_types or ["unit", "integration"],
        gaps=gaps or [],
    )


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestBuildAdjacency:
    def test_empty_integrations(self) -> None:
        result = _build_adjacency([])
        assert result == {}

    def test_single_integration(self) -> None:
        intg = _make_integration("a", "b")
        result = _build_adjacency([intg])
        assert "comp-a" in result
        assert len(result["comp-a"]) == 1
        assert result["comp-a"][0][0] == "comp-b"

    def test_multiple_targets(self) -> None:
        intgs = [
            _make_integration("a", "b"),
            _make_integration("a", "c"),
        ]
        result = _build_adjacency(intgs)
        assert len(result["comp-a"]) == 2


class TestComputeFanInOut:
    def test_empty(self) -> None:
        comp = _make_component("a")
        result = _compute_fan_in_out([comp], [])
        assert result["comp-a"] == (0, 0)

    def test_fan_in(self) -> None:
        comps = [_make_component("a"), _make_component("b"), _make_component("c")]
        intgs = [
            _make_integration("b", "a"),
            _make_integration("c", "a"),
        ]
        result = _compute_fan_in_out(comps, intgs)
        assert result["comp-a"] == (2, 0)
        assert result["comp-b"] == (0, 1)
        assert result["comp-c"] == (0, 1)

    def test_fan_out(self) -> None:
        comps = [_make_component("a"), _make_component("b")]
        intgs = [
            _make_integration("a", "b"),
        ]
        result = _compute_fan_in_out(comps, intgs)
        assert result["comp-a"] == (0, 1)
        assert result["comp-b"] == (1, 0)


class TestFindSyncChains:
    def test_no_sync_integrations(self) -> None:
        intgs = [_make_integration("a", "b", style="asynchronous")]
        result = _find_sync_chains(intgs)
        assert result == []

    def test_chain_of_three(self) -> None:
        intgs = [
            _make_integration("a", "b", style="synchronous"),
            _make_integration("b", "c", style="synchronous"),
        ]
        result = _find_sync_chains(intgs)
        assert len(result) >= 1
        assert any(len(chain) == 3 for chain in result)

    def test_chain_includes_api_call_style(self) -> None:
        intgs = [
            _make_integration("a", "b", style="api_call"),
            _make_integration("b", "c", style="api_call"),
        ]
        result = _find_sync_chains(intgs)
        assert len(result) >= 1

    def test_chain_includes_rpc_style(self) -> None:
        intgs = [
            _make_integration("a", "b", style="rpc"),
            _make_integration("b", "c", style="rpc"),
        ]
        result = _find_sync_chains(intgs)
        assert len(result) >= 1

    def test_short_chain_not_returned(self) -> None:
        intgs = [_make_integration("a", "b", style="synchronous")]
        result = _find_sync_chains(intgs)
        assert result == []

    def test_longer_chains_first(self) -> None:
        intgs = [
            _make_integration("a", "b", style="synchronous"),
            _make_integration("b", "c", style="synchronous"),
            _make_integration("c", "d", style="synchronous"),
        ]
        result = _find_sync_chains(intgs)
        assert len(result) >= 1
        # The longest chain should be first
        assert len(result[0]) >= len(result[-1])


class TestCoverageForComponent:
    def test_none_coverage(self) -> None:
        assert _coverage_for_component("comp-a", None) is None

    def test_found(self) -> None:
        cov = _make_coverage("a")
        result = _coverage_for_component("comp-a", [cov])
        assert result is cov

    def test_not_found(self) -> None:
        cov = _make_coverage("a")
        result = _coverage_for_component("comp-b", [cov])
        assert result is None


# ---------------------------------------------------------------------------
# Individual risk detector tests
# ---------------------------------------------------------------------------


class TestSinglePointOfFailure:
    def test_high_fan_in_detected(self) -> None:
        """Component with fan-in >= 3 should be flagged."""
        target = _make_component("db")
        sources = [_make_component(f"svc-{i}") for i in range(3)]
        intgs = [_make_integration(f"svc-{i}", "db") for i in range(3)]

        findings = analyze_risks([target, *sources], intgs, spof_threshold=3)
        spof = [
            f
            for f in findings
            if f.category == "resilience_threat" and "Single point of failure" in f.title
        ]
        assert len(spof) >= 1
        assert spof[0].severity == "medium"

    def test_high_severity_at_five(self) -> None:
        """Fan-in >= 5 should produce high severity."""
        target = _make_component("db")
        sources = [_make_component(f"svc-{i}") for i in range(5)]
        intgs = [_make_integration(f"svc-{i}", "db") for i in range(5)]

        findings = analyze_risks([target, *sources], intgs, spof_threshold=3)
        spof = [
            f
            for f in findings
            if f.category == "resilience_threat" and "Single point of failure" in f.title
        ]
        assert len(spof) >= 1
        assert spof[0].severity == "high"

    def test_below_threshold_not_detected(self) -> None:
        """Fan-in < threshold should not be flagged."""
        target = _make_component("db")
        sources = [_make_component(f"svc-{i}") for i in range(2)]
        intgs = [_make_integration(f"svc-{i}", "db") for i in range(2)]

        findings = analyze_risks([target, *sources], intgs, spof_threshold=3)
        spof = [f for f in findings if "Single point of failure" in f.title]
        assert len(spof) == 0

    def test_custom_threshold(self) -> None:
        """Custom spof_threshold should be respected."""
        target = _make_component("db")
        sources = [_make_component(f"svc-{i}") for i in range(2)]
        intgs = [_make_integration(f"svc-{i}", "db") for i in range(2)]

        findings = analyze_risks([target, *sources], intgs, spof_threshold=2)
        spof = [f for f in findings if "Single point of failure" in f.title]
        assert len(spof) >= 1


class TestSyncChainRisk:
    def test_chain_of_three_detected(self) -> None:
        comps = [_make_component(f"svc-{i}") for i in range(3)]
        intgs = [
            _make_integration("svc-0", "svc-1", style="synchronous"),
            _make_integration("svc-1", "svc-2", style="synchronous"),
        ]

        findings = analyze_risks(comps, intgs, sync_chain_threshold=3)
        chain_risks = [
            f
            for f in findings
            if f.category == "performance_bottleneck" and "Synchronous call chain" in f.title
        ]
        assert len(chain_risks) >= 1
        assert chain_risks[0].severity == "medium"

    def test_chain_of_four_is_high(self) -> None:
        comps = [_make_component(f"svc-{i}") for i in range(4)]
        intgs = [
            _make_integration("svc-0", "svc-1", style="synchronous"),
            _make_integration("svc-1", "svc-2", style="synchronous"),
            _make_integration("svc-2", "svc-3", style="synchronous"),
        ]

        findings = analyze_risks(comps, intgs, sync_chain_threshold=3)
        chain_risks = [f for f in findings if "Synchronous call chain" in f.title]
        assert len(chain_risks) >= 1
        assert chain_risks[0].severity == "high"

    def test_async_chain_not_detected(self) -> None:
        comps = [_make_component(f"svc-{i}") for i in range(3)]
        intgs = [
            _make_integration("svc-0", "svc-1", style="asynchronous"),
            _make_integration("svc-1", "svc-2", style="asynchronous"),
        ]

        findings = analyze_risks(comps, intgs, sync_chain_threshold=3)
        chain_risks = [f for f in findings if "Synchronous call chain" in f.title]
        assert len(chain_risks) == 0


class TestMissingResilienceTesting:
    def test_detected_when_nonfunctional_none(self) -> None:
        comps = [_make_component("api"), _make_component("db"), _make_component("cache")]
        intgs = [
            _make_integration("api", "db"),
            _make_integration("api", "cache"),
        ]
        coverage = [
            _make_coverage("api", nonfunctional="none"),
        ]

        findings = analyze_risks(comps, intgs, coverage)
        resilience = [f for f in findings if "Missing resilience testing" in f.title]
        assert len(resilience) >= 1

    def test_not_detected_with_adequate_coverage(self) -> None:
        comps = [_make_component("api"), _make_component("db"), _make_component("cache")]
        intgs = [
            _make_integration("api", "db"),
            _make_integration("api", "cache"),
        ]
        coverage = [
            _make_coverage("api", nonfunctional="adequate"),
        ]

        findings = analyze_risks(comps, intgs, coverage)
        resilience = [f for f in findings if "Missing resilience testing" in f.title]
        assert len(resilience) == 0

    def test_detected_when_gaps_mention_resilience(self) -> None:
        comps = [_make_component("api"), _make_component("db"), _make_component("cache")]
        intgs = [
            _make_integration("api", "db"),
            _make_integration("api", "cache"),
        ]
        coverage = [
            _make_coverage(
                "api",
                nonfunctional="partial",
                gaps=["No resilience tests"],
            ),
        ]

        findings = analyze_risks(comps, intgs, coverage)
        resilience = [f for f in findings if "Missing resilience testing" in f.title]
        assert len(resilience) >= 1

    def test_not_detected_when_coverage_is_none(self) -> None:
        """Coverage=None should not crash coverage-dependent detectors."""
        comps = [_make_component("api"), _make_component("db")]
        intgs = [_make_integration("api", "db")]

        findings = analyze_risks(comps, intgs, coverage=None)
        resilience = [f for f in findings if "Missing resilience testing" in f.title]
        assert len(resilience) == 0


class TestDatabaseBottleneck:
    def test_detected_at_three_consumers(self) -> None:
        db = _make_component("main-db", comp_type="database")
        services = [_make_component(f"svc-{i}") for i in range(3)]
        intgs = [_make_integration(f"svc-{i}", "main-db") for i in range(3)]

        findings = analyze_risks([db, *services], intgs)
        db_risks = [f for f in findings if "Database bottleneck" in f.title]
        assert len(db_risks) >= 1
        assert db_risks[0].severity == "medium"

    def test_high_severity_at_five(self) -> None:
        db = _make_component("main-db", comp_type="database")
        services = [_make_component(f"svc-{i}") for i in range(5)]
        intgs = [_make_integration(f"svc-{i}", "main-db") for i in range(5)]

        findings = analyze_risks([db, *services], intgs)
        db_risks = [f for f in findings if "Database bottleneck" in f.title]
        assert len(db_risks) >= 1
        assert db_risks[0].severity == "high"

    def test_shared_database_style_mentioned(self) -> None:
        db = _make_component("shared-db", comp_type="database")
        services = [_make_component(f"svc-{i}") for i in range(3)]
        intgs = [
            _make_integration(f"svc-{i}", "shared-db", style="shared_database")
            for i in range(3)
        ]

        findings = analyze_risks([db, *services], intgs)
        db_risks = [f for f in findings if "Database bottleneck" in f.title]
        assert len(db_risks) >= 1
        assert "shared_database" in db_risks[0].description

    def test_non_database_not_detected(self) -> None:
        """Non-database components with high fan-in are not flagged as DB bottleneck."""
        svc = _make_component("api", comp_type="service")
        sources = [_make_component(f"client-{i}") for i in range(3)]
        intgs = [_make_integration(f"client-{i}", "api") for i in range(3)]

        findings = analyze_risks([svc, *sources], intgs)
        db_risks = [f for f in findings if "Database bottleneck" in f.title]
        assert len(db_risks) == 0


class TestCrossRepoRisk:
    def test_cross_repo_detected(self) -> None:
        comps = [_make_component("svc-a"), _make_component("svc-b")]
        intgs = [_make_integration("svc-a", "svc-b", is_cross_repo=True)]

        findings = analyze_risks(comps, intgs)
        cross = [f for f in findings if f.category == "operational_risk"]
        assert len(cross) >= 1
        assert cross[0].severity == "medium"

    def test_same_repo_not_detected(self) -> None:
        comps = [_make_component("svc-a"), _make_component("svc-b")]
        intgs = [_make_integration("svc-a", "svc-b", is_cross_repo=False)]

        findings = analyze_risks(comps, intgs)
        cross = [f for f in findings if f.category == "operational_risk"]
        assert len(cross) == 0


class TestGatewayScalability:
    def test_gateway_with_high_fan_out(self) -> None:
        gw = _make_component("api-gateway", comp_type="gateway")
        targets = [_make_component(f"svc-{i}") for i in range(3)]
        intgs = [_make_integration("api-gateway", f"svc-{i}") for i in range(3)]

        findings = analyze_risks([gw, *targets], intgs)
        gw_risks = [f for f in findings if f.category == "scalability_limit"]
        assert len(gw_risks) >= 1
        assert gw_risks[0].severity == "medium"

    def test_non_gateway_not_detected(self) -> None:
        svc = _make_component("main-api", comp_type="service")
        targets = [_make_component(f"svc-{i}") for i in range(3)]
        intgs = [_make_integration("main-api", f"svc-{i}") for i in range(3)]

        findings = analyze_risks([svc, *targets], intgs)
        gw_risks = [f for f in findings if f.category == "scalability_limit"]
        assert len(gw_risks) == 0


class TestMissingTestCoverageHotspot:
    def test_detected_with_many_integrations(self) -> None:
        comp = _make_component("core-svc")
        others = [_make_component(f"other-{i}") for i in range(4)]
        intgs = [_make_integration(f"other-{i}", "core-svc") for i in range(4)]
        coverage = [_make_coverage("core-svc", functional="none")]

        findings = analyze_risks([comp, *others], intgs, coverage)
        hotspot = [f for f in findings if f.category == "change_hotspot"]
        assert len(hotspot) >= 1
        assert hotspot[0].severity == "high"

    def test_not_detected_with_adequate_coverage(self) -> None:
        comp = _make_component("core-svc")
        others = [_make_component(f"other-{i}") for i in range(4)]
        intgs = [_make_integration(f"other-{i}", "core-svc") for i in range(4)]
        coverage = [_make_coverage("core-svc", functional="adequate")]

        findings = analyze_risks([comp, *others], intgs, coverage)
        hotspot = [f for f in findings if f.category == "change_hotspot"]
        assert len(hotspot) == 0

    def test_not_detected_with_few_integrations(self) -> None:
        comp = _make_component("simple-svc")
        other = _make_component("other")
        intgs = [_make_integration("other", "simple-svc")]
        coverage = [_make_coverage("simple-svc", functional="none")]

        findings = analyze_risks([comp, other], intgs, coverage)
        hotspot = [f for f in findings if f.category == "change_hotspot"]
        assert len(hotspot) == 0


class TestSecuritySurface:
    def test_gateway_without_security_tests(self) -> None:
        gw = _make_component("api-gw", comp_type="gateway")
        coverage = [_make_coverage("api-gw", test_types=["unit"])]

        findings = analyze_risks([gw], [], coverage)
        sec = [f for f in findings if f.category == "security_surface"]
        assert len(sec) >= 1
        assert sec[0].severity == "medium"

    def test_gateway_with_security_tests_not_flagged(self) -> None:
        gw = _make_component("api-gw", comp_type="gateway")
        coverage = [_make_coverage("api-gw", test_types=["unit", "security"])]

        findings = analyze_risks([gw], [], coverage)
        sec = [f for f in findings if f.category == "security_surface"]
        assert len(sec) == 0

    def test_ui_component_flagged(self) -> None:
        ui = _make_component("web-app", comp_type="ui")
        coverage = [_make_coverage("web-app", test_types=["unit"])]

        findings = analyze_risks([ui], [], coverage)
        sec = [f for f in findings if f.category == "security_surface"]
        assert len(sec) >= 1
        assert sec[0].severity == "low"

    def test_external_integration_flagged(self) -> None:
        svc = _make_component("payment-svc", comp_type="service")
        ext = _make_component("stripe", comp_type="external")
        intgs = [_make_integration("payment-svc", "stripe")]
        coverage = [_make_coverage("payment-svc", test_types=["unit"])]

        findings = analyze_risks([svc, ext], intgs, coverage)
        sec = [
            f
            for f in findings
            if f.category == "security_surface" and "payment-svc" in f.title
        ]
        assert len(sec) >= 1

    def test_no_coverage_data_still_flags_gateway(self) -> None:
        """Security surface should be detected even without coverage data."""
        gw = _make_component("api-gw", comp_type="gateway")

        findings = analyze_risks([gw], [], coverage=None)
        sec = [f for f in findings if f.category == "security_surface"]
        assert len(sec) >= 1


# ---------------------------------------------------------------------------
# End-to-end / analyze_risks tests
# ---------------------------------------------------------------------------


class TestAnalyzeRisks:
    def test_empty_components(self) -> None:
        """No components should produce no findings."""
        findings = analyze_risks([], [])
        assert findings == []

    def test_single_component_no_integrations(self) -> None:
        """Single component with no integrations should produce minimal findings."""
        comp = _make_component("lonely-svc")
        findings = analyze_risks([comp], [])
        # No SPOF, no chain, no DB bottleneck, no cross-repo
        # Might get security surface if it were a gateway, but service is fine
        bottleneck = [f for f in findings if f.category == "performance_bottleneck"]
        assert len(bottleneck) == 0
        spof = [f for f in findings if "Single point of failure" in f.title]
        assert len(spof) == 0

    def test_ids_are_sequential(self) -> None:
        """Risk IDs should be RISK-001, RISK-002, etc."""
        comps = [
            _make_component("db", comp_type="database"),
            *[_make_component(f"svc-{i}") for i in range(5)],
        ]
        intgs = [_make_integration(f"svc-{i}", "db") for i in range(5)]

        findings = analyze_risks(comps, intgs)
        assert len(findings) > 0
        for i, finding in enumerate(findings, start=1):
            assert finding.id == f"RISK-{i:03d}"

    def test_ids_are_unique(self) -> None:
        """All IDs should be unique."""
        comps = [
            _make_component("db", comp_type="database"),
            _make_component("api-gw", comp_type="gateway"),
            *[_make_component(f"svc-{i}") for i in range(5)],
        ]
        intgs = [
            *[_make_integration(f"svc-{i}", "db") for i in range(5)],
            *[_make_integration("api-gw", f"svc-{i}") for i in range(5)],
        ]

        findings = analyze_risks(comps, intgs)
        ids = [f.id for f in findings]
        assert len(ids) == len(set(ids))

    def test_severity_ordering(self) -> None:
        """Findings should be sorted by severity (high before medium before low)."""
        comps = [
            _make_component("db", comp_type="database"),
            _make_component("gw", comp_type="gateway"),
            *[_make_component(f"svc-{i}") for i in range(5)],
        ]
        intgs = [
            *[_make_integration(f"svc-{i}", "db") for i in range(5)],
            *[_make_integration("gw", f"svc-{i}") for i in range(5)],
        ]

        findings = analyze_risks(comps, intgs)
        severities = [f.severity for f in findings]
        severity_values = [_severity_val(s) for s in severities]
        assert severity_values == sorted(severity_values)

    def test_realistic_scenario(self) -> None:
        """End-to-end test with a realistic multi-component architecture."""
        comps = [
            _make_component("api-gateway", comp_type="gateway"),
            _make_component("user-service"),
            _make_component("order-service"),
            _make_component("payment-service"),
            _make_component("notification-worker", comp_type="worker"),
            _make_component("main-db", comp_type="database"),
            _make_component("redis-cache", comp_type="database"),
            _make_component("stripe-api", comp_type="external"),
        ]
        intgs = [
            # Gateway routes to services
            _make_integration("api-gateway", "user-service", style="synchronous"),
            _make_integration("api-gateway", "order-service", style="synchronous"),
            _make_integration("api-gateway", "payment-service", style="synchronous"),
            # Sync chain: gw -> order -> payment -> stripe
            _make_integration("order-service", "payment-service", style="synchronous"),
            _make_integration("payment-service", "stripe-api", style="api_call"),
            # Database access
            _make_integration("user-service", "main-db", style="shared_database"),
            _make_integration("order-service", "main-db", style="shared_database"),
            _make_integration("payment-service", "main-db", style="shared_database"),
            # Cache
            _make_integration("user-service", "redis-cache", style="shared_database"),
            _make_integration("order-service", "redis-cache", style="shared_database"),
            _make_integration("payment-service", "redis-cache", style="shared_database"),
            # Async notification
            _make_integration("order-service", "notification-worker", style="asynchronous"),
        ]
        coverage = [
            _make_coverage(
                "api-gateway", functional="minimal", nonfunctional="none", test_types=["unit"]
            ),
            _make_coverage(
                "user-service",
                functional="adequate",
                nonfunctional="minimal",
                test_types=["unit", "integration"],
            ),
            _make_coverage(
                "order-service",
                functional="adequate",
                nonfunctional="none",
                test_types=["unit", "integration"],
            ),
            _make_coverage(
                "payment-service",
                functional="partial",
                nonfunctional="none",
                test_types=["unit"],
            ),
            _make_coverage(
                "notification-worker",
                functional="minimal",
                nonfunctional="none",
                test_types=["unit"],
            ),
            _make_coverage("main-db"),
            _make_coverage("redis-cache"),
        ]

        findings = analyze_risks(comps, intgs, coverage)

        assert len(findings) > 0
        categories = {f.category for f in findings}

        # We should see multiple risk categories in a realistic scenario
        assert "performance_bottleneck" in categories  # DB bottleneck or sync chain
        assert "resilience_threat" in categories  # SPOF or missing resilience
        assert "security_surface" in categories  # Gateway or external

        # Verify all findings have proper IDs
        for f in findings:
            assert f.id.startswith("RISK-")

    def test_coverage_none_does_not_crash(self) -> None:
        """Passing coverage=None should not crash any detector."""
        comps = [
            _make_component("db", comp_type="database"),
            _make_component("gw", comp_type="gateway"),
            *[_make_component(f"svc-{i}") for i in range(5)],
        ]
        intgs = [
            *[_make_integration(f"svc-{i}", "db") for i in range(5)],
            *[_make_integration("gw", f"svc-{i}") for i in range(5)],
        ]

        # Should not raise
        findings = analyze_risks(comps, intgs, coverage=None)
        assert isinstance(findings, list)
        # Coverage-dependent detectors should produce no findings
        resilience = [f for f in findings if "Missing resilience testing" in f.title]
        assert len(resilience) == 0
        hotspot = [f for f in findings if f.category == "change_hotspot"]
        assert len(hotspot) == 0

    def test_no_integrations_no_bottlenecks(self) -> None:
        """Components with no integrations should not produce bottleneck risks."""
        comps = [_make_component(f"svc-{i}") for i in range(5)]
        findings = analyze_risks(comps, [])
        bottleneck = [f for f in findings if f.category == "performance_bottleneck"]
        assert len(bottleneck) == 0

    def test_findings_are_risk_finding_instances(self) -> None:
        """All findings should be RiskFinding instances."""
        comps = [
            _make_component("db", comp_type="database"),
            *[_make_component(f"svc-{i}") for i in range(3)],
        ]
        intgs = [_make_integration(f"svc-{i}", "db") for i in range(3)]
        findings = analyze_risks(comps, intgs)
        for f in findings:
            assert isinstance(f, RiskFinding)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _severity_val(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 99)
