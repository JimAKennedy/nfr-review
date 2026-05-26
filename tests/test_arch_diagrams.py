# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for C4 architecture diagram generation."""

from __future__ import annotations

import pytest

from nfr_review.arch_diagrams import (
    _safe_id,
    generate_all_diagrams,
    render_c4_code,
    render_c4_component,
    render_c4_container,
    render_c4_context,
)
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
        assert "root" in result.mermaid

    def test_custom_title(self, api_service: Component) -> None:
        result = render_c4_code([api_service], title="Code Map")
        assert result.title == "Code Map"


# ---------------------------------------------------------------------------
# generate_all_diagrams tests
# ---------------------------------------------------------------------------


class TestGenerateAllDiagrams:
    def test_returns_three_diagrams(
        self,
        all_components: list[Component],
        all_integrations: list[IntegrationPoint],
    ) -> None:
        diagrams = generate_all_diagrams(all_components, all_integrations)
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
