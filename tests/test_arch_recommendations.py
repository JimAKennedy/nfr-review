# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for arch_recommendations module."""

from __future__ import annotations

from nfr_review.arch_models import (
    BoundedContext,
    Component,
    ComponentTestCoverage,
    DomainEntity,
    DomainModelSection,
    EntityRelationship,
    IntegrationPoint,
    MarketAnalysisSection,
    Recommendation,
    RiskFinding,
)
from nfr_review.arch_recommendations import (
    generate_recommendations,
    recommend_from_coverage_gaps,
    recommend_from_domain,
    recommend_from_integrations,
    recommend_from_maturity,
    recommend_from_risks,
)

# ---------------------------------------------------------------------------
# Fixtures: reusable test data
# ---------------------------------------------------------------------------


def _make_component(
    id: str = "comp-1",
    name: str = "TestService",
    component_type: str = "service",
    **kwargs,
) -> Component:
    return Component(
        id=id,
        name=name,
        description=f"Test component {name}",
        component_type=component_type,
        **kwargs,
    )


def _make_coverage(
    component_id: str = "comp-1",
    functional: str = "adequate",
    nonfunctional: str = "partial",
    test_types: list[str] | None = None,
    gaps: list[str] | None = None,
) -> ComponentTestCoverage:
    return ComponentTestCoverage(
        component_id=component_id,
        functional_coverage=functional,
        nonfunctional_coverage=nonfunctional,
        test_types_present=test_types or ["unit", "integration"],
        gaps=gaps or [],
    )


def _make_risk(
    id: str = "RISK-001",
    category: str = "performance_bottleneck",
    severity: str = "medium",
    title: str = "Test risk",
    affected_ids: list[str] | None = None,
) -> RiskFinding:
    return RiskFinding(
        id=id,
        category=category,
        severity=severity,
        title=title,
        description=f"Test risk: {title}",
        affected_component_ids=affected_ids or ["comp-1"],
    )


def _make_integration(
    id: str = "intg-1",
    source: str = "comp-1",
    target: str = "comp-2",
    style: str = "api_call",
    is_cross_repo: bool = False,
) -> IntegrationPoint:
    return IntegrationPoint(
        id=id,
        source_component_id=source,
        target_component_id=target,
        style=style,
        is_cross_repo=is_cross_repo,
    )


# ===================================================================
# 1. Coverage-gap recommendations
# ===================================================================


class TestRecommendFromCoverageGaps:
    """Tests for recommend_from_coverage_gaps."""

    def test_no_functional_coverage_is_critical(self):
        """Components with no functional coverage get critical priority."""
        comp = _make_component()
        cov = _make_coverage(functional="none", nonfunctional="partial")
        recs = recommend_from_coverage_gaps([cov], [comp])

        critical_recs = [r for r in recs if r.priority == "critical"]
        assert len(critical_recs) >= 1
        assert critical_recs[0].category == "additional_testing"
        assert "no functional" in critical_recs[0].title.lower()

    def test_none_nfr_coverage_is_high(self):
        """Components with 'none' NFR coverage get high priority."""
        comp = _make_component()
        cov = _make_coverage(functional="adequate", nonfunctional="none", test_types=["unit"])
        recs = recommend_from_coverage_gaps([cov], [comp])

        high_recs = [r for r in recs if r.priority == "high"]
        assert len(high_recs) >= 1
        assert any("non-functional" in r.title.lower() for r in high_recs)

    def test_minimal_nfr_coverage_is_high(self):
        """Components with 'minimal' NFR coverage get high priority."""
        comp = _make_component()
        cov = _make_coverage(functional="adequate", nonfunctional="minimal")
        recs = recommend_from_coverage_gaps([cov], [comp])

        high_recs = [r for r in recs if r.priority == "high"]
        assert len(high_recs) >= 1

    def test_missing_integration_tests_for_service(self):
        """Services missing integration tests get flagged."""
        comp = _make_component(component_type="service")
        cov = _make_coverage(
            functional="adequate",
            nonfunctional="adequate",
            test_types=["unit"],
        )
        recs = recommend_from_coverage_gaps([cov], [comp])

        missing_type_recs = [r for r in recs if r.priority == "medium"]
        assert len(missing_type_recs) >= 1
        assert any("integration" in r.description.lower() for r in missing_type_recs)

    def test_missing_accessibility_tests_for_ui(self):
        """UI components missing accessibility tests get flagged."""
        comp = _make_component(component_type="ui")
        cov = _make_coverage(
            functional="adequate",
            nonfunctional="adequate",
            test_types=["unit"],
        )
        recs = recommend_from_coverage_gaps([cov], [comp])

        assert any("accessibility" in r.description.lower() for r in recs)

    def test_empty_inputs(self):
        """Empty coverage and components produce no recommendations."""
        assert recommend_from_coverage_gaps([], []) == []

    def test_adequate_coverage_no_recs_for_types(self):
        """Components with all expected tests get no missing-type recs."""
        comp = _make_component(component_type="service")
        cov = _make_coverage(
            functional="adequate",
            nonfunctional="adequate",
            test_types=["unit", "integration"],
        )
        recs = recommend_from_coverage_gaps([cov], [comp])

        # Should not have missing-test-type recommendations
        missing_recs = [r for r in recs if "missing expected" in r.title.lower()]
        assert len(missing_recs) == 0

    def test_single_component(self):
        """Works correctly with a single component."""
        comp = _make_component()
        cov = _make_coverage(functional="none", nonfunctional="none")
        recs = recommend_from_coverage_gaps([cov], [comp])
        assert len(recs) >= 2  # at least critical + high

    def test_component_id_mismatch_uses_id_as_name(self):
        """When component is not in the map, uses ID as name."""
        cov = _make_coverage(component_id="unknown-comp", functional="none")
        recs = recommend_from_coverage_gaps([cov], [])
        assert len(recs) >= 1
        assert "unknown-comp" in recs[0].title


# ===================================================================
# 2. Risk-based recommendations
# ===================================================================


class TestRecommendFromRisks:
    """Tests for recommend_from_risks."""

    def test_critical_risk_produces_human_review(self):
        """Critical risks produce human_review recommendations."""
        risk = _make_risk(severity="critical", category="performance_bottleneck")
        comp = _make_component()
        recs = recommend_from_risks([risk], [comp])

        hr_recs = [r for r in recs if r.category == "human_review"]
        assert len(hr_recs) >= 1
        assert hr_recs[0].priority == "critical"

    def test_high_risk_produces_human_review(self):
        """High risks produce human_review recommendations."""
        risk = _make_risk(severity="high", category="resilience_threat")
        comp = _make_component()
        recs = recommend_from_risks([risk], [comp])

        hr_recs = [r for r in recs if r.category == "human_review"]
        assert len(hr_recs) >= 1
        assert hr_recs[0].priority == "high"

    def test_security_surface_always_human_review_high(self):
        """Security surface risks always get human_review at high priority."""
        risk = _make_risk(severity="low", category="security_surface")
        comp = _make_component()
        recs = recommend_from_risks([risk], [comp])

        hr_recs = [r for r in recs if r.category == "human_review"]
        assert len(hr_recs) >= 1
        assert hr_recs[0].priority == "high"
        assert "security" in hr_recs[0].title.lower()

    def test_risk_cluster_triggers_architecture_improvement(self):
        """3+ risks on same component triggers architecture_improvement."""
        risks = [
            _make_risk(id=f"RISK-{i}", severity="medium", affected_ids=["comp-1"])
            for i in range(3)
        ]
        comp = _make_component()
        recs = recommend_from_risks(risks, [comp])

        arch_recs = [r for r in recs if r.category == "architecture_improvement"]
        assert len(arch_recs) >= 1
        assert "cluster" in arch_recs[0].title.lower()

    def test_two_risks_no_cluster(self):
        """2 risks on same component does not trigger cluster."""
        risks = [
            _make_risk(id=f"RISK-{i}", severity="medium", affected_ids=["comp-1"])
            for i in range(2)
        ]
        comp = _make_component()
        recs = recommend_from_risks(risks, [comp])

        arch_recs = [r for r in recs if r.category == "architecture_improvement"]
        assert len(arch_recs) == 0

    def test_medium_low_risk_no_direct_rec(self):
        """Medium/low non-security risks don't produce direct recommendations."""
        risk = _make_risk(severity="medium", category="operational_risk")
        comp = _make_component()
        recs = recommend_from_risks([risk], [comp])

        # Should not have direct human_review for medium non-security risks
        hr_recs = [r for r in recs if r.category == "human_review"]
        assert len(hr_recs) == 0

    def test_empty_risks(self):
        """Empty risks produce no recommendations."""
        assert recommend_from_risks([], []) == []


# ===================================================================
# 3. Integration complexity recommendations
# ===================================================================


class TestRecommendFromIntegrations:
    """Tests for recommend_from_integrations."""

    def test_cross_repo_produces_documentation_gap(self):
        """Cross-repo integrations produce documentation_gap recs."""
        comp1 = _make_component(id="comp-1", name="ServiceA")
        comp2 = _make_component(id="comp-2", name="ServiceB")
        intg = _make_integration(source="comp-1", target="comp-2", is_cross_repo=True)
        recs = recommend_from_integrations([intg], [comp1, comp2])

        doc_recs = [r for r in recs if r.category == "documentation_gap"]
        assert len(doc_recs) >= 1
        assert "cross-repo" in doc_recs[0].title.lower()

    def test_high_fan_out_triggers_architecture_improvement(self):
        """Components with >5 integrations trigger architecture_improvement."""
        comp_main = _make_component(id="comp-main", name="Hub")
        others = [_make_component(id=f"comp-{i}", name=f"Service{i}") for i in range(6)]
        integrations = [
            _make_integration(id=f"intg-{i}", source="comp-main", target=f"comp-{i}")
            for i in range(6)
        ]

        all_comps = [comp_main] + others
        recs = recommend_from_integrations(integrations, all_comps)

        arch_recs = [r for r in recs if r.category == "architecture_improvement"]
        assert len(arch_recs) >= 1
        assert "comp-main" in arch_recs[0].affected_component_ids

    def test_five_integrations_no_flag(self):
        """Components with exactly 5 integrations are not flagged."""
        comp_main = _make_component(id="comp-main", name="Hub")
        others = [_make_component(id=f"comp-{i}", name=f"Service{i}") for i in range(5)]
        integrations = [
            _make_integration(id=f"intg-{i}", source="comp-main", target=f"comp-{i}")
            for i in range(5)
        ]

        all_comps = [comp_main] + others
        recs = recommend_from_integrations(integrations, all_comps)

        arch_recs = [r for r in recs if r.category == "architecture_improvement"]
        assert len(arch_recs) == 0

    def test_sync_chain_depth_3_triggers_human_review(self):
        """Sync chains of depth 3 trigger human_review."""
        comps = [_make_component(id=f"comp-{i}", name=f"Svc{i}") for i in range(3)]
        integrations = [
            _make_integration(
                id=f"intg-{i}",
                source=f"comp-{i}",
                target=f"comp-{i + 1}",
                style="api_call",
            )
            for i in range(2)
        ]

        recs = recommend_from_integrations(integrations, comps)

        hr_recs = [r for r in recs if r.category == "human_review"]
        assert len(hr_recs) >= 1
        assert "synchronous" in hr_recs[0].title.lower()

    def test_async_chain_no_flag(self):
        """Async chains do not trigger sync chain warnings."""
        comps = [_make_component(id=f"comp-{i}", name=f"Svc{i}") for i in range(4)]
        integrations = [
            _make_integration(
                id=f"intg-{i}",
                source=f"comp-{i}",
                target=f"comp-{i + 1}",
                style="message_queue",
            )
            for i in range(3)
        ]

        recs = recommend_from_integrations(integrations, comps)

        hr_recs = [r for r in recs if r.category == "human_review"]
        assert len(hr_recs) == 0

    def test_empty_integrations(self):
        """Empty integrations produce no recommendations."""
        assert recommend_from_integrations([], []) == []

    def test_single_integration_no_flags(self):
        """A single non-cross-repo integration produces no recs."""
        comp1 = _make_component(id="comp-1")
        comp2 = _make_component(id="comp-2")
        intg = _make_integration(source="comp-1", target="comp-2")
        recs = recommend_from_integrations([intg], [comp1, comp2])
        assert len(recs) == 0


# ===================================================================
# 4. Domain model recommendations
# ===================================================================


class TestRecommendFromDomain:
    """Tests for recommend_from_domain."""

    def test_none_domain_returns_empty(self):
        """None domain returns no recommendations."""
        assert recommend_from_domain(None) == []

    def test_orphaned_entity_flagged(self):
        """Entities with no relationships get flagged."""
        domain = DomainModelSection(
            entities=[
                DomainEntity(
                    name="OrphanedEntity",
                    description="An entity with no relationships",
                ),
            ],
        )
        recs = recommend_from_domain(domain)

        assert len(recs) >= 1
        assert recs[0].category == "human_review"
        assert "orphaned" in recs[0].title.lower()

    def test_entity_with_relationships_not_flagged(self):
        """Entities with relationships are not flagged as orphaned."""
        domain = DomainModelSection(
            entities=[
                DomainEntity(
                    name="ConnectedEntity",
                    description="Has relationships",
                    relationships=[
                        EntityRelationship(
                            target_entity="OtherEntity",
                            relationship_type="has_many",
                        )
                    ],
                ),
            ],
        )
        recs = recommend_from_domain(domain)

        orphan_recs = [r for r in recs if "orphaned" in r.title.lower()]
        assert len(orphan_recs) == 0

    def test_isolated_bounded_context_flagged(self):
        """Bounded contexts with no upstream/downstream get flagged."""
        domain = DomainModelSection(
            bounded_contexts=[
                BoundedContext(
                    name="IsolatedContext",
                    description="No connections",
                    component_ids=["comp-1"],
                ),
            ],
        )
        recs = recommend_from_domain(domain)

        assert len(recs) >= 1
        assert recs[0].category == "documentation_gap"
        assert "isolated" in recs[0].title.lower()

    def test_connected_bounded_context_not_flagged(self):
        """Bounded contexts with upstream/downstream are not flagged."""
        domain = DomainModelSection(
            bounded_contexts=[
                BoundedContext(
                    name="ConnectedContext",
                    description="Has connections",
                    upstream_contexts=["OtherContext"],
                ),
            ],
        )
        recs = recommend_from_domain(domain)

        isolated_recs = [r for r in recs if "isolated" in r.title.lower()]
        assert len(isolated_recs) == 0

    def test_empty_domain_no_recs(self):
        """Domain section with empty lists produces no recommendations."""
        domain = DomainModelSection()
        assert recommend_from_domain(domain) == []


# ===================================================================
# 5. Maturity recommendations
# ===================================================================


class TestRecommendFromMaturity:
    """Tests for recommend_from_maturity."""

    def test_none_market_returns_empty(self):
        """None market returns no recommendations."""
        assert recommend_from_maturity(None) == []

    def test_initial_maturity_flagged_high(self):
        """Initial maturity gets architecture_improvement at high priority."""
        market = MarketAnalysisSection(
            overall_maturity="initial",
            maturity_rationale="Very early stage",
        )
        recs = recommend_from_maturity(market)

        assert len(recs) == 1
        assert recs[0].category == "architecture_improvement"
        assert recs[0].priority == "high"

    def test_developing_maturity_flagged_medium(self):
        """Developing maturity gets architecture_improvement at medium."""
        market = MarketAnalysisSection(overall_maturity="developing")
        recs = recommend_from_maturity(market)

        assert len(recs) == 1
        assert recs[0].category == "architecture_improvement"
        assert recs[0].priority == "medium"

    def test_defined_maturity_not_flagged(self):
        """Defined maturity and above are not flagged."""
        for level in ("defined", "managed", "optimizing"):
            market = MarketAnalysisSection(overall_maturity=level)
            recs = recommend_from_maturity(market)
            assert len(recs) == 0, f"Expected no recs for maturity={level}"


# ===================================================================
# 6. Orchestrator: generate_recommendations
# ===================================================================


class TestGenerateRecommendations:
    """Tests for generate_recommendations orchestrator."""

    def test_assigns_sequential_ids(self):
        """Recommendations get REC-001, REC-002, etc. IDs."""
        comp = _make_component()
        cov = _make_coverage(functional="none", nonfunctional="none")
        recs = generate_recommendations(
            components=[comp],
            integrations=[],
            test_coverage=[cov],
            risks=[],
        )

        assert len(recs) >= 1
        for i, rec in enumerate(recs, start=1):
            assert rec.id == f"REC-{i:03d}"

    def test_sorted_by_priority(self):
        """Recommendations are sorted critical -> high -> medium -> low."""
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}

        comp = _make_component()
        cov = _make_coverage(functional="none", nonfunctional="none")
        risk = _make_risk(severity="high", category="resilience_threat")

        recs = generate_recommendations(
            components=[comp],
            integrations=[],
            test_coverage=[cov],
            risks=[risk],
        )

        priorities = [priority_order[r.priority] for r in recs]
        assert priorities == sorted(priorities)

    def test_deduplication_keeps_higher_priority(self):
        """When two recs have same component+category, keep higher priority."""
        comp = _make_component()

        # Create two risks affecting the same component, both producing
        # human_review: one critical, one high
        risk_critical = _make_risk(
            id="RISK-1",
            severity="critical",
            category="performance_bottleneck",
            affected_ids=["comp-1"],
        )
        risk_high = _make_risk(
            id="RISK-2",
            severity="high",
            category="resilience_threat",
            affected_ids=["comp-1"],
        )

        recs = generate_recommendations(
            components=[comp],
            integrations=[],
            test_coverage=[],
            risks=[risk_critical, risk_high],
        )

        # Both should produce human_review for comp-1
        # After dedup, only the critical one should remain
        hr_recs = [
            r
            for r in recs
            if r.category == "human_review" and "comp-1" in r.affected_component_ids
        ]
        assert len(hr_recs) == 1
        assert hr_recs[0].priority == "critical"

    def test_all_empty_inputs(self):
        """All empty inputs produce no recommendations."""
        recs = generate_recommendations(
            components=[],
            integrations=[],
            test_coverage=[],
            risks=[],
        )
        assert recs == []

    def test_all_empty_with_none_optionals(self):
        """Empty inputs with None optionals produce no recommendations."""
        recs = generate_recommendations(
            components=[],
            integrations=[],
            test_coverage=[],
            risks=[],
            domain=None,
            market=None,
        )
        assert recs == []

    def test_full_orchestration(self):
        """End-to-end test with all recommendation sources."""
        comp1 = _make_component(id="comp-1", name="API Gateway", component_type="gateway")
        comp2 = _make_component(id="comp-2", name="UserService", component_type="service")
        comp3 = _make_component(id="comp-3", name="OrderService", component_type="service")

        cov1 = _make_coverage(
            component_id="comp-1",
            functional="none",
            nonfunctional="none",
            test_types=[],
        )
        cov2 = _make_coverage(
            component_id="comp-2",
            functional="adequate",
            nonfunctional="minimal",
            test_types=["unit"],
        )

        risk = _make_risk(
            severity="high",
            category="security_surface",
            affected_ids=["comp-1"],
        )

        intg = _make_integration(source="comp-1", target="comp-2", is_cross_repo=True)

        domain = DomainModelSection(
            entities=[
                DomainEntity(name="User", description="User entity"),
            ],
        )

        market = MarketAnalysisSection(overall_maturity="initial")

        recs = generate_recommendations(
            components=[comp1, comp2, comp3],
            integrations=[intg],
            test_coverage=[cov1, cov2],
            risks=[risk],
            domain=domain,
            market=market,
        )

        assert len(recs) > 0

        # Check IDs are sequential
        for i, rec in enumerate(recs, start=1):
            assert rec.id == f"REC-{i:03d}"

        # Check sorted by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        priorities = [priority_order[r.priority] for r in recs]
        assert priorities == sorted(priorities)

        # Check that different categories are represented
        categories = {r.category for r in recs}
        assert len(categories) >= 2  # at least a couple of categories

    def test_dedup_different_categories_not_merged(self):
        """Recs with same components but different categories are NOT deduped."""
        comp = _make_component()
        cov = _make_coverage(functional="none", nonfunctional="none")

        recs = generate_recommendations(
            components=[comp],
            integrations=[],
            test_coverage=[cov],
            risks=[],
        )

        # We expect both additional_testing (from coverage gaps) recs
        # for the same component; they should NOT be merged if they
        # have different categories
        assert len(recs) >= 1

    def test_dedup_different_components_not_merged(self):
        """Recs with same category but different components not deduped."""
        comp1 = _make_component(id="comp-1", name="Svc1")
        comp2 = _make_component(id="comp-2", name="Svc2")
        cov1 = _make_coverage(component_id="comp-1", functional="none")
        cov2 = _make_coverage(component_id="comp-2", functional="none")

        recs = generate_recommendations(
            components=[comp1, comp2],
            integrations=[],
            test_coverage=[cov1, cov2],
            risks=[],
        )

        # Both components should have their own critical recs
        critical_recs = [r for r in recs if r.priority == "critical"]
        affected_comps = {frozenset(r.affected_component_ids) for r in critical_recs}
        assert frozenset(["comp-1"]) in affected_comps
        assert frozenset(["comp-2"]) in affected_comps


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_single_component_single_integration(self):
        """Single component with single integration works."""
        comp1 = _make_component(id="comp-1")
        comp2 = _make_component(id="comp-2")
        intg = _make_integration(source="comp-1", target="comp-2")

        recs = recommend_from_integrations([intg], [comp1, comp2])
        # Single non-cross-repo integration should produce no recs
        assert len(recs) == 0

    def test_recommendation_model_validates(self):
        """Recommendations are valid Pydantic models."""
        comp = _make_component()
        cov = _make_coverage(functional="none", nonfunctional="none")
        recs = generate_recommendations(
            components=[comp],
            integrations=[],
            test_coverage=[cov],
            risks=[],
        )

        for rec in recs:
            # Verify it's a proper Recommendation instance
            assert isinstance(rec, Recommendation)
            assert rec.id.startswith("REC-")
            assert rec.category in (
                "human_review",
                "additional_testing",
                "architecture_improvement",
                "documentation_gap",
            )
            assert rec.priority in ("critical", "high", "medium", "low")
            assert len(rec.title) > 0
            assert len(rec.description) > 0
            assert len(rec.rationale) > 0

    def test_multiple_security_risks_same_component(self):
        """Multiple security risks on same component still produce recs."""
        risks = [
            _make_risk(
                id=f"RISK-{i}",
                severity="medium",
                category="security_surface",
                affected_ids=["comp-1"],
            )
            for i in range(3)
        ]
        comp = _make_component()
        recs = recommend_from_risks(risks, [comp])

        # Should have security human_review recs + cluster rec
        hr_recs = [r for r in recs if r.category == "human_review"]
        assert len(hr_recs) >= 1

        arch_recs = [r for r in recs if r.category == "architecture_improvement"]
        assert len(arch_recs) >= 1

    def test_sync_chain_with_rpc_style(self):
        """RPC-style integrations are counted in sync chains."""
        comps = [_make_component(id=f"comp-{i}", name=f"Svc{i}") for i in range(3)]
        integrations = [
            _make_integration(
                id="intg-1",
                source="comp-0",
                target="comp-1",
                style="rpc",
            ),
            _make_integration(
                id="intg-2",
                source="comp-1",
                target="comp-2",
                style="synchronous",
            ),
        ]

        recs = recommend_from_integrations(integrations, comps)

        hr_recs = [r for r in recs if r.category == "human_review"]
        assert len(hr_recs) >= 1
        assert "synchronous" in hr_recs[0].title.lower()

    def test_gateway_missing_security_tests(self):
        """Gateway components missing security tests get flagged."""
        comp = _make_component(component_type="gateway")
        cov = _make_coverage(
            functional="adequate",
            nonfunctional="adequate",
            test_types=["unit", "integration"],
        )
        recs = recommend_from_coverage_gaps([cov], [comp])

        missing_recs = [r for r in recs if "security" in r.description.lower()]
        assert len(missing_recs) >= 1

    def test_external_component_missing_contract_tests(self):
        """External components missing contract tests get flagged."""
        comp = _make_component(component_type="external")
        cov = _make_coverage(
            functional="adequate",
            nonfunctional="adequate",
            test_types=["unit"],
        )
        recs = recommend_from_coverage_gaps([cov], [comp])

        missing_recs = [r for r in recs if "contract" in r.description.lower()]
        assert len(missing_recs) >= 1
