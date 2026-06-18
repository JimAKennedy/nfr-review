# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Emit valid Structurizr DSL text from workspace models."""

from __future__ import annotations

import logging
from pathlib import Path

from nfr_review.structurizr_models import (
    DslAutoLayout,
    DslDynamicView,
    DslElement,
    DslElementStyle,
    DslGroup,
    DslModel,
    DslProperty,
    DslRelationship,
    DslRelationshipStyle,
    DslStyles,
    DslView,
    DslWorkspace,
)

logger = logging.getLogger(__name__)

_INDENT = "    "


def _q(text: str) -> str:
    """Quote a string for DSL output.  Empty strings become ``""``."""
    if not text:
        return '""'
    if " " in text or '"' in text or not text.strip():
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f'"{text}"'


def _emit_properties(props: list[DslProperty], indent: str) -> list[str]:
    if not props:
        return []
    lines = [f"{indent}properties {{"]
    for p in props:
        lines.append(f"{indent}{_INDENT}{_q(p.key)} {_q(p.value)}")
    lines.append(f"{indent}}}")
    return lines


def _emit_tags(tags: list[str], indent: str) -> list[str]:
    if not tags:
        return []
    quoted = " ".join(_q(t) for t in tags)
    return [f"{indent}tags {quoted}"]


def _emit_relationship(rel: DslRelationship, indent: str) -> list[str]:
    parts = [f"{indent}{rel.source_id} -> {rel.destination_id}"]
    if rel.description:
        parts[0] += f" {_q(rel.description)}"
    if rel.technology:
        if not rel.description:
            parts[0] += ' ""'
        parts[0] += f" {_q(rel.technology)}"

    has_body = rel.tags or rel.properties
    if has_body:
        parts[0] += " {"
        parts.extend(_emit_tags(rel.tags, indent + _INDENT))
        parts.extend(_emit_properties(rel.properties, indent + _INDENT))
        parts.append(f"{indent}}}")
    return parts


def _emit_implicit_relationship(rel: DslRelationship, indent: str) -> list[str]:
    parts = [f"{indent}-> {rel.destination_id}"]
    if rel.description:
        parts[0] += f" {_q(rel.description)}"
    if rel.technology:
        if not rel.description:
            parts[0] += ' ""'
        parts[0] += f" {_q(rel.technology)}"

    has_body = rel.tags or rel.properties
    if has_body:
        parts[0] += " {"
        parts.extend(_emit_tags(rel.tags, indent + _INDENT))
        parts.extend(_emit_properties(rel.properties, indent + _INDENT))
        parts.append(f"{indent}}}")
    return parts


def _emit_element(elem: DslElement, indent: str) -> list[str]:
    type_kw = elem.element_type
    header = f"{indent}{elem.identifier} = {type_kw} {_q(elem.name)}"

    if elem.description:
        header += f" {_q(elem.description)}"
    if elem.technology:
        if not elem.description:
            header += ' ""'
        header += f" {_q(elem.technology)}"

    has_body = (
        elem.tags
        or elem.properties
        or elem.url
        or elem.children
        or elem.implicit_relationships
    )

    if has_body:
        header += " {"
        lines = [header]
        if elem.url:
            lines.append(f"{indent}{_INDENT}url {elem.url}")
        lines.extend(_emit_tags(elem.tags, indent + _INDENT))
        lines.extend(_emit_properties(elem.properties, indent + _INDENT))
        for child in elem.children:
            lines.extend(_emit_element(child, indent + _INDENT))
        for rel in elem.implicit_relationships:
            lines.extend(_emit_implicit_relationship(rel, indent + _INDENT))
        lines.append(f"{indent}}}")
        return lines
    else:
        return [header]


def _emit_group(group: DslGroup, indent: str) -> list[str]:
    lines = [f"{indent}group {_q(group.name)} {{"]
    for sub in group.groups:
        lines.extend(_emit_group(sub, indent + _INDENT))
    for elem in group.elements:
        lines.extend(_emit_element(elem, indent + _INDENT))
    lines.append(f"{indent}}}")
    return lines


def _emit_model(model: DslModel, indent: str) -> list[str]:
    lines = [f"{indent}model {{"]
    inner = indent + _INDENT

    lines.extend(_emit_properties(model.properties, inner))

    for person in model.people:
        lines.extend(_emit_element(person, inner))

    for group in model.groups:
        lines.extend(_emit_group(group, inner))

    for system in model.software_systems:
        lines.extend(_emit_element(system, inner))

    for rel in model.relationships:
        lines.extend(_emit_relationship(rel, inner))

    lines.append(f"{indent}}}")
    return lines


def _emit_auto_layout(al: DslAutoLayout | None, indent: str) -> list[str]:
    if al is None:
        return []
    parts = [f"{indent}autoLayout {al.direction}"]
    if al.rank_sep is not None:
        parts[0] += f" {al.rank_sep}"
        if al.node_sep is not None:
            parts[0] += f" {al.node_sep}"
    return parts


def _emit_view(view: DslView, indent: str) -> list[str]:
    header = f"{indent}{view.view_type}"
    if view.scope_id:
        header += f" {view.scope_id}"
    header += f" {_q(view.key)}"
    if view.description:
        header += f" {_q(view.description)}"
    header += " {"

    lines = [header]
    inner = indent + _INDENT

    for inc in view.content.include:
        v = inc if inc == "*" else _q(inc)
        lines.append(f"{inner}include {v}")
    for exc in view.content.exclude:
        v = exc if exc == "*" else _q(exc)
        lines.append(f"{inner}exclude {v}")
    lines.extend(_emit_auto_layout(view.content.auto_layout, inner))
    if view.content.title:
        lines.append(f"{inner}title {_q(view.content.title)}")
    if view.content.is_default:
        lines.append(f"{inner}default")

    lines.append(f"{indent}}}")
    return lines


def _emit_dynamic_view(dv: DslDynamicView, indent: str) -> list[str]:
    header = f"{indent}dynamic"
    if dv.scope_id:
        header += f" {dv.scope_id}"
    header += f" {_q(dv.key)}"
    if dv.description:
        header += f" {_q(dv.description)}"
    header += " {"

    lines = [header]
    inner = indent + _INDENT

    for step in dv.steps:
        line = f"{inner}{step.source_id} -> {step.destination_id}"
        if step.description:
            line += f" {_q(step.description)}"
        lines.append(line)

    lines.extend(_emit_auto_layout(dv.auto_layout, inner))
    lines.append(f"{indent}}}")
    return lines


def _emit_element_style(es: DslElementStyle, indent: str) -> list[str]:
    lines = [f"{indent}element {_q(es.tag)} {{"]
    inner = indent + _INDENT

    if es.shape is not None:
        lines.append(f"{inner}shape {es.shape}")
    if es.background:
        lines.append(f"{inner}background {es.background}")
    if es.color:
        lines.append(f"{inner}color {es.color}")
    if es.stroke:
        lines.append(f"{inner}stroke {es.stroke}")
    if es.stroke_width is not None:
        lines.append(f"{inner}strokeWidth {es.stroke_width}")
    if es.border is not None:
        lines.append(f"{inner}border {es.border}")
    if es.font_size is not None:
        lines.append(f"{inner}fontSize {es.font_size}")
    if es.opacity is not None:
        lines.append(f"{inner}opacity {es.opacity}")
    if es.icon:
        lines.append(f"{inner}icon {es.icon}")
    if es.metadata is not None:
        lines.append(f"{inner}metadata {str(es.metadata).lower()}")
    if es.show_description is not None:
        lines.append(f"{inner}description {str(es.show_description).lower()}")

    lines.append(f"{indent}}}")
    return lines


def _emit_relationship_style(rs: DslRelationshipStyle, indent: str) -> list[str]:
    lines = [f"{indent}relationship {_q(rs.tag)} {{"]
    inner = indent + _INDENT

    if rs.thickness is not None:
        lines.append(f"{inner}thickness {rs.thickness}")
    if rs.color:
        lines.append(f"{inner}color {rs.color}")
    if rs.style is not None:
        lines.append(f"{inner}style {rs.style}")
    if rs.routing is not None:
        lines.append(f"{inner}routing {rs.routing}")
    if rs.font_size is not None:
        lines.append(f"{inner}fontSize {rs.font_size}")
    if rs.position is not None:
        lines.append(f"{inner}position {rs.position}")
    if rs.opacity is not None:
        lines.append(f"{inner}opacity {rs.opacity}")

    lines.append(f"{indent}}}")
    return lines


def _emit_styles(styles: DslStyles, indent: str) -> list[str]:
    if not styles.elements and not styles.relationships:
        return []
    lines = [f"{indent}styles {{"]
    inner = indent + _INDENT
    for es in styles.elements:
        lines.extend(_emit_element_style(es, inner))
    for rs in styles.relationships:
        lines.extend(_emit_relationship_style(rs, inner))
    lines.append(f"{indent}}}")
    return lines


def emit_workspace_dsl(workspace: DslWorkspace) -> str:
    """Render a DslWorkspace to valid Structurizr DSL text."""
    header = "workspace"
    if workspace.name:
        header += f" {_q(workspace.name)}"
    if workspace.description:
        header += f" {_q(workspace.description)}"
    header += " {"

    lines = [header]
    inner = _INDENT

    if workspace.use_hierarchical_identifiers:
        lines.append(f"{inner}!identifiers hierarchical")
    if not workspace.implied_relationships:
        lines.append(f"{inner}!impliedRelationships false")

    lines.append("")
    lines.extend(_emit_model(workspace.model, inner))

    has_views = (
        workspace.views
        or workspace.dynamic_views
        or (workspace.styles.elements or workspace.styles.relationships)
    )
    if has_views:
        lines.append("")
        lines.append(f"{inner}views {{")
        views_inner = inner + _INDENT

        for view in workspace.views:
            lines.extend(_emit_view(view, views_inner))
        for dv in workspace.dynamic_views:
            lines.extend(_emit_dynamic_view(dv, views_inner))
        lines.extend(_emit_styles(workspace.styles, views_inner))

        lines.append(f"{inner}}}")

    lines.append("}")
    lines.append("")

    return "\n".join(lines)


def write_workspace_dsl(workspace: DslWorkspace, output_path: Path) -> Path:
    """Emit DSL text and write to *output_path*."""
    text = emit_workspace_dsl(workspace)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text)
    logger.info("Structurizr DSL written to %s", output_path)
    return output_path


__all__ = [
    "emit_workspace_dsl",
    "write_workspace_dsl",
]
