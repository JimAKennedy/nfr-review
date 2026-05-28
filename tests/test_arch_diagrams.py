# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for C4 architecture diagram generation."""

from __future__ import annotations

import pytest

from nfr_review.arch_diagrams import (
    _package_boundary,
    _safe_id,
    generate_all_diagrams,
    render_c4_code,
    render_c4_component,
    render_c4_component_detail,
    render_c4_component_overview,
    render_c4_container,
    render_c4_context,
    render_class_diagram,
    render_pipeline_diagram,
)
from nfr_review.arch_discovery import DvcPipeline, DvcStage
from nfr_review.arch_models import (
    C4Diagram,
    Component,
    ComponentBoundary,
    ComponentTestCoverage,
    IntegrationPoint,
    TechStackEntry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_service() -> Component:
    return Component(
        id="svc-api",
        name="API Service",
        description="REST API gateway",
        component_type="service",
        boundaries=[ComponentBoundary(boundary_type="directory", path="services/api")],
        responsibilities=["handle HTTP requests"],
        tech_stack=[TechStackEntry(name="FastAPI")],
        repo="my-app",
    )


@pytest.fixture()
def db_component() -> Component:
    return Component(
        id="db-main",
        name="Main Database",
        description="Primary PostgreSQL database",
        component_type="database",
        boundaries=[ComponentBoundary(boundary_type="directory", path="infra/db")],
        repo="my-app",
    )


@pytest.fixture()
def queue_component() -> Component:
    return Component(
        id="queue-events",
        name="Event Queue",
        description="Message queue for async events",
        component_type="queue",
        boundaries=[ComponentBoundary(boundary_type="directory", path="infra/queue")],
        repo="my-app",
    )


@pytest.fixture()
def worker_component() -> Component:
    return Component(
        id="worker-bg",
        name="Background Worker",
        description="Processes async jobs",
        component_type="worker",
        boundaries=[ComponentBoundary(boundary_type="directory", path="services/worker")],
        repo="my-app",
    )


@pytest.fixture()
def lib_component() -> Component:
    return Component(
        id="lib-common",
        name="Common Library",
        description="Shared utilities",
        component_type="library",
        boundaries=[ComponentBoundary(boundary_type="package", path="libs/common")],
        repo="my-app",
    )


@pytest.fixture()
def external_system() -> Component:
    return Component(
        id="ext-payment",
        name="Payment Gateway",
        description="External payment provider",
        component_type="external",
    )


@pytest.fixture()
def sync_integration() -> IntegrationPoint:
    return IntegrationPoint(
        id="int-api-db",
        source_component_id="svc-api",
        target_component_id="db-main",
        style="synchronous",
        protocol="SQL",
        description="Direct DB queries",
    )


@pytest.fixture()
def async_integration() -> IntegrationPoint:
    return IntegrationPoint(
        id="int-api-queue",
        source_component_id="svc-api",
        target_component_id="queue-events",
        style="asynchronous",
        protocol="AMQP",
        description="Publish events",
    )


@pytest.fixture()
def event_integration() -> IntegrationPoint:
    return IntegrationPoint(
        id="int-queue-worker",
        source_component_id="queue-events",
        target_component_id="worker-bg",
        style="event_driven",
        protocol="AMQP",
        description="Consume events",
    )


@pytest.fixture()
def cross_repo_integration() -> IntegrationPoint:
    return IntegrationPoint(
        id="int-api-ext",
        source_component_id="svc-api",
        target_component_id="ext-payment",
        style="synchronous",
        protocol="HTTPS",
        description="Payment calls",
        is_cross_repo=True,
    )


@pytest.fixture()
def all_components(
    api_service: Component,
    db_component: Component,
    queue_component: Component,
    worker_component: Component,
    lib_component: Component,
    external_system: Component,
) -> list[Component]:
    return [
        api_service,
        db_component,
        queue_component,
        worker_component,
        lib_component,
        external_system,
    ]


@pytest.fixture()
def all_integrations(
    sync_integration: IntegrationPoint,
    async_integration: IntegrationPoint,
    event_integration: IntegrationPoint,
    cross_repo_integration: IntegrationPoint,
) -> list[IntegrationPoint]:
    return [sync_integration, async_integration, event_integration, cross_repo_integration]


# ---------------------------------------------------------------------------
# _safe_id tests
# ---------------------------------------------------------------------------


class TestSafeId:
    def test_simple_id(self) -> None:
        assert _safe_id("hello") == "hello"

    def test_special_characters(self) -> None:
        assert _safe_id("my-service.v2") == "my_service_v2"

    def test_spaces_and_symbols(self) -> None:
        assert _safe_id("Service A (v2)") == "Service_A__v2_"

    def test_already_safe(self) -> None:
        assert _safe_id("abc_123") == "abc_123"


# ---------------------------------------------------------------------------
# Context diagram tests
# ---------------------------------------------------------------------------


class TestRenderC4Context:
    def test_empty_components(self) -> None:
        result = render_c4_context([], [])
        assert isinstance(result, C4Diagram)
        assert result.level == "context"
        assert result.component_ids == []
        assert "flowchart TD" in result.mermaid

    def test_single_internal(self, api_service: Component) -> None:
        result = render_c4_context([api_service], [])
        assert result.level == "context"
        assert "svc_api" not in result.mermaid  # collapsed into system
        assert "subgraph system" in result.mermaid
        assert "API Service" in result.mermaid
        assert result.component_ids == ["svc-api"]

    def test_external_shown_separately(
        self,
        api_service: Component,
        external_system: Component,
    ) -> None:
        result = render_c4_context([api_service, external_system], [])
        assert "Payment Gateway" in result.mermaid
        assert _safe_id("ext-payment") in result.mermaid

    def test_cross_repo_edge(
        self,
        api_service: Component,
        external_system: Component,
        cross_repo_integration: IntegrationPoint,
    ) -> None:
        result = render_c4_context(
            [api_service, external_system],
            [cross_repo_integration],
        )
        assert "sys_inner" in result.mermaid
        assert _safe_id("ext-payment") in result.mermaid
        assert "-->" in result.mermaid
        assert "HTTPS" in result.mermaid

    def test_internal_edges_skipped(
        self,
        api_service: Component,
        db_component: Component,
        sync_integration: IntegrationPoint,
    ) -> None:
        result = render_c4_context(
            [api_service, db_component],
            [sync_integration],
        )
        # Both are internal, so no edge should appear
        assert "-->" not in result.mermaid.split("end\n", 1)[-1]

    def test_custom_title(self, api_service: Component) -> None:
        result = render_c4_context([api_service], [], title="My System")
        assert result.title == "My System"
        assert "My System" in result.mermaid

    def test_only_externals(self, external_system: Component) -> None:
        result = render_c4_context([external_system], [])
        assert "Payment Gateway" in result.mermaid
        assert result.component_ids == ["ext-payment"]


# ---------------------------------------------------------------------------
# Container diagram tests
# ---------------------------------------------------------------------------


class TestRenderC4Container:
    def test_empty_components(self) -> None:
        result = render_c4_container([], [])
        assert isinstance(result, C4Diagram)
        assert result.level == "container"
        assert result.component_ids == []

    def test_single_service(self, api_service: Component) -> None:
        result = render_c4_container([api_service], [])
        assert result.level == "container"
        sid = _safe_id("svc-api")
        assert sid in result.mermaid
        assert "API Service" in result.mermaid
        assert "service" in result.mermaid

    def test_database_shape(self, db_component: Component) -> None:
        result = render_c4_container([db_component], [])
        # Database uses cylindrical shape [(" ")]
        assert '[("' in result.mermaid

    def test_queue_shape(self, queue_component: Component) -> None:
        result = render_c4_container([queue_component], [])
        # Queue uses hexagon shape {{ }}
        assert "{{" in result.mermaid

    def test_library_grouped_separately(
        self,
        api_service: Component,
        lib_component: Component,
    ) -> None:
        result = render_c4_container([api_service, lib_component], [])
        assert "libs" in result.mermaid.lower()
        assert "library" in result.mermaid

    def test_sync_edge_solid(
        self,
        api_service: Component,
        db_component: Component,
        sync_integration: IntegrationPoint,
    ) -> None:
        result = render_c4_container(
            [api_service, db_component],
            [sync_integration],
        )
        assert "-->" in result.mermaid
        assert "SQL" in result.mermaid

    def test_async_edge_dashed(
        self,
        api_service: Component,
        queue_component: Component,
        async_integration: IntegrationPoint,
    ) -> None:
        result = render_c4_container(
            [api_service, queue_component],
            [async_integration],
        )
        assert "-.->" in result.mermaid
        assert "AMQP" in result.mermaid

    def test_boundary_grouping(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        result = render_c4_container(all_components, all_integrations)
        assert "subgraph" in result.mermaid
        assert len(result.component_ids) == len(all_components)


# ---------------------------------------------------------------------------
# Component diagram tests
# ---------------------------------------------------------------------------


class TestRenderC4Component:
    def test_empty_components(self) -> None:
        result = render_c4_component([], [])
        assert result.level == "component"
        assert result.component_ids == []

    def test_all_components(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        result = render_c4_component(all_components, all_integrations)
        assert result.level == "component"
        for c in all_components:
            assert _safe_id(c.id) in result.mermaid

    def test_scoped_to_component(
        self,
        api_service: Component,
        worker_component: Component,
        db_component: Component,
        sync_integration: IntegrationPoint,
    ) -> None:
        # api_service and worker_component share repo "my-app" but different boundary paths
        result = render_c4_component(
            [api_service, worker_component, db_component],
            [sync_integration],
            scope_component_id="svc-api",
        )
        assert result.scope == "svc-api"
        # Only components sharing the same primary boundary as svc-api
        assert _safe_id("svc-api") in result.mermaid

    def test_invalid_scope_id(self, api_service: Component) -> None:
        result = render_c4_component([api_service], [], scope_component_id="nonexistent")
        assert result.component_ids == []

    def test_internal_edges_shown(
        self,
        api_service: Component,
        db_component: Component,
        sync_integration: IntegrationPoint,
    ) -> None:
        # These have different boundaries so they won't be scoped together
        # but without scope_component_id they all show
        result = render_c4_component(
            [api_service, db_component],
            [sync_integration],
        )
        assert "-->" in result.mermaid
        assert "SQL" in result.mermaid

    def test_custom_title(self, api_service: Component) -> None:
        result = render_c4_component([api_service], [], title="API Internals")
        assert result.title == "API Internals"

    def test_grouped_by_boundary(
        self,
        api_service: Component,
        db_component: Component,
    ) -> None:
        result = render_c4_component([api_service, db_component], [])
        # Should have subgraphs for different boundary paths
        assert result.mermaid.count("subgraph") == 2  # services/api and infra/db


# ---------------------------------------------------------------------------
# Code diagram tests
# ---------------------------------------------------------------------------


class TestRenderC4Code:
    def test_empty_components(self) -> None:
        result = render_c4_code([])
        assert result.level == "code"
        assert result.component_ids == []
        assert "flowchart TD" in result.mermaid

    def test_single_component(self, api_service: Component) -> None:
        result = render_c4_code([api_service])
        assert result.level == "code"
        assert "services/api" in result.mermaid
        assert "API Service" in result.mermaid
        assert "FastAPI" in result.mermaid

    def test_tech_stack_included(self, api_service: Component) -> None:
        result = render_c4_code([api_service])
        assert "FastAPI" in result.mermaid

    def test_directory_subgraphs(
        self,
        api_service: Component,
        db_component: Component,
    ) -> None:
        result = render_c4_code([api_service, db_component])
        assert "subgraph" in result.mermaid
        assert "services/api" in result.mermaid
        assert "infra/db" in result.mermaid

    def test_no_boundary_uses_root(self, external_system: Component) -> None:
        result = render_c4_code([external_system])
        assert "Project Root" in result.mermaid

    def test_custom_title(self, api_service: Component) -> None:
        result = render_c4_code([api_service], title="Code Map")
        assert result.title == "Code Map"


# ---------------------------------------------------------------------------
# generate_all_diagrams tests
# ---------------------------------------------------------------------------


class TestGenerateAllDiagrams:
    def test_returns_three_diagrams_flat(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        diagrams = generate_all_diagrams(all_components, all_integrations, diagram_mode="flat")
        assert len(diagrams) == 3
        assert diagrams[0].level == "context"
        assert diagrams[1].level == "container"
        assert diagrams[2].level == "component"

    def test_all_are_c4diagram(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        diagrams = generate_all_diagrams(all_components, all_integrations)
        for d in diagrams:
            assert isinstance(d, C4Diagram)
            assert d.mermaid.startswith("flowchart TD")

    def test_empty_input(self) -> None:
        diagrams = generate_all_diagrams([], [])
        assert len(diagrams) == 3
        for d in diagrams:
            assert d.component_ids == []

    def test_coverage_annotations(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        coverage = [
            ComponentTestCoverage(
                component_id="svc-api",
                functional_coverage="adequate",
                nonfunctional_coverage="partial",
            ),
            ComponentTestCoverage(
                component_id="db-main",
                functional_coverage="none",
                nonfunctional_coverage="none",
            ),
        ]
        diagrams = generate_all_diagrams(all_components, all_integrations, coverage=coverage)
        container_diag = diagrams[1]
        # Should have classDef lines for coverage
        assert "classDef" in container_diag.mermaid
        assert "covNone" in container_diag.mermaid
        assert "covPartial" in container_diag.mermaid

    def test_coverage_colors_applied(
        self,
        api_service: Component,
    ) -> None:
        coverage = [
            ComponentTestCoverage(
                component_id="svc-api",
                functional_coverage="comprehensive",
                nonfunctional_coverage="comprehensive",
            ),
        ]
        diagrams = generate_all_diagrams([api_service], [], coverage=coverage)
        container_diag = diagrams[1]
        assert "covComprehensive" in container_diag.mermaid
        assert f"class {_safe_id('svc-api')} covComprehensive" in container_diag.mermaid

    def test_no_coverage_no_classdefs(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        diagrams = generate_all_diagrams(all_components, all_integrations, coverage=None)
        container_diag = diagrams[1]
        assert "classDef" not in container_diag.mermaid


# ---------------------------------------------------------------------------
# Component overview diagram tests
# ---------------------------------------------------------------------------


class TestRenderC4ComponentOverview:
    def test_empty_components(self) -> None:
        result = render_c4_component_overview([], [])
        assert result.level == "component"
        assert result.scope == "overview"
        assert result.component_ids == []

    def test_groups_collapsed(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        result = render_c4_component_overview(all_components, all_integrations)
        assert result.scope == "overview"
        assert "subgraph" not in result.mermaid
        assert "services/api" in result.mermaid
        assert "infra/db" in result.mermaid
        assert "infra/queue" in result.mermaid

    def test_inter_group_edges(
        self,
        api_service: Component,
        db_component: Component,
        sync_integration: IntegrationPoint,
    ) -> None:
        result = render_c4_component_overview(
            [api_service, db_component],
            [sync_integration],
        )
        assert "-->" in result.mermaid

    def test_intra_group_edges_excluded(self) -> None:
        comp_a = Component(
            id="svc-a",
            name="A",
            description="A",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="directory", path="services")],
        )
        comp_b = Component(
            id="svc-b",
            name="B",
            description="B",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="directory", path="services")],
        )
        integ = IntegrationPoint(
            id="int-ab",
            source_component_id="svc-a",
            target_component_id="svc-b",
            style="synchronous",
        )
        result = render_c4_component_overview([comp_a, comp_b], [integ])
        assert "-->" not in result.mermaid

    def test_deduplicates_inter_group_edges(
        self,
        api_service: Component,
        db_component: Component,
    ) -> None:
        integ1 = IntegrationPoint(
            id="int-1",
            source_component_id="svc-api",
            target_component_id="db-main",
            style="synchronous",
        )
        integ2 = IntegrationPoint(
            id="int-2",
            source_component_id="svc-api",
            target_component_id="db-main",
            style="synchronous",
        )
        result = render_c4_component_overview(
            [api_service, db_component],
            [integ1, integ2],
        )
        assert result.mermaid.count("-->") == 1

    def test_group_count_in_label(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        result = render_c4_component_overview(all_components, all_integrations)
        assert "(1)" in result.mermaid

    def test_root_named_sensibly(self) -> None:
        comp = Component(
            id="svc-root",
            name="Root Service",
            description="Lives at root",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="repo", path=".")],
        )
        result = render_c4_component_overview([comp], [])
        assert "Project Root" in result.mermaid

    def test_dot_slash_root_normalized(self) -> None:
        comp = Component(
            id="svc-root",
            name="Root Service",
            description="Lives at root",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="directory", path="./")],
        )
        result = render_c4_component_overview([comp], [])
        assert "Project Root" in result.mermaid
        assert "./" not in result.mermaid

    def test_dot_slash_prefix_stripped(self) -> None:
        comp = Component(
            id="svc-web",
            name="Web Service",
            description="Frontend",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="directory", path="./src/web")],
        )
        result = render_c4_component_overview([comp], [])
        assert "src/web" in result.mermaid
        assert "./src/web" not in result.mermaid


# ---------------------------------------------------------------------------
# Component detail diagram tests
# ---------------------------------------------------------------------------


class TestRenderC4ComponentDetail:
    def test_empty_focus_group(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        result = render_c4_component_detail(
            all_components, all_integrations, "nonexistent/path"
        )
        assert result.component_ids == []

    def test_focus_group_expanded(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        result = render_c4_component_detail(all_components, all_integrations, "services/api")
        assert "subgraph" in result.mermaid
        assert "API Service" in result.mermaid
        assert result.scope == "services/api"
        assert "svc-api" in result.component_ids

    def test_external_groups_as_stubs(
        self,
        api_service: Component,
        db_component: Component,
        sync_integration: IntegrationPoint,
    ) -> None:
        result = render_c4_component_detail(
            [api_service, db_component],
            [sync_integration],
            "services/api",
        )
        assert "infra/db" in result.mermaid
        assert "stroke-dasharray" in result.mermaid

    def test_internal_edges_shown(self) -> None:
        comp_a = Component(
            id="svc-a",
            name="A",
            description="A",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="directory", path="services")],
        )
        comp_b = Component(
            id="svc-b",
            name="B",
            description="B",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="directory", path="services")],
        )
        integ = IntegrationPoint(
            id="int-ab",
            source_component_id="svc-a",
            target_component_id="svc-b",
            style="synchronous",
            protocol="gRPC",
        )
        result = render_c4_component_detail([comp_a, comp_b], [integ], "services")
        assert "-->" in result.mermaid
        assert "gRPC" in result.mermaid

    def test_cross_edges_to_stubs(
        self,
        api_service: Component,
        db_component: Component,
        queue_component: Component,
        sync_integration: IntegrationPoint,
        async_integration: IntegrationPoint,
    ) -> None:
        result = render_c4_component_detail(
            [api_service, db_component, queue_component],
            [sync_integration, async_integration],
            "services/api",
        )
        assert "-->" in result.mermaid
        assert "-.->" in result.mermaid

    def test_title_includes_group_name(
        self,
        api_service: Component,
    ) -> None:
        result = render_c4_component_detail([api_service], [], "services/api")
        assert "services/api" in result.title


# ---------------------------------------------------------------------------
# generate_all_diagrams hierarchical mode tests
# ---------------------------------------------------------------------------


class TestGenerateAllDiagramsHierarchical:
    def test_hierarchical_mode_multi_group(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        diagrams = generate_all_diagrams(
            all_components, all_integrations, diagram_mode="hierarchical"
        )
        levels = [d.level for d in diagrams]
        assert levels[0] == "context"
        assert levels[1] == "container"
        assert any(d.scope == "overview" for d in diagrams)
        assert len(diagrams) > 3

    def test_flat_mode_unchanged(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        diagrams = generate_all_diagrams(all_components, all_integrations, diagram_mode="flat")
        assert len(diagrams) == 3
        assert diagrams[2].level == "component"
        assert diagrams[2].scope is None

    def test_single_group_falls_back_to_flat(self) -> None:
        comps = [
            Component(
                id="svc-a",
                name="A",
                description="A",
                component_type="service",
                boundaries=[ComponentBoundary(boundary_type="directory", path="services")],
            ),
            Component(
                id="svc-b",
                name="B",
                description="B",
                component_type="service",
                boundaries=[ComponentBoundary(boundary_type="directory", path="services")],
            ),
        ]
        diagrams = generate_all_diagrams(comps, [], diagram_mode="hierarchical")
        assert len(diagrams) == 3

    def test_detail_count_matches_groups(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        from nfr_review.arch_diagrams import _group_components_by_boundary

        groups = _group_components_by_boundary(all_components)
        diagrams = generate_all_diagrams(
            all_components, all_integrations, diagram_mode="hierarchical"
        )
        detail_diagrams = [
            d for d in diagrams if d.level == "component" and d.scope != "overview"
        ]
        assert len(detail_diagrams) == len(groups)


# ---------------------------------------------------------------------------
# Multi-repo with cross-repo integrations
# ---------------------------------------------------------------------------


class TestMultiRepo:
    def test_cross_repo_context(self) -> None:
        comp_a = Component(
            id="svc-a",
            name="Service A",
            description="Service in repo-1",
            component_type="service",
            repo="repo-1",
            boundaries=[ComponentBoundary(boundary_type="repo", path=".", repo="repo-1")],
        )
        comp_b = Component(
            id="svc-b",
            name="Service B",
            description="Service in repo-2",
            component_type="service",
            repo="repo-2",
            boundaries=[ComponentBoundary(boundary_type="repo", path=".", repo="repo-2")],
        )
        integ = IntegrationPoint(
            id="int-ab",
            source_component_id="svc-a",
            target_component_id="svc-b",
            style="synchronous",
            protocol="gRPC",
            is_cross_repo=True,
        )
        # At context level, both internal — edge skipped
        result = render_c4_context([comp_a, comp_b], [integ])
        assert result.level == "context"

    def test_cross_repo_container(self) -> None:
        comp_a = Component(
            id="svc-a",
            name="Service A",
            description="Service in repo-1",
            component_type="service",
            repo="repo-1",
            boundaries=[ComponentBoundary(boundary_type="repo", path=".", repo="repo-1")],
        )
        comp_b = Component(
            id="svc-b",
            name="Service B",
            description="Service in repo-2",
            component_type="service",
            repo="repo-2",
            boundaries=[ComponentBoundary(boundary_type="repo", path=".", repo="repo-2")],
        )
        integ = IntegrationPoint(
            id="int-ab",
            source_component_id="svc-a",
            target_component_id="svc-b",
            style="synchronous",
            protocol="gRPC",
            is_cross_repo=True,
        )
        result = render_c4_container([comp_a, comp_b], [integ])
        # Should show both repos as separate subgraphs
        assert "repo-1" in result.mermaid or "repo_1" in result.mermaid
        assert "repo-2" in result.mermaid or "repo_2" in result.mermaid
        assert "gRPC" in result.mermaid


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_component_with_no_boundaries(self) -> None:
        comp = Component(
            id="orphan",
            name="Orphan Service",
            description="No boundaries defined",
            component_type="service",
        )
        # Should still work, using default grouping
        result = render_c4_container([comp], [])
        assert _safe_id("orphan") in result.mermaid

    def test_special_chars_in_name(self) -> None:
        comp = Component(
            id="svc-my.special/name",
            name='Service "Special" <v2>',
            description="Has special characters",
            component_type="service",
        )
        result = render_c4_container([comp], [])
        # Should not break Mermaid syntax
        assert _safe_id("svc-my.special/name") in result.mermaid
        assert "#quot;" in result.mermaid  # escaped quote

    def test_integration_with_missing_component(self) -> None:
        comp = Component(
            id="svc-a",
            name="Service A",
            description="Only component",
            component_type="service",
        )
        integ = IntegrationPoint(
            id="int-orphan",
            source_component_id="svc-a",
            target_component_id="svc-nonexistent",
            style="synchronous",
        )
        # Container filters out edges with missing endpoints
        result = render_c4_container([comp], [integ])
        assert "-->" not in result.mermaid.split("end\n", 1)[-1]

    def test_event_driven_dashed(self) -> None:
        comp_a = Component(
            id="svc-a",
            name="A",
            description="A",
            component_type="service",
        )
        comp_b = Component(
            id="svc-b",
            name="B",
            description="B",
            component_type="worker",
        )
        integ = IntegrationPoint(
            id="int-evt",
            source_component_id="svc-a",
            target_component_id="svc-b",
            style="event_driven",
            protocol="Kafka",
        )
        result = render_c4_container([comp_a, comp_b], [integ])
        assert "-.->" in result.mermaid
        assert "async" in result.mermaid

    def test_message_queue_style_dashed(self) -> None:
        comp_a = Component(
            id="svc-a",
            name="A",
            description="A",
            component_type="service",
        )
        comp_b = Component(
            id="svc-b",
            name="B",
            description="B",
            component_type="worker",
        )
        integ = IntegrationPoint(
            id="int-mq",
            source_component_id="svc-a",
            target_component_id="svc-b",
            style="message_queue",
            protocol="RabbitMQ",
        )
        result = render_c4_container([comp_a, comp_b], [integ])
        assert "-.->" in result.mermaid

    def test_integration_no_protocol_uses_description(self) -> None:
        comp_a = Component(
            id="svc-a",
            name="A",
            description="A",
            component_type="service",
        )
        comp_b = Component(
            id="svc-b",
            name="B",
            description="B",
            component_type="service",
        )
        integ = IntegrationPoint(
            id="int-nop",
            source_component_id="svc-a",
            target_component_id="svc-b",
            style="synchronous",
            description="Internal call to process data",
        )
        result = render_c4_container([comp_a, comp_b], [integ])
        assert "Internal call to process dat" in result.mermaid  # truncated to 30 chars

    def test_c4diagram_fields_populated(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        """Verify all returned C4Diagram objects have correct fields."""
        ctx = render_c4_context(all_components, all_integrations)
        assert ctx.level == "context"
        assert ctx.title == "System Context"
        assert ctx.scope == "system"
        assert len(ctx.component_ids) == len(all_components)

        ctr = render_c4_container(all_components, all_integrations)
        assert ctr.level == "container"
        assert ctr.title == "Container Diagram"
        assert ctr.scope == "containers"

        cmp = render_c4_component(all_components, all_integrations)
        assert cmp.level == "component"
        assert cmp.title == "Component Diagram"

        code = render_c4_code(all_components)
        assert code.level == "code"
        assert code.title == "Code Diagram"
        assert code.scope == "code"

    def test_coverage_worst_of_both(self) -> None:
        """Coverage map picks worst of functional vs nonfunctional."""
        comp = Component(
            id="svc-x",
            name="X",
            description="X",
            component_type="service",
        )
        coverage = [
            ComponentTestCoverage(
                component_id="svc-x",
                functional_coverage="comprehensive",
                nonfunctional_coverage="minimal",
            ),
        ]
        diagrams = generate_all_diagrams([comp], [], coverage=coverage)
        container = diagrams[1]
        # Should pick "minimal" (worse of the two)
        assert "covMinimal" in container.mermaid


# ---------------------------------------------------------------------------
# Package boundary helper tests
# ---------------------------------------------------------------------------


class TestPackageBoundary:
    def test_returns_package_path(self) -> None:
        comp = Component(
            id="svc-a",
            name="A",
            description="A",
            component_type="service",
            boundaries=[
                ComponentBoundary(boundary_type="module", path="module-a"),
                ComponentBoundary(boundary_type="package", path="com.example"),
            ],
        )
        assert _package_boundary(comp) == "com.example"

    def test_returns_none_without_package(self) -> None:
        comp = Component(
            id="svc-a",
            name="A",
            description="A",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="module", path="module-a")],
        )
        assert _package_boundary(comp) is None

    def test_returns_none_no_boundaries(self) -> None:
        comp = Component(
            id="svc-a",
            name="A",
            description="A",
            component_type="service",
        )
        assert _package_boundary(comp) is None


# ---------------------------------------------------------------------------
# Package nesting in diagram tests
# ---------------------------------------------------------------------------


def _make_pkg_component(
    comp_id: str,
    name: str,
    boundary_path: str,
    package: str | None = None,
    component_type: str = "service",
    repo: str = "my-app",
) -> Component:
    """Helper to create a component with optional package boundary."""
    boundaries = [ComponentBoundary(boundary_type="module", path=boundary_path, repo=repo)]
    if package is not None:
        boundaries.append(ComponentBoundary(boundary_type="package", path=package, repo=repo))
    return Component(
        id=comp_id,
        name=name,
        description=f"{name} component",
        component_type=component_type,
        boundaries=boundaries,
        repo=repo,
    )


class TestPackageNestingInComponent:
    def test_components_with_packages_produce_nested_subgraphs(self) -> None:
        comp_a = _make_pkg_component("svc-a", "User API", "services", package="com.example")
        comp_b = _make_pkg_component("svc-b", "Order API", "services", package="com.example")
        result = render_c4_component([comp_a, comp_b], [])
        assert "com.example" in result.mermaid
        assert result.mermaid.count("subgraph") == 2  # outer group + package

    def test_different_packages_produce_separate_subgraphs(self) -> None:
        comp_a = _make_pkg_component("svc-a", "User API", "services", package="com.example")
        comp_b = _make_pkg_component("svc-b", "Connector", "services", package="org.other")
        result = render_c4_component([comp_a, comp_b], [])
        assert "com.example" in result.mermaid
        assert "org.other" in result.mermaid
        assert result.mermaid.count("subgraph") == 3  # outer group + 2 packages

    def test_mixed_package_and_no_package(self) -> None:
        comp_a = _make_pkg_component("svc-a", "User API", "services", package="com.example")
        comp_b = _make_pkg_component("svc-b", "Legacy", "services", package=None)
        result = render_c4_component([comp_a, comp_b], [])
        assert "com.example" in result.mermaid
        assert "User API" in result.mermaid
        assert "Legacy" in result.mermaid

    def test_no_packages_renders_flat(self) -> None:
        comp_a = _make_pkg_component("svc-a", "A", "services", package=None)
        comp_b = _make_pkg_component("svc-b", "B", "services", package=None)
        result = render_c4_component([comp_a, comp_b], [])
        assert result.mermaid.count("subgraph") == 1  # only the boundary group

    def test_edges_still_work_with_nesting(self) -> None:
        comp_a = _make_pkg_component("svc-a", "User API", "services", package="com.example")
        comp_b = _make_pkg_component("svc-b", "Order API", "services", package="com.example")
        integ = IntegrationPoint(
            id="int-ab",
            source_component_id="svc-a",
            target_component_id="svc-b",
            style="synchronous",
            protocol="gRPC",
        )
        result = render_c4_component([comp_a, comp_b], [integ])
        assert "-->" in result.mermaid
        assert "gRPC" in result.mermaid


class TestPackageNestingInContainer:
    def test_container_nests_by_package(self) -> None:
        comp_a = _make_pkg_component("svc-a", "User API", "services", package="com.example")
        comp_b = _make_pkg_component("svc-b", "Order API", "services", package="com.example")
        result = render_c4_container([comp_a, comp_b], [])
        assert "com.example" in result.mermaid

    def test_container_no_packages_flat(self) -> None:
        comp_a = _make_pkg_component("svc-a", "A", "services", package=None)
        comp_b = _make_pkg_component("svc-b", "B", "services", package=None)
        result = render_c4_container([comp_a, comp_b], [])
        # Only the boundary group subgraph, no package subgraphs
        assert result.mermaid.count("subgraph") == 1


class TestPackageNestingInDetail:
    def test_detail_nests_by_package(self) -> None:
        comp_a = _make_pkg_component("svc-a", "User API", "services", package="com.example")
        comp_b = _make_pkg_component("svc-b", "Order API", "services", package="com.example")
        result = render_c4_component_detail([comp_a, comp_b], [], "services")
        assert "com.example" in result.mermaid
        assert result.mermaid.count("subgraph") == 2  # focus group + package

    def test_detail_multiple_packages(self) -> None:
        comp_a = _make_pkg_component("svc-a", "User API", "services", package="com.example")
        comp_b = _make_pkg_component("svc-b", "Connector", "services", package="org.other")
        result = render_c4_component_detail([comp_a, comp_b], [], "services")
        assert "com.example" in result.mermaid
        assert "org.other" in result.mermaid
        assert result.mermaid.count("subgraph") == 3  # focus group + 2 packages


class TestPackageNestingInCode:
    def test_code_nests_by_package(self) -> None:
        comp_a = _make_pkg_component("svc-a", "User API", "services", package="com.example")
        comp_b = _make_pkg_component("svc-b", "Order API", "services", package="com.example")
        result = render_c4_code([comp_a, comp_b])
        assert "com.example" in result.mermaid
        assert result.mermaid.count("subgraph") == 2  # dir group + package

    def test_code_no_packages_flat(self) -> None:
        comp_a = _make_pkg_component("svc-a", "A", "services", package=None)
        comp_b = _make_pkg_component("svc-b", "B", "services", package=None)
        result = render_c4_code([comp_a, comp_b])
        assert result.mermaid.count("subgraph") == 1


# ---------------------------------------------------------------------------
# Environment-based infrastructure grouping in container diagram
# ---------------------------------------------------------------------------


class TestContainerEnvironmentGrouping:
    def test_infra_grouped_by_environment(self) -> None:
        app = Component(
            id="comp-app-001",
            name="My App",
            description="Main service",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="directory", path=".")],
        )
        prod_db = Component(
            id="infra-prod-db-aaa",
            name="Prod DB",
            description="Production database",
            component_type="database",
            environment="prod",
        )
        dev_db = Component(
            id="infra-dev-db-bbb",
            name="Dev DB",
            description="Development database",
            component_type="database",
            environment="dev",
        )
        intg = IntegrationPoint(
            id="intg-001",
            source_component_id=app.id,
            target_component_id=prod_db.id,
            style="shared_database",
            protocol="postgresql",
        )

        result = render_c4_container([app, prod_db, dev_db], [intg])
        assert "Production Infrastructure" in result.mermaid
        assert "Development Infrastructure" in result.mermaid
        assert prod_db.id.replace("-", "_") in _safe_id(prod_db.id)

    def test_no_env_components_in_boundary_groups(self) -> None:
        """Components without environment go into boundary groups, not infra groups."""
        app = Component(
            id="comp-app-001",
            name="My App",
            description="Main service",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="directory", path="services")],
        )
        result = render_c4_container([app], [])
        assert "Infrastructure" not in result.mermaid
        assert "services" in result.mermaid

    def test_edges_render_with_materialized_infra(self) -> None:
        """Edges to infra components render when both endpoints exist."""
        app = Component(
            id="comp-app-001",
            name="My App",
            description="Main service",
            component_type="service",
            boundaries=[ComponentBoundary(boundary_type="directory", path=".")],
        )
        prod_db = Component(
            id="infra-prod-db-aaa",
            name="Prod DB",
            description="Production database",
            component_type="database",
            environment="prod",
        )
        intg = IntegrationPoint(
            id="intg-001",
            source_component_id=app.id,
            target_component_id=prod_db.id,
            style="shared_database",
            protocol="postgresql",
        )
        result = render_c4_container([app, prod_db], [intg])
        assert "-->" in result.mermaid


# ===================================================================
# Class Diagram Tests
# ===================================================================

_SAMPLE_CLASSES = [
    {
        "name": "AudioProcessor",
        "line": 1,
        "has_destructor": True,
        "is_struct": False,
        "base_classes": [],
        "methods": [
            {
                "name": "processBlock",
                "return_type": "void",
                "access": "public",
                "is_virtual": True,
                "is_pure_virtual": True,
                "line": 3,
            },
            {
                "name": "getName",
                "return_type": "char",
                "access": "public",
                "is_virtual": True,
                "is_pure_virtual": True,
                "line": 4,
            },
        ],
        "fields": [
            {"name": "sampleRate_", "type": "int", "access": "protected", "line": 7},
        ],
        "is_abstract": True,
    },
    {
        "name": "PluginProcessor",
        "line": 10,
        "has_destructor": False,
        "is_struct": False,
        "base_classes": [{"name": "AudioProcessor", "access": "public"}],
        "methods": [
            {
                "name": "processBlock",
                "return_type": "void",
                "access": "public",
                "is_virtual": False,
                "is_pure_virtual": False,
                "line": 12,
            },
        ],
        "fields": [
            {"name": "gain_", "type": "float", "access": "private", "line": 15},
        ],
        "is_abstract": False,
    },
    {
        "name": "Config",
        "line": 20,
        "has_destructor": False,
        "is_struct": True,
        "base_classes": [],
        "methods": [],
        "fields": [
            {"name": "value", "type": "int", "access": "public", "line": 21},
        ],
        "is_abstract": False,
    },
]


class TestClassDiagram:
    def test_empty_input(self) -> None:
        result = render_class_diagram([])
        assert result.level == "code"
        assert result.mermaid == "classDiagram\n"

    def test_starts_with_class_diagram(self) -> None:
        result = render_class_diagram(_SAMPLE_CLASSES)
        assert result.mermaid.startswith("classDiagram\n")

    def test_abstract_annotation(self) -> None:
        result = render_class_diagram(_SAMPLE_CLASSES)
        assert "<<abstract>> AudioProcessor" in result.mermaid

    def test_struct_annotation(self) -> None:
        result = render_class_diagram(_SAMPLE_CLASSES)
        assert "<<struct>> Config" in result.mermaid

    def test_inheritance_edge(self) -> None:
        result = render_class_diagram(_SAMPLE_CLASSES)
        assert "AudioProcessor <|-- PluginProcessor" in result.mermaid

    def test_method_with_access(self) -> None:
        result = render_class_diagram(_SAMPLE_CLASSES)
        assert "+processBlock()" in result.mermaid

    def test_pure_virtual_marker(self) -> None:
        result = render_class_diagram(_SAMPLE_CLASSES)
        assert "+processBlock()* void" in result.mermaid

    def test_field_with_access(self) -> None:
        result = render_class_diagram(_SAMPLE_CLASSES)
        assert "#sampleRate_ int" in result.mermaid
        assert "-gain_ float" in result.mermaid

    def test_external_base_class(self) -> None:
        classes = [
            {
                "name": "MyWidget",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [{"name": "CView", "access": "public"}],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]
        result = render_class_diagram(classes)
        assert "<<external>> CView" in result.mermaid
        assert "CView <|-- MyWidget" in result.mermaid

    def test_custom_title(self) -> None:
        result = render_class_diagram(_SAMPLE_CLASSES, title="Plugin Classes")
        assert result.title == "Plugin Classes"

    def test_no_destructors_in_output(self) -> None:
        result = render_class_diagram(_SAMPLE_CLASSES)
        assert "~AudioProcessor" not in result.mermaid

    def test_generate_all_includes_class_diagram(self) -> None:
        comp = Component(
            id="test-comp",
            name="Test",
            description="Test component",
            component_type="library",
        )
        diagrams = generate_all_diagrams([comp], [], class_data=_SAMPLE_CLASSES)
        class_diagrams = [d for d in diagrams if d.scope == "classes"]
        assert len(class_diagrams) == 1
        assert "classDiagram" in class_diagrams[0].mermaid

    def test_generate_all_no_class_data(self) -> None:
        comp = Component(
            id="test-comp",
            name="Test",
            description="Test component",
            component_type="library",
        )
        diagrams = generate_all_diagrams([comp], [])
        class_diagrams = [d for d in diagrams if d.scope == "classes"]
        assert len(class_diagrams) == 0


class TestPipelineDiagram:
    def test_multi_stage_dag(self) -> None:
        pipeline = DvcPipeline(
            stages=[
                DvcStage(name="prepare", cmd="python prepare.py", outs=["prepared/"]),
                DvcStage(
                    name="train", cmd="python train.py", deps=["prepared/"], outs=["model.pt"]
                ),
                DvcStage(name="export", cmd="python export.py", deps=["model.pt"]),
            ],
            edges=[("prepare", "train"), ("train", "export")],
        )

        diagram = render_pipeline_diagram(pipeline)
        assert diagram.level == "code"
        assert diagram.scope == "pipeline"
        assert "flowchart TD" in diagram.mermaid
        assert "prepare" in diagram.mermaid
        assert "train" in diagram.mermaid
        assert "export" in diagram.mermaid
        assert "python prepare.py" in diagram.mermaid
        assert "prepare --> train" in diagram.mermaid
        assert "train --> export" in diagram.mermaid

    def test_single_stage(self) -> None:
        pipeline = DvcPipeline(
            stages=[DvcStage(name="train", cmd="python train.py")],
            edges=[],
        )

        diagram = render_pipeline_diagram(pipeline)
        assert "train" in diagram.mermaid
        assert "-->" not in diagram.mermaid

    def test_empty_pipeline(self) -> None:
        pipeline = DvcPipeline(stages=[], edges=[])
        diagram = render_pipeline_diagram(pipeline)
        assert diagram.mermaid == "flowchart TD\n"

    def test_long_cmd_truncated(self) -> None:
        long_cmd = (
            "python -m training.run --epochs=100"
            " --batch-size=32 --learning-rate=0.001 --output=model.pt"
        )
        pipeline = DvcPipeline(
            stages=[DvcStage(name="train", cmd=long_cmd)],
            edges=[],
        )

        diagram = render_pipeline_diagram(pipeline)
        assert "..." in diagram.mermaid
        assert long_cmd not in diagram.mermaid

    def test_custom_title(self) -> None:
        pipeline = DvcPipeline(
            stages=[DvcStage(name="train", cmd="python train.py")],
            edges=[],
        )
        diagram = render_pipeline_diagram(pipeline, title="Training Pipeline")
        assert diagram.title == "Training Pipeline"

    def test_generate_all_with_pipeline_data(self) -> None:
        comp = Component(
            id="test-comp",
            name="Test",
            description="Test component",
            component_type="library",
        )
        pipeline = DvcPipeline(
            stages=[
                DvcStage(name="prepare", cmd="python prepare.py", outs=["data/"]),
                DvcStage(name="train", cmd="python train.py", deps=["data/"]),
            ],
            edges=[("prepare", "train")],
        )
        diagrams = generate_all_diagrams([comp], [], pipeline_data=[pipeline])
        pipeline_diagrams = [d for d in diagrams if d.scope == "pipeline"]
        assert len(pipeline_diagrams) == 1
        assert "prepare" in pipeline_diagrams[0].mermaid

    def test_generate_all_no_pipeline_data(self) -> None:
        comp = Component(
            id="test-comp",
            name="Test",
            description="Test component",
            component_type="library",
        )
        diagrams = generate_all_diagrams([comp], [])
        pipeline_diagrams = [d for d in diagrams if d.scope == "pipeline"]
        assert len(pipeline_diagrams) == 0
