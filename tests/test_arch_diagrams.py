# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for C4 architecture diagram generation."""

from __future__ import annotations

import json
import re as _re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from nfr_review.arch_diagrams import (
    OrphanNode,
    _package_boundary,
    _safe_id,
    _sanitize_member_type,
    detect_orphan_nodes,
    generate_all_diagrams,
    partition_classes,
    render_c4_code,
    render_c4_component,
    render_c4_component_detail,
    render_c4_component_overview,
    render_c4_container,
    render_c4_context,
    render_class_diagram,
    render_orphans_markdown,
    render_partitioned_class_diagrams,
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
# _sanitize_member_type tests
# ---------------------------------------------------------------------------


class TestSanitizeMemberType:
    def test_double_colon_namespace(self) -> None:
        assert "::" not in _sanitize_member_type("std::vector")
        assert "std.vector" == _sanitize_member_type("std::vector")

    def test_angle_brackets(self) -> None:
        result = _sanitize_member_type("vector<int>")
        assert "<" not in result and ">" not in result

    def test_curly_braces(self) -> None:
        result = _sanitize_member_type("union { const void* p_data; int i; }")
        assert "{" not in result and "}" not in result

    def test_asterisk_pointer(self) -> None:
        result = _sanitize_member_type("void*")
        assert "*" not in result

    def test_semicolons_stripped(self) -> None:
        result = _sanitize_member_type("int;")
        assert ";" not in result

    def test_remaining_colon_stripped(self) -> None:
        result = _sanitize_member_type("std::index_sequence<I...>")
        assert ":" not in result

    def test_nested_template_with_namespaces(self) -> None:
        raw = "DispatcherImpl<Struct, std::index_sequence<Indices...>>"
        result = _sanitize_member_type(raw)
        assert ":" not in result
        assert "<" not in result
        assert ">" not in result

    def test_union_with_pointer_members(self) -> None:
        raw = "union { const void* p_data; size_t i_data; }"
        result = _sanitize_member_type(raw)
        assert "{" not in result
        assert "}" not in result
        assert "*" not in result
        assert ";" not in result

    def test_simple_type_unchanged(self) -> None:
        assert _sanitize_member_type("int") == "int"
        assert _sanitize_member_type("string") == "string"
        assert _sanitize_member_type("bool") == "bool"


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
        assert "<<abstract>>" in result.mermaid

    def test_struct_annotation(self) -> None:
        result = render_class_diagram(_SAMPLE_CLASSES)
        assert "<<struct>>" in result.mermaid

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

    def test_generate_all_splits_class_diagrams_by_language(self) -> None:
        comp = Component(
            id="test-comp",
            name="Test",
            description="Test component",
            component_type="library",
        )
        mixed_classes = [
            {
                "name": "CppWidget",
                "base_classes": [],
                "methods": [{"name": "render", "return_type": "void", "access": "public"}],
                "fields": [],
                "language": "C++",
            },
            {
                "name": "PyWidget",
                "base_classes": [],
                "methods": [{"name": "render", "return_type": "None", "access": "public"}],
                "fields": [],
                "language": "Python",
            },
        ]
        diagrams = generate_all_diagrams([comp], [], class_data=mixed_classes)
        class_diagrams = [d for d in diagrams if d.scope == "classes"]
        assert len(class_diagrams) == 2
        titles = {d.title for d in class_diagrams}
        assert "Class Diagram (C++)" in titles
        assert "Class Diagram (Python)" in titles
        cpp_diag = next(d for d in class_diagrams if "C++" in d.title)
        assert "CppWidget" in cpp_diag.mermaid
        assert "PyWidget" not in cpp_diag.mermaid
        py_diag = next(d for d in class_diagrams if "Python" in d.title)
        assert "PyWidget" in py_diag.mermaid
        assert "CppWidget" not in py_diag.mermaid

    def test_multiline_type_collapsed_to_single_line(self) -> None:
        classes = [
            {
                "name": "Widget",
                "fields": [
                    {
                        "name": "mode",
                        "type": "Literal<\n    fast, slow, auto\n>",
                        "access": "public",
                    },
                ],
                "methods": [],
                "base_classes": [],
            },
        ]
        result = render_class_diagram(classes)
        for line in result.mermaid.splitlines():
            if "mode" in line:
                assert "\n" not in line
                assert "Literal~" in line
                assert "fast" in line
                break
        else:
            pytest.fail("mode field not found in mermaid output")

    def test_class_count_capped(self) -> None:
        from nfr_review.arch_diagrams import _MAX_CLASSES_PER_DIAGRAM

        classes = [
            {
                "name": f"Cls{i}",
                "fields": [],
                "methods": [],
                "base_classes": [],
            }
            for i in range(_MAX_CLASSES_PER_DIAGRAM + 20)
        ]
        result = render_class_diagram(classes)
        declared = [
            line
            for line in result.mermaid.splitlines()
            if line.strip().startswith("class Cls")
        ]
        assert len(declared) == _MAX_CLASSES_PER_DIAGRAM

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


class TestClassDiagramRelationships:
    """Tests for composition, aggregation, and dependency edges."""

    @staticmethod
    def _make_classes() -> list[dict]:
        return [
            {
                "name": "Engine",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [
                    {
                        "name": "getConfig",
                        "return_type": "Config",
                        "access": "public",
                        "is_virtual": False,
                        "is_pure_virtual": False,
                        "line": 3,
                    },
                ],
                "fields": [
                    {"name": "state_", "type": "State", "access": "private", "line": 5},
                    {
                        "name": "logger_",
                        "type": "std::shared_ptr<Logger>",
                        "access": "private",
                        "line": 6,
                    },
                    {
                        "name": "items_",
                        "type": "std::vector<Item>",
                        "access": "private",
                        "line": 7,
                    },
                ],
                "is_abstract": False,
            },
            {
                "name": "State",
                "line": 20,
                "has_destructor": False,
                "is_struct": True,
                "base_classes": [],
                "methods": [],
                "fields": [
                    {"name": "count", "type": "int", "access": "public", "line": 21},
                ],
                "is_abstract": False,
            },
            {
                "name": "Logger",
                "line": 30,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "Config",
                "line": 40,
                "has_destructor": False,
                "is_struct": True,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "Item",
                "line": 50,
                "has_destructor": False,
                "is_struct": True,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]

    def test_composition_by_value(self) -> None:
        result = render_class_diagram(self._make_classes())
        assert "Engine *-- State" in result.mermaid

    def test_aggregation_shared_ptr(self) -> None:
        result = render_class_diagram(self._make_classes())
        assert "Engine o-- Logger" in result.mermaid

    def test_composition_vector_element(self) -> None:
        result = render_class_diagram(self._make_classes())
        assert "Engine *-- Item" in result.mermaid

    def test_dependency_from_return_type(self) -> None:
        result = render_class_diagram(self._make_classes())
        assert "Engine ..> Config" in result.mermaid

    def test_no_self_reference(self) -> None:
        classes = [
            {
                "name": "Node",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [
                    {"name": "next_", "type": "Node*", "access": "private", "line": 2},
                ],
                "is_abstract": False,
            },
        ]
        result = render_class_diagram(classes)
        assert "Node *--" not in result.mermaid
        assert "Node o--" not in result.mermaid

    def test_inheritance_suppresses_composition(self) -> None:
        classes = [
            {
                "name": "Base",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": True,
            },
            {
                "name": "Derived",
                "line": 10,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [{"name": "Base", "access": "public"}],
                "methods": [],
                "fields": [
                    {"name": "parent_", "type": "Base", "access": "private", "line": 11},
                ],
                "is_abstract": False,
            },
        ]
        result = render_class_diagram(classes)
        assert "Base <|-- Derived" in result.mermaid
        assert "*--" not in result.mermaid

    def test_no_edges_for_primitive_types(self) -> None:
        result = render_class_diagram(_SAMPLE_CLASSES)
        assert "*--" not in result.mermaid
        assert "o--" not in result.mermaid
        assert "..>" not in result.mermaid

    def test_dedup_multiple_fields_same_type(self) -> None:
        classes = [
            {
                "name": "Widget",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [
                    {"name": "a_", "type": "Config", "access": "private", "line": 2},
                    {"name": "b_", "type": "Config", "access": "private", "line": 3},
                ],
                "is_abstract": False,
            },
            {
                "name": "Config",
                "line": 10,
                "has_destructor": False,
                "is_struct": True,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]
        result = render_class_diagram(classes)
        assert result.mermaid.count("Widget *-- Config") == 1

    def test_pointer_field_is_aggregation(self) -> None:
        classes = [
            {
                "name": "View",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [
                    {"name": "ctrl_", "type": "Controller*", "access": "private", "line": 2},
                ],
                "is_abstract": False,
            },
            {
                "name": "Controller",
                "line": 10,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]
        result = render_class_diagram(classes)
        assert "View o-- Controller" in result.mermaid
        assert "*--" not in result.mermaid


class TestClassDiagramParameterDeps:
    """Tests for dependency edges derived from method parameter types."""

    @staticmethod
    def _make_classes() -> list[dict]:
        return [
            {
                "name": "Controller",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [
                    {
                        "name": "handleEvent",
                        "return_type": "void",
                        "access": "public",
                        "is_virtual": False,
                        "is_pure_virtual": False,
                        "line": 3,
                        "parameters": [
                            {"name": "msg", "type": "Message"},
                            {"name": "count", "type": "int"},
                        ],
                    },
                    {
                        "name": "processBuffer",
                        "return_type": "void",
                        "access": "public",
                        "is_virtual": False,
                        "is_pure_virtual": False,
                        "line": 4,
                        "parameters": [
                            {"name": "buf", "type": "AudioBuffer*"},
                        ],
                    },
                ],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "Message",
                "line": 20,
                "has_destructor": False,
                "is_struct": True,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "AudioBuffer",
                "line": 30,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]

    def test_param_type_creates_dependency(self) -> None:
        result = render_class_diagram(self._make_classes())
        assert "Controller ..> Message" in result.mermaid

    def test_pointer_param_creates_dependency(self) -> None:
        result = render_class_diagram(self._make_classes())
        assert "Controller ..> AudioBuffer" in result.mermaid

    def test_primitive_param_no_dependency(self) -> None:
        result = render_class_diagram(self._make_classes())
        lines = result.mermaid.splitlines()
        dep_lines = [ln for ln in lines if "..>" in ln]
        for ln in dep_lines:
            assert "int" not in ln.split("..>")[1]


class TestClassDiagramFriends:
    """Tests for friend class dependency edges."""

    @staticmethod
    def _make_classes() -> list[dict]:
        return [
            {
                "name": "Engine",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "friends": ["Inspector"],
            },
            {
                "name": "Inspector",
                "line": 20,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]

    def test_friend_creates_dependency(self) -> None:
        result = render_class_diagram(self._make_classes())
        assert 'Engine ..> Inspector : "friend"' in result.mermaid

    def test_friend_unknown_class_ignored(self) -> None:
        classes = [
            {
                "name": "Engine",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "friends": ["UnknownClass"],
            },
        ]
        result = render_class_diagram(classes)
        assert "friend" not in result.mermaid


class TestClassDiagramNestedClasses:
    """Tests for nested (inner) class edges."""

    @staticmethod
    def _make_classes() -> list[dict]:
        return [
            {
                "name": "Outer",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "Inner",
                "line": 5,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "outer_class": "Outer",
            },
        ]

    def test_nested_class_edge(self) -> None:
        result = render_class_diagram(self._make_classes())
        assert 'Outer *-- Inner : "inner"' in result.mermaid

    def test_nested_unknown_outer_ignored(self) -> None:
        classes = [
            {
                "name": "Orphan",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "outer_class": "Missing",
            },
        ]
        result = render_class_diagram(classes)
        assert "inner" not in result.mermaid


class TestClassDiagramNamespaceGrouping:
    """Tests for optional namespace grouping in class diagrams."""

    @staticmethod
    def _make_classes() -> list[dict]:
        return [
            {
                "name": "Processor",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "namespace": "audio",
            },
            {
                "name": "Buffer",
                "line": 10,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "namespace": "audio",
            },
            {
                "name": "Config",
                "line": 20,
                "has_destructor": False,
                "is_struct": True,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "namespace": "",
            },
        ]

    def test_namespace_grouping_enabled(self) -> None:
        result = render_class_diagram(self._make_classes(), group_by_namespace=True)
        assert "namespace audio {" in result.mermaid
        assert "Processor" in result.mermaid
        assert "Buffer" in result.mermaid

    def test_namespace_grouping_disabled(self) -> None:
        result = render_class_diagram(self._make_classes(), group_by_namespace=False)
        assert "namespace" not in result.mermaid

    def test_global_ns_classes_not_wrapped(self) -> None:
        result = render_class_diagram(self._make_classes(), group_by_namespace=True)
        assert "Config" in result.mermaid
        mermaid_before_ns = result.mermaid.split("namespace audio")[0]
        assert "Config" in mermaid_before_ns or "Config" in result.mermaid.split("}")[1]

    def test_nested_namespace_sanitized(self) -> None:
        classes = [
            {
                "name": "Widget",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "namespace": "ui::widgets",
            },
        ]
        result = render_class_diagram(classes, group_by_namespace=True)
        assert "namespace ui_widgets {" in result.mermaid

    def test_dotted_namespace_sanitized(self) -> None:
        classes = [
            {
                "name": "ArchReport",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "namespace": "src.nfr_review.arch_models",
            },
        ]
        result = render_class_diagram(classes, group_by_namespace=True)
        assert "namespace src_nfr_review_arch_models {" in result.mermaid
        assert "." not in result.mermaid.split("namespace")[1].split("{")[0]


class TestMultiRepoNamespaceGrouping:
    """When classes come from multiple repos, repo wraps as an outer namespace."""

    @staticmethod
    def _make_multi_repo_classes() -> list[dict]:
        return [
            {
                "name": "PluginProcessor",
                "line": 10,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [{"name": "process", "return_type": "void", "access": "public"}],
                "fields": [],
                "is_abstract": False,
                "namespace": "JKDigital",
                "repo": "drumcore",
            },
            {
                "name": "DrumEngine",
                "line": 20,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [{"name": "run", "return_type": "void", "access": "public"}],
                "fields": [],
                "is_abstract": False,
                "namespace": "JKDigital",
                "repo": "DrumGenerator",
            },
            {
                "name": "PostFilter",
                "line": 30,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [{"name": "cutoff", "type": "float", "access": "private"}],
                "is_abstract": False,
                "namespace": "JKDigital",
                "repo": "DrumPostProcessor",
            },
        ]

    def test_multi_repo_wraps_repo_as_outer_namespace(self) -> None:
        classes = self._make_multi_repo_classes()
        result = render_class_diagram(classes, group_by_namespace=True)
        assert "namespace drumcore {" in result.mermaid
        assert "namespace DrumGenerator {" in result.mermaid
        assert "namespace DrumPostProcessor {" in result.mermaid

    def test_multi_repo_nests_cpp_namespace_inside_repo(self) -> None:
        classes = self._make_multi_repo_classes()
        result = render_class_diagram(classes, group_by_namespace=True)
        lines = result.mermaid.splitlines()
        for i, line in enumerate(lines):
            if "namespace drumcore" in line:
                block = "\n".join(lines[i : i + 10])
                assert "namespace JKDigital {" in block
                break
        else:
            raise AssertionError("namespace drumcore not found")

    def test_multi_repo_classes_inside_correct_repo(self) -> None:
        classes = self._make_multi_repo_classes()
        result = render_class_diagram(classes, group_by_namespace=True)
        mermaid = result.mermaid
        gen_start = mermaid.index("namespace DrumGenerator")
        gen_end = mermaid.index("namespace DrumPostProcessor")
        gen_block = mermaid[gen_start:gen_end]
        assert "DrumEngine" in gen_block
        assert "PluginProcessor" not in gen_block

    def test_single_repo_no_repo_namespace(self) -> None:
        classes = [
            {
                "name": "Foo",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [{"name": "bar", "return_type": "int", "access": "public"}],
                "fields": [],
                "is_abstract": False,
                "namespace": "myns",
                "repo": "solo-repo",
            },
        ]
        result = render_class_diagram(classes, group_by_namespace=True)
        assert "namespace myns {" in result.mermaid
        assert "namespace solo_repo" not in result.mermaid

    def test_no_repo_field_falls_back_to_ns_only(self) -> None:
        classes = [
            {
                "name": "Bar",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [{"name": "baz", "return_type": "void", "access": "public"}],
                "fields": [],
                "is_abstract": False,
                "namespace": "ns1",
            },
        ]
        result = render_class_diagram(classes, group_by_namespace=True)
        assert "namespace ns1 {" in result.mermaid

    def test_multi_repo_without_namespace_grouping(self) -> None:
        classes = self._make_multi_repo_classes()
        result = render_class_diagram(classes, group_by_namespace=False)
        assert "namespace" not in result.mermaid

    def test_multi_repo_with_global_ns_classes(self) -> None:
        classes = [
            {
                "name": "Alpha",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [{"name": "go", "return_type": "void", "access": "public"}],
                "fields": [],
                "is_abstract": False,
                "namespace": "shared",
                "repo": "repoA",
            },
            {
                "name": "Beta",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [{"name": "run", "return_type": "void", "access": "public"}],
                "fields": [],
                "is_abstract": False,
                "namespace": "",
                "repo": "repoB",
            },
        ]
        result = render_class_diagram(classes, group_by_namespace=True)
        assert "namespace repoA {" in result.mermaid
        assert "namespace repoB {" in result.mermaid
        assert "namespace shared {" in result.mermaid
        assert "Beta" in result.mermaid

    def test_multi_repo_repo_name_sanitized(self) -> None:
        classes = [
            {
                "name": "Cls1",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [{"name": "m", "return_type": "void", "access": "public"}],
                "fields": [],
                "is_abstract": False,
                "namespace": "ns",
                "repo": "my-repo.v2",
            },
            {
                "name": "Cls2",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [{"name": "n", "return_type": "void", "access": "public"}],
                "fields": [],
                "is_abstract": False,
                "namespace": "ns",
                "repo": "other repo!",
            },
        ]
        result = render_class_diagram(classes, group_by_namespace=True)
        assert "namespace my_repo_v2 {" in result.mermaid
        assert "namespace other_repo_ {" in result.mermaid


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


# ---------------------------------------------------------------------------
# Class diagram partitioning
# ---------------------------------------------------------------------------


class TestClassPartitioning:
    def test_empty_input(self) -> None:
        assert partition_classes([]) == []

    def test_small_set_single_partition(self) -> None:
        classes = [
            {"name": f"Cls{i}", "fields": [], "methods": [], "base_classes": []}
            for i in range(10)
        ]
        parts = partition_classes(classes)
        assert len(parts) == 1
        assert len(parts[0].classes) == 10
        assert parts[0].diagram_index == 1

    def test_splits_when_over_limit(self) -> None:
        classes = [
            {"name": f"Cls{i}", "fields": [], "methods": [], "base_classes": []}
            for i in range(20)
        ]
        parts = partition_classes(classes, max_per_diagram=10)
        assert len(parts) >= 2
        total = sum(len(p.classes) for p in parts)
        assert total == 20

    def test_preserves_all_classes(self) -> None:
        from nfr_review.arch_diagrams import _MAX_CLASSES_PER_DIAGRAM

        classes = [
            {"name": f"Cls{i}", "fields": [], "methods": [], "base_classes": []}
            for i in range(_MAX_CLASSES_PER_DIAGRAM + 30)
        ]
        parts = partition_classes(classes)
        all_names = set()
        for p in parts:
            for c in p.classes:
                all_names.add(c["name"])
        expected = {f"Cls{i}" for i in range(_MAX_CLASSES_PER_DIAGRAM + 30)}
        assert all_names == expected

    def test_namespace_groups_stay_together(self) -> None:
        classes = []
        for i in range(8):
            classes.append(
                {
                    "name": f"A{i}",
                    "namespace": "audio",
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        for i in range(8):
            classes.append(
                {
                    "name": f"V{i}",
                    "namespace": "video",
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        parts = partition_classes(classes, max_per_diagram=10)
        assert len(parts) >= 2
        for part in parts:
            namespaces = {c.get("namespace", "") for c in part.classes}
            assert len(namespaces) == 1

    def test_indices_sequential(self) -> None:
        classes = [
            {"name": f"Cls{i}", "fields": [], "methods": [], "base_classes": []}
            for i in range(30)
        ]
        parts = partition_classes(classes, max_per_diagram=10)
        indices = [p.diagram_index for p in parts]
        assert indices == list(range(1, len(parts) + 1))

    def test_connected_classes_cluster(self) -> None:
        classes = []
        for i in range(12):
            fields = []
            if i > 0:
                fields = [{"name": "ref", "type": f"Cls{i - 1}", "access": "private"}]
            classes.append(
                {
                    "name": f"Cls{i}",
                    "fields": fields,
                    "methods": [],
                    "base_classes": [],
                }
            )
        parts = partition_classes(classes, max_per_diagram=8)
        assert len(parts) >= 2
        for part in parts:
            assert len(part.classes) > 0


class TestPartitionedClassDiagrams:
    def test_single_diagram_no_proxies(self) -> None:
        diagrams = render_partitioned_class_diagrams(_SAMPLE_CLASSES)
        assert len(diagrams) == 1
        assert "proxy_D" not in diagrams[0].mermaid

    def test_multi_diagram_has_proxies(self) -> None:
        classes = []
        for i in range(8):
            classes.append(
                {
                    "name": f"A{i}",
                    "namespace": "audio",
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        for i in range(8):
            classes.append(
                {
                    "name": f"V{i}",
                    "namespace": "video",
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        classes[0]["fields"] = [{"name": "video_ref", "type": "V0", "access": "private"}]

        diagrams = render_partitioned_class_diagrams(classes, max_per_diagram=10)
        assert len(diagrams) >= 2
        all_mermaid = "\n".join(d.mermaid for d in diagrams)
        assert "proxy_D" in all_mermaid
        assert "<<Diagram" in all_mermaid

    def test_outgoing_proxy_shows_target_class(self) -> None:
        classes = []
        for i in range(8):
            classes.append(
                {
                    "name": f"Src{i}",
                    "namespace": "src",
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        for i in range(8):
            classes.append(
                {
                    "name": f"Tgt{i}",
                    "namespace": "tgt",
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        classes[0]["fields"] = [{"name": "dep", "type": "Tgt0", "access": "private"}]

        diagrams = render_partitioned_class_diagrams(classes, max_per_diagram=10)
        src_diag = next(d for d in diagrams if "class Src0" in d.mermaid)
        assert "class Tgt0" not in src_diag.mermaid
        assert "to Tgt0" in src_diag.mermaid

    def test_incoming_proxy_shows_source_class(self) -> None:
        classes = []
        for i in range(8):
            classes.append(
                {
                    "name": f"Src{i}",
                    "namespace": "src",
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        for i in range(8):
            classes.append(
                {
                    "name": f"Tgt{i}",
                    "namespace": "tgt",
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        classes[0]["fields"] = [{"name": "dep", "type": "Tgt0", "access": "private"}]

        diagrams = render_partitioned_class_diagrams(classes, max_per_diagram=10)
        tgt_diag = next(d for d in diagrams if "class Tgt0" in d.mermaid)
        assert "from Src0" in tgt_diag.mermaid

    def test_cross_partition_proxy_sanitizes_cpp_names(self) -> None:
        """Class names with :: in proxy edge labels must be sanitized."""
        classes = []
        for i in range(8):
            name = (
                "std::DispatcherImpl<Struct, std::index_sequence<I>>" if i == 0 else f"Src{i}"
            )
            classes.append(
                {
                    "name": name,
                    "namespace": "src",
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        for i in range(8):
            classes.append(
                {
                    "name": f"Tgt{i}",
                    "namespace": "tgt",
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        classes[0]["fields"] = [{"name": "dep", "type": "Tgt0", "access": "private"}]

        diagrams = render_partitioned_class_diagrams(classes, max_per_diagram=10)
        all_mermaid = "\n".join(d.mermaid for d in diagrams)
        assert "::" not in all_mermaid
        assert "from std.DispatcherImpl" in all_mermaid

    def test_titles_include_index(self) -> None:
        classes = [
            {"name": f"Cls{i}", "fields": [], "methods": [], "base_classes": []}
            for i in range(20)
        ]
        diagrams = render_partitioned_class_diagrams(classes, max_per_diagram=10)
        for i, d in enumerate(diagrams, 1):
            assert f" {i}" in d.title

    def test_suppress_external_for_cross_partition_inheritance(self) -> None:
        classes = []
        for i in range(8):
            classes.append(
                {
                    "name": f"Base{i}",
                    "namespace": "base",
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        for i in range(8):
            base_ref = [{"name": "Base0", "access": "public"}] if i == 0 else []
            classes.append(
                {
                    "name": f"Derived{i}",
                    "namespace": "derived",
                    "fields": [],
                    "methods": [],
                    "base_classes": base_ref,
                }
            )

        diagrams = render_partitioned_class_diagrams(classes, max_per_diagram=10)
        derived_diag = next(d for d in diagrams if "class Derived0" in d.mermaid)
        assert "<<external>> Base0" not in derived_diag.mermaid
        assert "to Base0" in derived_diag.mermaid

    def test_generate_all_uses_partitioned(self) -> None:
        comp = Component(
            id="test-comp",
            name="Test",
            description="Test component",
            component_type="library",
        )
        classes = [
            {"name": f"Cls{i}", "fields": [], "methods": [], "base_classes": []}
            for i in range(70)
        ]
        diagrams = generate_all_diagrams([comp], [], class_data=classes)
        class_diagrams = [d for d in diagrams if d.scope == "classes"]
        assert len(class_diagrams) >= 2

    def test_namespace_grouping_enabled_by_default(self) -> None:
        classes = [
            {
                "name": "Foo",
                "namespace": "audio",
                "fields": [],
                "methods": [],
                "base_classes": [],
            },
            {
                "name": "Bar",
                "namespace": "video",
                "fields": [],
                "methods": [],
                "base_classes": [],
            },
        ]
        diagrams = render_partitioned_class_diagrams(classes, group_by_namespace=True)
        assert len(diagrams) == 1
        assert "namespace audio" in diagrams[0].mermaid
        assert "namespace video" in diagrams[0].mermaid

    def test_generate_all_shows_namespaces(self) -> None:
        comp = Component(
            id="test-comp",
            name="Test",
            description="Test component",
            component_type="library",
        )
        classes = [
            {"name": "A", "namespace": "ns1", "fields": [], "methods": [], "base_classes": []},
            {"name": "B", "namespace": "ns2", "fields": [], "methods": [], "base_classes": []},
        ]
        diagrams = generate_all_diagrams([comp], [], class_data=classes)
        class_diagrams = [d for d in diagrams if d.scope == "classes"]
        all_mermaid = "\n".join(d.mermaid for d in class_diagrams)
        assert "namespace ns1" in all_mermaid
        assert "namespace ns2" in all_mermaid

    def test_empty_class_data(self) -> None:
        diagrams = render_partitioned_class_diagrams([])
        assert len(diagrams) == 1
        assert diagrams[0].mermaid == "classDiagram\n"


# ---------------------------------------------------------------------------
# Mermaid syntax validation helpers
# ---------------------------------------------------------------------------


def _assert_annotations_inside_class_body(mermaid: str) -> None:
    """Verify <<annotation>> lines only appear between class { and }."""
    in_class = False
    brace_depth = 0
    for line in mermaid.splitlines():
        stripped = line.strip()
        if stripped.startswith("class ") and stripped.endswith("{"):
            in_class = True
            brace_depth += 1
        elif in_class and stripped == "}":
            brace_depth -= 1
            if brace_depth == 0:
                in_class = False
        elif "<<" in stripped and ">>" in stripped:
            if stripped.startswith("<<") and stripped.endswith(">>"):
                assert in_class, (
                    f"Annotation on standalone line outside class body: {stripped!r}"
                )


def _assert_annotation_labels_safe(mermaid: str) -> None:
    """Verify <<...>> labels contain only alphanumeric and underscore (no spaces)."""
    for m in _re.finditer(r"<<(.+?)>>", mermaid):
        content = m.group(1)
        bad = _re.search(r"[^a-zA-Z0-9_]", content)
        assert bad is None, (
            f"Annotation label contains invalid char {bad.group()!r}: <<{content}>>"
        )


# ---------------------------------------------------------------------------
# Combinatorial class diagram tests — regression coverage for Bug 1 & Bug 2
# ---------------------------------------------------------------------------


class TestAnnotationsInsideNamespaces:
    """Bug 1 regression: <<abstract>>/<<struct>> must be inside class body, not
    standalone lines inside namespace blocks (Mermaid parser rejects them)."""

    def test_abstract_inside_namespace(self) -> None:
        classes = [
            {
                "name": "Base",
                "namespace": "com.example.engine",
                "is_abstract": True,
                "is_struct": False,
                "fields": [{"name": "x", "type": "int", "access": "protected"}],
                "methods": [],
                "base_classes": [],
            },
        ]
        result = render_class_diagram(classes, group_by_namespace=True)
        _assert_annotations_inside_class_body(result.mermaid)
        assert "<<abstract>>" in result.mermaid
        assert "namespace com_example_engine" in result.mermaid

    def test_struct_inside_namespace(self) -> None:
        classes = [
            {
                "name": "Config",
                "namespace": "data.models",
                "is_abstract": False,
                "is_struct": True,
                "fields": [{"name": "val", "type": "str", "access": "public"}],
                "methods": [],
                "base_classes": [],
            },
        ]
        result = render_class_diagram(classes, group_by_namespace=True)
        _assert_annotations_inside_class_body(result.mermaid)
        assert "<<struct>>" in result.mermaid

    def test_mixed_abstract_and_plain_in_same_namespace(self) -> None:
        classes = [
            {
                "name": "AbstractBase",
                "namespace": "core.services",
                "is_abstract": True,
                "is_struct": False,
                "fields": [],
                "methods": [{"name": "run", "return_type": "void", "access": "public"}],
                "base_classes": [],
            },
            {
                "name": "ConcreteImpl",
                "namespace": "core.services",
                "is_abstract": False,
                "is_struct": False,
                "fields": [],
                "methods": [{"name": "run", "return_type": "void", "access": "public"}],
                "base_classes": [{"name": "AbstractBase", "access": "public"}],
            },
        ]
        result = render_class_diagram(classes, group_by_namespace=True)
        _assert_annotations_inside_class_body(result.mermaid)
        assert "<<abstract>>" in result.mermaid
        assert "namespace core_services" in result.mermaid

    def test_annotation_only_class_in_namespace(self) -> None:
        """Abstract class with no fields/methods — annotation is the only body content."""
        classes = [
            {
                "name": "Marker",
                "namespace": "util",
                "is_abstract": True,
                "is_struct": False,
                "fields": [],
                "methods": [],
                "base_classes": [],
            },
        ]
        result = render_class_diagram(classes, group_by_namespace=True)
        _assert_annotations_inside_class_body(result.mermaid)
        assert "<<abstract>>" in result.mermaid

    def test_no_namespace_annotation_still_valid(self) -> None:
        """Annotations without namespace grouping remain valid (baseline)."""
        classes = [
            {
                "name": "Generic",
                "is_abstract": True,
                "is_struct": False,
                "fields": [{"name": "id", "type": "int", "access": "private"}],
                "methods": [],
                "base_classes": [],
            },
        ]
        result = render_class_diagram(classes)
        _assert_annotations_inside_class_body(result.mermaid)


class TestProxyLabelSanitization:
    """Bug 2 regression: proxy cross-reference labels like <<Diagram N: pkg.mod>>
    must not contain dots — Mermaid's annotation parser rejects them."""

    def _make_two_partition_data(self, ns_a: str, ns_b: str) -> list[dict]:
        classes: list[dict] = []
        for i in range(8):
            classes.append(
                {
                    "name": f"A{i}",
                    "namespace": ns_a,
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        for i in range(8):
            classes.append(
                {
                    "name": f"B{i}",
                    "namespace": ns_b,
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        classes[0]["fields"] = [{"name": "ref", "type": "B0", "access": "private"}]
        return classes

    def test_dotted_namespace_proxy_label(self) -> None:
        classes = self._make_two_partition_data(
            "src.nfr_review.arch_diagrams", "src.nfr_review.models"
        )
        diagrams = render_partitioned_class_diagrams(
            classes, max_per_diagram=10, group_by_namespace=True
        )
        for d in diagrams:
            _assert_annotation_labels_safe(d.mermaid)

    def test_colons_in_namespace_proxy_label(self) -> None:
        classes = self._make_two_partition_data("com::example::core", "com::example::util")
        diagrams = render_partitioned_class_diagrams(
            classes, max_per_diagram=10, group_by_namespace=True
        )
        for d in diagrams:
            _assert_annotation_labels_safe(d.mermaid)

    def test_special_chars_in_namespace_proxy_label(self) -> None:
        classes = self._make_two_partition_data("my-pkg/sub.module", "other-pkg/sub.module")
        diagrams = render_partitioned_class_diagrams(
            classes, max_per_diagram=10, group_by_namespace=True
        )
        for d in diagrams:
            _assert_annotation_labels_safe(d.mermaid)

    def test_proxy_label_contains_diagram_number(self) -> None:
        classes = self._make_two_partition_data("audio", "video")
        diagrams = render_partitioned_class_diagrams(
            classes, max_per_diagram=10, group_by_namespace=True
        )
        all_mermaid = "\n".join(d.mermaid for d in diagrams)
        assert "<<Diagram" in all_mermaid

    def test_abstract_in_namespace_with_proxy_labels(self) -> None:
        """Combined scenario: abstract class + namespace + multi-partition proxies."""
        classes: list[dict] = []
        for i in range(8):
            classes.append(
                {
                    "name": f"Base{i}",
                    "namespace": "org.example.core",
                    "is_abstract": i == 0,
                    "is_struct": False,
                    "fields": [],
                    "methods": [],
                    "base_classes": [],
                }
            )
        for i in range(8):
            classes.append(
                {
                    "name": f"Impl{i}",
                    "namespace": "org.example.impl",
                    "is_abstract": False,
                    "is_struct": False,
                    "fields": [],
                    "methods": [],
                    "base_classes": [{"name": "Base0", "access": "public"}] if i == 0 else [],
                }
            )
        diagrams = render_partitioned_class_diagrams(
            classes, max_per_diagram=10, group_by_namespace=True
        )
        all_mermaid = "\n".join(d.mermaid for d in diagrams)
        assert "<<abstract>>" in all_mermaid
        for d in diagrams:
            _assert_annotations_inside_class_body(d.mermaid)
            _assert_annotation_labels_safe(d.mermaid)


# ---------------------------------------------------------------------------
# Orphan node detection
# ---------------------------------------------------------------------------


class TestOrphanDetection:
    def test_no_orphans_when_all_connected(self) -> None:
        diagram = C4Diagram(
            level="component",
            title="All Connected",
            scope="test",
            mermaid=(
                "flowchart TD\n"
                "    subgraph grp[Group]\n"
                "        svc_a[A]\n"
                "        svc_b[B]\n"
                "    end\n"
                '    svc_a -->|"http"| svc_b\n'
            ),
            component_ids=[],
        )
        orphans = detect_orphan_nodes([diagram])
        assert orphans == []

    def test_detects_disconnected_node(self) -> None:
        diagram = C4Diagram(
            level="component",
            title="Has Orphan",
            scope="test",
            mermaid=(
                "flowchart TD\n"
                "    subgraph grp[Group]\n"
                "        svc_a[A]\n"
                "        svc_b[B]\n"
                "        svc_c[C]\n"
                "    end\n"
                '    svc_a -->|"http"| svc_b\n'
            ),
            component_ids=[],
        )
        orphans = detect_orphan_nodes([diagram])
        assert len(orphans) == 1
        assert orphans[0].node_id == "svc_c"
        assert orphans[0].diagram_title == "Has Orphan"

    def test_skips_class_diagrams(self) -> None:
        diagram = C4Diagram(
            level="code",
            title="Class Diagram",
            scope="classes",
            mermaid="classDiagram\n    class Foo\n",
            component_ids=[],
        )
        orphans = detect_orphan_nodes([diagram])
        assert orphans == []

    def test_skips_legend_nodes(self) -> None:
        diagram = C4Diagram(
            level="container",
            title="Container",
            scope="containers",
            mermaid=(
                "flowchart TD\n"
                "    svc_a[A]\n"
                "    svc_b[B]\n"
                "    svc_a --> svc_b\n"
                '    subgraph legend["Test Coverage"]\n'
                "        leg_none[None]\n"
                "        leg_minimal[Minimal]\n"
                "    end\n"
            ),
            component_ids=[],
        )
        orphans = detect_orphan_nodes([diagram])
        assert orphans == []

    def test_multiple_diagrams(self) -> None:
        d1 = C4Diagram(
            level="component",
            title="D1",
            scope="s1",
            mermaid="flowchart TD\n    orphan_a[A]\n",
            component_ids=[],
        )
        d2 = C4Diagram(
            level="component",
            title="D2",
            scope="s2",
            mermaid=("flowchart TD\n    x[X]\n    y[Y]\n    x --> y\n"),
            component_ids=[],
        )
        orphans = detect_orphan_nodes([d1, d2])
        assert len(orphans) == 1
        assert orphans[0].diagram_title == "D1"

    def test_render_orphans_markdown_empty(self) -> None:
        md = render_orphans_markdown([])
        assert "No orphan nodes detected" in md

    def test_render_orphans_markdown_with_data(self) -> None:
        orphans = [
            OrphanNode(
                diagram_title="Container",
                diagram_scope="containers",
                diagram_level="container",
                node_id="svc_orphan",
            ),
        ]
        md = render_orphans_markdown(orphans)
        assert "Total orphans: 1" in md
        assert "svc_orphan" in md
        assert "## Container" in md


# ---------------------------------------------------------------------------
# Real mmdc syntax validation — catches parse errors that substring tests miss
# ---------------------------------------------------------------------------

_MMDC = shutil.which("mmdc")
requires_mmdc = pytest.mark.skipif(_MMDC is None, reason="mmdc not installed")


def _assert_mmdc_parses(mermaid: str, label: str = "") -> None:
    """Run mmdc on the Mermaid text and assert it exits 0 (syntax OK)."""
    assert _MMDC is not None
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "input.mmd"
        out = Path(td) / "output.png"
        cfg = Path(td) / "config.json"
        inp.write_text(mermaid)
        cfg.write_text(json.dumps({"maxTextSize": 200_000}))
        result = subprocess.run(
            [_MMDC, "-i", str(inp), "-o", str(out), "-b", "transparent", "-c", str(cfg)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")[:500]
            pytest.fail(f"mmdc parse failure{f' ({label})' if label else ''}: {err}")


def _make_rich_classes(
    *,
    ns_prefix: str = "",
    count: int = 6,
    abstract_indices: set[int] | None = None,
    struct_indices: set[int] | None = None,
) -> list[dict]:
    """Build a realistic set of class dicts with fields, methods, inheritance."""
    abstract_indices = abstract_indices or set()
    struct_indices = struct_indices or set()
    classes: list[dict] = []
    for i in range(count):
        ns = f"{ns_prefix}.pkg{i // 3}" if ns_prefix else ""
        cls: dict = {
            "name": f"Class{i}",
            "line": i * 10 + 1,
            "has_destructor": False,
            "is_struct": i in struct_indices,
            "is_abstract": i in abstract_indices,
            "namespace": ns,
            "base_classes": [{"name": f"Class{i - 1}", "access": "public"}] if i > 0 else [],
            "fields": [
                {"name": f"field_{j}", "type": "string", "access": "private"} for j in range(3)
            ],
            "methods": [
                {
                    "name": f"method_{j}",
                    "return_type": "void",
                    "access": "public",
                    "is_virtual": False,
                    "is_pure_virtual": i in abstract_indices and j == 0,
                    "line": i * 10 + j + 2,
                    "parameters": [{"name": "arg", "type": f"Class{(i + 1) % count}"}],
                }
                for j in range(2)
            ],
        }
        classes.append(cls)
    return classes


@requires_mmdc
class TestMermaidSyntaxValidation:
    """Validate generated Mermaid against the real mmdc parser.

    Every test generates indicative class diagram output and pipes it
    through mmdc.  These catch syntax errors (bad annotations, namespace
    violations, illegal chars) that substring assertions miss.
    """

    def test_basic_class_diagram(self) -> None:
        classes = _make_rich_classes()
        d = render_class_diagram(classes, title="Basic")
        _assert_mmdc_parses(d.mermaid, "basic class diagram")

    def test_namespace_grouping(self) -> None:
        classes = _make_rich_classes(ns_prefix="com.example")
        d = render_class_diagram(classes, group_by_namespace=True)
        _assert_mmdc_parses(d.mermaid, "namespace grouping")

    def test_abstract_in_namespace(self) -> None:
        classes = _make_rich_classes(ns_prefix="org.project", abstract_indices={0, 2})
        d = render_class_diagram(classes, group_by_namespace=True)
        _assert_mmdc_parses(d.mermaid, "abstract in namespace")

    def test_struct_in_namespace(self) -> None:
        classes = _make_rich_classes(ns_prefix="audio.dsp", struct_indices={1, 3})
        d = render_class_diagram(classes, group_by_namespace=True)
        _assert_mmdc_parses(d.mermaid, "struct in namespace")

    def test_mixed_annotations_in_namespace(self) -> None:
        classes = _make_rich_classes(
            ns_prefix="engine.core", abstract_indices={0}, struct_indices={3, 5}
        )
        d = render_class_diagram(classes, group_by_namespace=True)
        _assert_mmdc_parses(d.mermaid, "mixed annotations in namespace")

    def test_partitioned_with_dotted_namespaces(self) -> None:
        classes = _make_rich_classes(ns_prefix="src.nfr_review.arch", count=20)
        diagrams = render_partitioned_class_diagrams(
            classes, max_per_diagram=8, group_by_namespace=True
        )
        for i, d in enumerate(diagrams):
            _assert_mmdc_parses(d.mermaid, f"partition {i}")

    def test_partitioned_with_proxy_crossrefs(self) -> None:
        part_a = _make_rich_classes(ns_prefix="pkg.alpha", count=10)
        part_b = _make_rich_classes(ns_prefix="pkg.beta", count=10)
        for i, cls in enumerate(part_b):
            cls["name"] = f"Beta{i}"
        part_b[0]["base_classes"] = [{"name": "Class0", "access": "public"}]
        diagrams = render_partitioned_class_diagrams(
            part_a + part_b, max_per_diagram=12, group_by_namespace=True
        )
        for i, d in enumerate(diagrams):
            _assert_mmdc_parses(d.mermaid, f"proxy crossref partition {i}")

    def test_partitioned_abstract_with_proxies(self) -> None:
        classes = _make_rich_classes(
            ns_prefix="org.example.core", count=20, abstract_indices={0, 5, 10}
        )
        diagrams = render_partitioned_class_diagrams(
            classes, max_per_diagram=8, group_by_namespace=True
        )
        for i, d in enumerate(diagrams):
            _assert_mmdc_parses(d.mermaid, f"abstract+proxy partition {i}")

    def test_cpp_double_colon_namespaces(self) -> None:
        classes = _make_rich_classes(ns_prefix="std::chrono", count=6, struct_indices={2})
        d = render_class_diagram(classes, group_by_namespace=True)
        _assert_mmdc_parses(d.mermaid, "C++ :: namespaces")

    def test_nested_and_friend_classes(self) -> None:
        classes = [
            {
                "name": "Container",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "is_abstract": False,
                "namespace": "util",
                "base_classes": [],
                "fields": [{"name": "data", "type": "vector~int~", "access": "private"}],
                "methods": [],
                "friends": ["Inspector"],
            },
            {
                "name": "Iterator",
                "line": 20,
                "has_destructor": False,
                "is_struct": False,
                "is_abstract": False,
                "namespace": "util",
                "base_classes": [],
                "fields": [],
                "methods": [
                    {
                        "name": "next",
                        "return_type": "bool",
                        "access": "public",
                        "is_virtual": False,
                        "is_pure_virtual": False,
                        "line": 21,
                    }
                ],
                "outer_class": "Container",
            },
            {
                "name": "Inspector",
                "line": 40,
                "has_destructor": False,
                "is_struct": False,
                "is_abstract": False,
                "namespace": "debug",
                "base_classes": [],
                "fields": [],
                "methods": [],
            },
        ]
        d = render_class_diagram(classes, group_by_namespace=True)
        _assert_mmdc_parses(d.mermaid, "nested + friend classes in namespaces")

    def test_single_class_no_members(self) -> None:
        classes = [
            {
                "name": "Singleton",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "is_abstract": False,
                "base_classes": [],
                "fields": [],
                "methods": [],
            }
        ]
        d = render_class_diagram(classes)
        _assert_mmdc_parses(d.mermaid, "single class")

    def test_cpp_union_brace_fields(self) -> None:
        """Regression: union { const void* p_data; } broke mmdc with OPEN_IN_STRUCT."""
        classes = [
            {
                "name": "Variant",
                "line": 1,
                "has_destructor": False,
                "is_struct": True,
                "is_abstract": False,
                "namespace": "audio",
                "base_classes": [],
                "fields": [
                    {
                        "name": "data",
                        "type": "union { const void* p_data; size_t i_data; }",
                        "access": "public",
                    },
                    {
                        "name": "tag",
                        "type": "int",
                        "access": "public",
                    },
                ],
                "methods": [],
            }
        ]
        d = render_class_diagram(classes, group_by_namespace=True)
        _assert_mmdc_parses(d.mermaid, "C++ union brace fields")

    def test_cpp_nested_template_with_colons(self) -> None:
        """Regression: std::index_sequence<I...> broke mmdc with unexpected COLON."""
        classes = [
            {
                "name": "DispatcherImpl",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "is_abstract": False,
                "namespace": "detail",
                "base_classes": [],
                "fields": [
                    {
                        "name": "seq",
                        "type": "std::index_sequence<Indices...>",
                        "access": "private",
                    },
                ],
                "methods": [
                    {
                        "name": "dispatch",
                        "return_type": (
                            "DispatcherImpl<Struct, std::index_sequence<Indices...>>"
                        ),
                        "access": "public",
                        "is_virtual": False,
                        "is_pure_virtual": False,
                        "line": 10,
                    }
                ],
            }
        ]
        d = render_class_diagram(classes, group_by_namespace=True)
        _assert_mmdc_parses(d.mermaid, "C++ nested template with colons")
