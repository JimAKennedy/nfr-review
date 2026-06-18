# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Bridge from scan results to Structurizr workspace models.

Maps ArchReport components/integrations and ExperimentalReport class diagrams
into a DslWorkspace suitable for DSL emission.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from nfr_review.structurizr_models import (
    DslAutoLayout,
    DslDynamicStep,
    DslDynamicView,
    DslElement,
    DslElementStyle,
    DslModel,
    DslRelationship,
    DslRelationshipStyle,
    DslStyles,
    DslView,
    DslViewContent,
    DslWorkspace,
    ElementType,
    make_identifier,
)

if TYPE_CHECKING:
    from nfr_review.arch_models import ArchReport, Component, IntegrationPoint
    from nfr_review.experimental_models import ExperimentalReport

_COMPONENT_TYPE_TO_C4: dict[str, str] = {
    "service": "container",
    "library": "component",
    "database": "container",
    "queue": "container",
    "gateway": "container",
    "ui": "container",
    "worker": "container",
    "external": "softwareSystem",
}

_C4_LEVEL_TO_ELEMENT: dict[str, str] = {
    "context": "softwareSystem",
    "container": "container",
    "component": "component",
    "code": "component",
}


def _component_element_type(comp: Component) -> str:
    """Determine the DSL element type for an arch component."""
    if comp.component_type == "external":
        return "softwareSystem"
    by_level = _C4_LEVEL_TO_ELEMENT.get(comp.c4_level)
    if by_level:
        return by_level
    return _COMPONENT_TYPE_TO_C4.get(comp.component_type, "container")


def _technology_str(comp: Component) -> str:
    """Extract a concise technology string from a component's tech stack."""
    if not comp.tech_stack:
        return ""
    names = [t.name for t in comp.tech_stack[:3]]
    tech = ", ".join(names)
    if len(comp.tech_stack) > 3:
        tech += f" +{len(comp.tech_stack) - 3}"
    return tech


def _build_component_element(comp: Component) -> DslElement:
    ident = make_identifier(comp.id)
    elem_type = _component_element_type(comp)
    tags = []
    if comp.component_type == "external":
        tags.append("External")
    if comp.environment:
        tags.append(comp.environment)

    return DslElement(
        identifier=ident,
        element_type=cast(ElementType, elem_type),
        name=comp.name,
        description=comp.description[:200] if comp.description else "",
        technology=_technology_str(comp),
        tags=tags,
    )


def _build_relationship(
    ip: IntegrationPoint, comp_id_to_ident: dict[str, str]
) -> DslRelationship | None:
    src = comp_id_to_ident.get(ip.source_component_id)
    dst = comp_id_to_ident.get(ip.target_component_id)
    if not src or not dst:
        return None

    tags = []
    if ip.is_cross_repo:
        tags.append("CrossRepo")

    return DslRelationship(
        source_id=src,
        destination_id=dst,
        description=ip.description or ip.style.replace("_", " ").title(),
        technology=ip.protocol or "",
        tags=tags,
    )


def build_workspace_from_arch(
    report: ArchReport,
    *,
    workspace_name: str = "",
) -> DslWorkspace:
    """Convert an ArchReport into a DslWorkspace."""
    name = workspace_name or "Architecture"
    if report.metadata.repos_analyzed:
        repo_names = [r.name for r in report.metadata.repos_analyzed]
        name = workspace_name or f"Architecture — {', '.join(repo_names)}"

    systems: list[DslElement] = []
    containers: list[DslElement] = []
    comp_id_to_ident: dict[str, str] = {}

    for comp in report.components:
        elem = _build_component_element(comp)
        comp_id_to_ident[comp.id] = elem.identifier

        if elem.element_type == "softwareSystem":
            systems.append(elem)
        else:
            containers.append(elem)

    if containers:
        primary_name = "System"
        if report.metadata.repos_analyzed:
            primary_name = report.metadata.repos_analyzed[0].name
        primary_ident = make_identifier(primary_name)

        primary_system = DslElement(
            identifier=primary_ident,
            element_type="softwareSystem",
            name=primary_name,
            description="Primary system under analysis",
            children=containers,
        )
        systems.insert(0, primary_system)

    relationships = []
    for ip in report.integration_points:
        rel = _build_relationship(ip, comp_id_to_ident)
        if rel:
            relationships.append(rel)

    dynamic_views = []
    for scenario in report.dynamic_scenarios:
        steps = []
        for step in scenario.steps:
            src = comp_id_to_ident.get(step.from_component_id)
            dst = comp_id_to_ident.get(step.to_component_id)
            if src and dst:
                steps.append(
                    DslDynamicStep(
                        source_id=src,
                        destination_id=dst,
                        description=step.action,
                    )
                )
        if steps:
            dynamic_views.append(
                DslDynamicView(
                    key=make_identifier(scenario.id),
                    description=scenario.name,
                    steps=steps,
                    auto_layout=DslAutoLayout(direction="lr"),
                )
            )

    views = [
        DslView(
            view_type="systemLandscape",
            key="landscape",
            content=DslViewContent(
                include=["*"],
                auto_layout=DslAutoLayout(direction="tb"),
            ),
        ),
    ]
    if containers and systems:
        views.append(
            DslView(
                view_type="container",
                scope_id=systems[0].identifier,
                key="containers",
                content=DslViewContent(
                    include=["*"],
                    auto_layout=DslAutoLayout(direction="lr"),
                ),
            )
        )

    styles = DslStyles(
        elements=[
            DslElementStyle(
                tag="External",
                background="#999999",
                color="#ffffff",
                shape="RoundedBox",
            ),
            DslElementStyle(
                tag="Element",
                shape="RoundedBox",
            ),
        ],
        relationships=[
            DslRelationshipStyle(
                tag="CrossRepo",
                style="dashed",
                color="#ff0000",
            ),
        ],
    )

    return DslWorkspace(
        name=name,
        description=f"Auto-generated by nfr-review v{report.metadata.tool_version}",
        model=DslModel(
            software_systems=systems,
            relationships=relationships,
        ),
        views=views,
        dynamic_views=dynamic_views,
        styles=styles,
    )


def build_workspace_from_experimental(
    report: ExperimentalReport,
    *,
    workspace_name: str = "",
) -> DslWorkspace:
    """Convert an ExperimentalReport into a DslWorkspace."""
    name = workspace_name or f"Architecture — {report.repo_name}"

    systems: list[DslElement] = []
    relationships: list[DslRelationship] = []

    repos_seen: set[str] = set()

    for edge in report.cross_repo_edges:
        for repo in (edge.source_repo, edge.target_repo):
            if repo not in repos_seen:
                repos_seen.add(repo)
                systems.append(
                    DslElement(
                        identifier=make_identifier(repo),
                        element_type="softwareSystem",
                        name=repo,
                    )
                )

        relationships.append(
            DslRelationship(
                source_id=make_identifier(edge.source_repo),
                destination_id=make_identifier(edge.target_repo),
                description=f"{edge.source_class} -> {edge.target_class}",
                tags=["CrossRepo"],
            )
        )

    if report.dynamic_analysis and report.dynamic_analysis.services:
        for svc_name in report.dynamic_analysis.services:
            if svc_name not in repos_seen:
                repos_seen.add(svc_name)
                systems.append(
                    DslElement(
                        identifier=make_identifier(svc_name),
                        element_type="softwareSystem",
                        name=svc_name,
                        tags=["OTel"],
                    )
                )

    if not systems:
        systems.append(
            DslElement(
                identifier=make_identifier(report.repo_name),
                element_type="softwareSystem",
                name=report.repo_name,
            )
        )

    views = [
        DslView(
            view_type="systemLandscape",
            key="landscape",
            content=DslViewContent(
                include=["*"],
                auto_layout=DslAutoLayout(direction="tb"),
            ),
        ),
    ]

    styles = DslStyles(
        elements=[
            DslElementStyle(tag="OTel", border="dashed"),
            DslElementStyle(tag="Element", shape="RoundedBox"),
        ],
        relationships=[
            DslRelationshipStyle(tag="CrossRepo", style="dashed", color="#ff0000"),
        ],
    )

    return DslWorkspace(
        name=name,
        description="Auto-generated from experimental scan",
        model=DslModel(
            software_systems=systems,
            relationships=relationships,
        ),
        views=views,
        styles=styles,
    )


__all__ = [
    "build_workspace_from_arch",
    "build_workspace_from_experimental",
]
