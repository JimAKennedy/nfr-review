# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the scan-to-Structurizr workspace bridge."""

from __future__ import annotations

from nfr_review.arch_models import (
    ArchReport,
    ArchReportMetadata,
    Component,
    DynamicScenario,
    IntegrationPoint,
    RepoInfo,
    ScenarioStep,
    TechStackEntry,
)
from nfr_review.experimental_models import (
    CrossRepoEdge,
    DynamicAnalysisSection,
    ExperimentalReport,
)
from nfr_review.output.structurizr_dsl import emit_workspace_dsl
from nfr_review.structurizr_bridge import (
    build_workspace_from_arch,
    build_workspace_from_experimental,
)


def _minimal_arch_report(**overrides) -> ArchReport:
    defaults = {
        "metadata": ArchReportMetadata(
            tool_version="0.1.0",
            timestamp="2026-06-18T00:00:00Z",
            repos_analyzed=[RepoInfo(path="/tmp/repo", name="my-repo")],
        ),
        "components": [],
        "integration_points": [],
    }
    defaults.update(overrides)
    return ArchReport(**defaults)


class TestBuildWorkspaceFromArch:
    def test_empty_report_produces_valid_dsl(self) -> None:
        report = _minimal_arch_report()
        ws = build_workspace_from_arch(report)
        dsl = emit_workspace_dsl(ws)
        assert 'workspace "Architecture' in dsl
        assert "model {" in dsl

    def test_components_mapped_to_systems_and_containers(self) -> None:
        report = _minimal_arch_report(
            components=[
                Component(
                    id="svc-api",
                    name="API Service",
                    description="REST API",
                    component_type="service",
                    c4_level="container",
                    tech_stack=[TechStackEntry(name="Python")],
                ),
                Component(
                    id="ext-payment",
                    name="Payment Gateway",
                    description="External payment provider",
                    component_type="external",
                    c4_level="context",
                ),
            ]
        )
        ws = build_workspace_from_arch(report)
        dsl = emit_workspace_dsl(ws)

        assert 'softwareSystem "Payment Gateway"' in dsl
        assert 'container "API Service"' in dsl
        assert '"Python"' in dsl

    def test_integrations_become_relationships(self) -> None:
        report = _minimal_arch_report(
            components=[
                Component(
                    id="a",
                    name="A",
                    description="",
                    component_type="service",
                    c4_level="container",
                ),
                Component(
                    id="b",
                    name="B",
                    description="",
                    component_type="service",
                    c4_level="container",
                ),
            ],
            integration_points=[
                IntegrationPoint(
                    id="ip-1",
                    source_component_id="a",
                    target_component_id="b",
                    style="api_call",
                    protocol="gRPC",
                    description="Calls B",
                ),
            ],
        )
        ws = build_workspace_from_arch(report)
        dsl = emit_workspace_dsl(ws)
        assert '-> b "Calls B" "gRPC"' in dsl

    def test_cross_repo_integration_tagged(self) -> None:
        report = _minimal_arch_report(
            components=[
                Component(
                    id="a",
                    name="A",
                    description="",
                    component_type="service",
                    c4_level="container",
                    repo="repo-a",
                ),
                Component(
                    id="b",
                    name="B",
                    description="",
                    component_type="service",
                    c4_level="container",
                    repo="repo-b",
                ),
            ],
            integration_points=[
                IntegrationPoint(
                    id="ip-1",
                    source_component_id="a",
                    target_component_id="b",
                    style="api_call",
                    is_cross_repo=True,
                ),
            ],
        )
        ws = build_workspace_from_arch(report)
        dsl = emit_workspace_dsl(ws)
        assert "CrossRepo" in dsl

    def test_dynamic_scenarios_become_dynamic_views(self) -> None:
        report = _minimal_arch_report(
            components=[
                Component(
                    id="fe",
                    name="Frontend",
                    description="",
                    component_type="ui",
                    c4_level="container",
                ),
                Component(
                    id="api",
                    name="API",
                    description="",
                    component_type="service",
                    c4_level="container",
                ),
            ],
            dynamic_scenarios=[
                DynamicScenario(
                    id="checkout",
                    name="Checkout Flow",
                    description="User checks out",
                    trigger="User clicks buy",
                    steps=[
                        ScenarioStep(
                            sequence=1,
                            from_component_id="fe",
                            to_component_id="api",
                            action="POST /orders",
                        ),
                    ],
                ),
            ],
        )
        ws = build_workspace_from_arch(report)
        dsl = emit_workspace_dsl(ws)
        assert "dynamic" in dsl
        assert "Checkout Flow" in dsl
        assert "POST /orders" in dsl

    def test_custom_workspace_name(self) -> None:
        report = _minimal_arch_report()
        ws = build_workspace_from_arch(report, workspace_name="Custom Name")
        dsl = emit_workspace_dsl(ws)
        assert 'workspace "Custom Name"' in dsl

    def test_landscape_and_container_views_generated(self) -> None:
        report = _minimal_arch_report(
            components=[
                Component(
                    id="svc",
                    name="Service",
                    description="",
                    component_type="service",
                    c4_level="container",
                ),
            ]
        )
        ws = build_workspace_from_arch(report)
        dsl = emit_workspace_dsl(ws)
        assert "systemLandscape" in dsl
        assert "container" in dsl
        assert "include *" in dsl


class TestBuildWorkspaceFromExperimental:
    def test_cross_repo_edges_become_systems(self) -> None:
        report = ExperimentalReport(
            repo_name="main-repo",
            cross_repo_edges=[
                CrossRepoEdge(
                    source_repo="repo-a",
                    target_repo="repo-b",
                    source_class="ClassA",
                    target_class="ClassB",
                ),
            ],
        )
        ws = build_workspace_from_experimental(report)
        dsl = emit_workspace_dsl(ws)
        assert 'softwareSystem "repo-a"' in dsl
        assert 'softwareSystem "repo-b"' in dsl
        assert "ClassA -> ClassB" in dsl

    def test_otel_services_added(self) -> None:
        report = ExperimentalReport(
            repo_name="main-repo",
            dynamic_analysis=DynamicAnalysisSection(
                service_count=2,
                edge_count=1,
                services=["svc-a", "svc-b"],
            ),
        )
        ws = build_workspace_from_experimental(report)
        dsl = emit_workspace_dsl(ws)
        assert 'softwareSystem "svc-a"' in dsl
        assert 'softwareSystem "svc-b"' in dsl

    def test_empty_report_creates_single_system(self) -> None:
        report = ExperimentalReport(repo_name="lonely-repo")
        ws = build_workspace_from_experimental(report)
        dsl = emit_workspace_dsl(ws)
        assert 'softwareSystem "lonely-repo"' in dsl

    def test_no_duplicate_systems_from_overlap(self) -> None:
        report = ExperimentalReport(
            repo_name="main-repo",
            cross_repo_edges=[
                CrossRepoEdge(
                    source_repo="shared",
                    target_repo="other",
                    source_class="X",
                    target_class="Y",
                ),
            ],
            dynamic_analysis=DynamicAnalysisSection(
                service_count=1,
                edge_count=0,
                services=["shared"],
            ),
        )
        ws = build_workspace_from_experimental(report)
        system_names = [s.name for s in ws.model.software_systems]
        assert system_names.count("shared") == 1


class TestDslStructuralValidity:
    """Verify the emitted DSL follows Structurizr syntax rules."""

    def test_opening_braces_on_same_line(self) -> None:
        report = _minimal_arch_report(
            components=[
                Component(
                    id="svc",
                    name="Service",
                    description="desc",
                    component_type="service",
                    c4_level="container",
                    tech_stack=[TechStackEntry(name="Go")],
                ),
            ],
            integration_points=[
                IntegrationPoint(
                    id="ip-1",
                    source_component_id="svc",
                    target_component_id="svc",
                    style="api_call",
                    description="Self-call",
                    is_cross_repo=True,
                ),
            ],
        )
        ws = build_workspace_from_arch(report)
        dsl = emit_workspace_dsl(ws)
        for line in dsl.splitlines():
            stripped = line.strip()
            if stripped == "{":
                raise AssertionError(f"Opening brace alone on line: {line!r}")

    def test_closing_braces_alone_on_line(self) -> None:
        report = _minimal_arch_report(
            components=[
                Component(
                    id="svc",
                    name="S",
                    description="",
                    component_type="service",
                    c4_level="container",
                ),
            ],
        )
        ws = build_workspace_from_arch(report)
        dsl = emit_workspace_dsl(ws)
        for line in dsl.splitlines():
            stripped = line.strip()
            if "}" in stripped and stripped != "}":
                if not stripped.endswith("{"):
                    raise AssertionError(f"Closing brace not alone on line: {line!r}")
