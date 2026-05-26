# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""C4 architecture diagram generators producing Mermaid text.

Generates C4 diagrams at context, container, component, and code levels
from discovered components, integrations, and test coverage data.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from nfr_review.arch_models import C4Diagram, Component, IntegrationPoint

if TYPE_CHECKING:
    from nfr_review.arch_models import ComponentTestCoverage, CoverageLevel

# ---------------------------------------------------------------------------
# Helpers — mirror patterns from output/diagrams.py
# ---------------------------------------------------------------------------

_MERMAID_ID_RE = re.compile(r"[^a-zA-Z0-9_]")


def _safe_id(raw: str) -> str:
    """Turn an arbitrary string into a Mermaid-safe node ID."""
    return _MERMAID_ID_RE.sub("_", raw)


def _quote_label(text: str) -> str:
    """Wrap *text* in double quotes, escaping inner quotes."""
    return '"' + text.replace('"', "#quot;") + '"'


# ---------------------------------------------------------------------------
# Node shape helpers per component type
# ---------------------------------------------------------------------------

_SHAPE_MAP: dict[str, tuple[str, str]] = {
    "database": (
        '(["',
        '"])',
    ),  # type: ignore[dict-item]
    "queue": ('{{"', '"}}'),
}


def _node_declaration(node_id: str, label: str, component_type: str) -> str:
    """Return a Mermaid node declaration with shape based on type."""
    if component_type == "database":
        return f'{node_id}[("{label}")]'
    if component_type == "queue":
        return f'{node_id}{{{{"{label}"}}}}'
    # Default rectangle for service, library, gateway, ui, worker, external
    return f"{node_id}[{_quote_label(label)}]"


# ---------------------------------------------------------------------------
# Coverage helpers
# ---------------------------------------------------------------------------

_COVERAGE_COLORS: dict[CoverageLevel, str] = {
    "none": "#ff6b6b",
    "minimal": "#ffa94d",
    "partial": "#ffd43b",
    "adequate": "#69db7c",
    "comprehensive": "#38d9a9",
}

_COVERAGE_CLASS: dict[CoverageLevel, str] = {
    "none": "covNone",
    "minimal": "covMinimal",
    "partial": "covPartial",
    "adequate": "covAdequate",
    "comprehensive": "covComprehensive",
}


def _coverage_classdefs() -> list[str]:
    """Return Mermaid classDef lines for coverage levels."""
    lines: list[str] = []
    for level, cls_name in _COVERAGE_CLASS.items():
        color = _COVERAGE_COLORS[level]
        lines.append(f"    classDef {cls_name} fill:{color},stroke:#333,color:#000")
    return lines


def _coverage_map(
    coverage: list[ComponentTestCoverage],
) -> dict[str, CoverageLevel]:
    """Build component_id -> worst-of(functional, nonfunctional) map."""
    order: list[CoverageLevel] = [
        "none",
        "minimal",
        "partial",
        "adequate",
        "comprehensive",
    ]
    rank = {v: i for i, v in enumerate(order)}
    result: dict[str, CoverageLevel] = {}
    for cov in coverage:
        worst = min(
            cov.functional_coverage, cov.nonfunctional_coverage, key=lambda c: rank.get(c, 0)
        )
        result[cov.component_id] = worst
    return result


# ---------------------------------------------------------------------------
# Edge helpers
# ---------------------------------------------------------------------------

_ASYNC_STYLES = frozenset({"asynchronous", "event_driven", "message_queue"})


def _edge(src_id: str, tgt_id: str, integration: IntegrationPoint) -> str:
    """Return a Mermaid edge line (solid for sync, dashed for async)."""
    label_parts: list[str] = []
    if integration.style in _ASYNC_STYLES:
        label_parts.append("async")
    if integration.protocol:
        label_parts.append(integration.protocol)
    elif integration.description:
        label_parts.append(integration.description[:30])

    label = ": ".join(label_parts) if label_parts else ""

    if integration.style in _ASYNC_STYLES:
        if label:
            return f"    {src_id} -.->|{_quote_label(label)}| {tgt_id}"
        return f"    {src_id} -.-> {tgt_id}"
    else:
        if label:
            return f"    {src_id} -->|{_quote_label(label)}| {tgt_id}"
        return f"    {src_id} --> {tgt_id}"


# ---------------------------------------------------------------------------
# Grouping helpers
# ---------------------------------------------------------------------------


def _primary_boundary(comp: Component) -> str:
    """Return a sensible grouping label for a component."""
    if comp.repo:
        return comp.repo
    if comp.boundaries:
        return comp.boundaries[0].path
    return "default"


def _boundary_path(comp: Component) -> str:
    """Return the most specific boundary path for component-level grouping."""
    if comp.boundaries:
        return comp.boundaries[0].path
    return "root"


# ---------------------------------------------------------------------------
# Component lookup helper
# ---------------------------------------------------------------------------


def _comp_by_id(components: list[Component]) -> dict[str, Component]:
    return {c.id: c for c in components}


# ===================================================================
# C4 Level 1 — System Context
# ===================================================================


def render_c4_context(
    components: list[Component],
    integrations: list[IntegrationPoint],
    title: str | None = None,
) -> C4Diagram:
    """Render a C4 System Context diagram.

    Internal components are collapsed into a single "System" box.
    External components (``component_type="external"``) appear as separate
    nodes. Cross-repo integrations are shown as connections.
    """
    title = title or "System Context"
    lines: list[str] = ["flowchart TD"]

    internal = [c for c in components if c.component_type != "external"]
    external = [c for c in components if c.component_type == "external"]

    # Emit the system box grouping all internal components
    system_id = "system"
    if internal:
        internal_names = ", ".join(c.name for c in internal[:5])
        if len(internal) > 5:
            internal_names += f" (+{len(internal) - 5} more)"
        lines.append(f"    subgraph {system_id}[{_quote_label(title)}]")
        lines.append(f"        sys_inner[{_quote_label(internal_names)}]")
        lines.append("    end")
    elif not external:
        # No components at all — return minimal diagram
        return C4Diagram(
            level="context",
            title=title,
            scope="system",
            mermaid="flowchart TD\n",
            component_ids=[],
        )

    # Emit external actors
    for ext in external:
        eid = _safe_id(ext.id)
        lines.append(f'    {eid}["{ext.name}<br/>external"]')

    # Emit edges
    internal_ids = {c.id for c in internal}
    for integ in integrations:
        src = integ.source_component_id
        tgt = integ.target_component_id
        src_internal = src in internal_ids
        tgt_internal = tgt in internal_ids

        if src_internal and tgt_internal:
            # Both internal — skip at context level
            continue

        src_node = "sys_inner" if src_internal else _safe_id(src)
        tgt_node = "sys_inner" if tgt_internal else _safe_id(tgt)
        lines.append(_edge(src_node, tgt_node, integ))

    mermaid = "\n".join(lines) + "\n"
    return C4Diagram(
        level="context",
        title=title,
        scope="system",
        mermaid=mermaid,
        component_ids=[c.id for c in components],
    )


# ===================================================================
# C4 Level 2 — Container
# ===================================================================

_CONTAINER_TYPES = frozenset({"service", "database", "queue", "gateway", "ui", "worker"})


def render_c4_container(
    components: list[Component],
    integrations: list[IntegrationPoint],
    title: str | None = None,
) -> C4Diagram:
    """Render a C4 Container diagram.

    Each component whose type is a container-level concern (service,
    database, queue, gateway, ui, worker) is shown individually.
    Libraries are grouped into their repo/boundary subgraph.
    """
    title = title or "Container Diagram"
    lines: list[str] = ["flowchart TD"]

    comp_map = _comp_by_id(components)

    if not components:
        return C4Diagram(
            level="container",
            title=title,
            scope="containers",
            mermaid="flowchart TD\n",
            component_ids=[],
        )

    # Separate containers from libraries
    containers: list[Component] = []
    libraries: list[Component] = []
    for c in components:
        if c.component_type in _CONTAINER_TYPES or c.component_type == "external":
            containers.append(c)
        else:
            libraries.append(c)

    # Group by boundary
    boundary_groups: dict[str, list[Component]] = {}
    for c in containers:
        grp = _primary_boundary(c)
        boundary_groups.setdefault(grp, []).append(c)

    lib_groups: dict[str, list[Component]] = {}
    for c in libraries:
        grp = _primary_boundary(c)
        lib_groups.setdefault(grp, []).append(c)

    # Emit container subgraphs
    for grp_name, grp_comps in sorted(boundary_groups.items()):
        sg_id = _safe_id(grp_name)
        lines.append(f"    subgraph {sg_id}[{_quote_label(grp_name)}]")
        for c in grp_comps:
            cid = _safe_id(c.id)
            label = f"{c.name}<br/>{c.component_type}"
            lines.append(f"        {_node_declaration(cid, label, c.component_type)}")
        lines.append("    end")

    # Emit library subgraphs
    for grp_name, grp_comps in sorted(lib_groups.items()):
        sg_id = _safe_id(f"libs_{grp_name}")
        lines.append(f"    subgraph {sg_id}[{_quote_label(grp_name + ' libs')}]")
        for c in grp_comps:
            cid = _safe_id(c.id)
            label = f"{c.name}<br/>library"
            lines.append(f"        {cid}[{_quote_label(label)}]")
        lines.append("    end")

    # Emit edges
    for integ in integrations:
        src_id = _safe_id(integ.source_component_id)
        tgt_id = _safe_id(integ.target_component_id)
        # Only emit if both endpoints exist in our component set
        if integ.source_component_id in comp_map and integ.target_component_id in comp_map:
            lines.append(_edge(src_id, tgt_id, integ))

    mermaid = "\n".join(lines) + "\n"
    return C4Diagram(
        level="container",
        title=title,
        scope="containers",
        mermaid=mermaid,
        component_ids=[c.id for c in components],
    )


# ===================================================================
# C4 Level 3 — Component
# ===================================================================


def render_c4_component(
    components: list[Component],
    integrations: list[IntegrationPoint],
    scope_component_id: str | None = None,
    title: str | None = None,
) -> C4Diagram:
    """Render a C4 Component diagram.

    If *scope_component_id* is given, only components sharing its
    boundary are shown. Otherwise all components are rendered, grouped
    by their boundary paths.
    """
    title = title or "Component Diagram"

    if not components:
        return C4Diagram(
            level="component",
            title=title,
            scope=scope_component_id,
            mermaid="flowchart TD\n",
            component_ids=[],
        )

    comp_map = _comp_by_id(components)

    # Scope filtering
    if scope_component_id is not None:
        scope_comp = comp_map.get(scope_component_id)
        if scope_comp is None:
            return C4Diagram(
                level="component",
                title=title,
                scope=scope_component_id,
                mermaid="flowchart TD\n",
                component_ids=[],
            )
        scope_boundary = _primary_boundary(scope_comp)
        scoped = [c for c in components if _primary_boundary(c) == scope_boundary]
    else:
        scoped = list(components)

    scoped_ids = {c.id for c in scoped}
    lines: list[str] = ["flowchart TD"]

    # Group by boundary path
    path_groups: dict[str, list[Component]] = {}
    for c in scoped:
        bp = _boundary_path(c)
        path_groups.setdefault(bp, []).append(c)

    for grp_name, grp_comps in sorted(path_groups.items()):
        sg_id = _safe_id(f"grp_{grp_name}")
        lines.append(f"    subgraph {sg_id}[{_quote_label(grp_name)}]")
        for c in grp_comps:
            cid = _safe_id(c.id)
            label = f"{c.name}<br/>{c.component_type}"
            lines.append(f"        {_node_declaration(cid, label, c.component_type)}")
        lines.append("    end")

    # Emit internal edges
    for integ in integrations:
        if integ.source_component_id in scoped_ids and integ.target_component_id in scoped_ids:
            src_id = _safe_id(integ.source_component_id)
            tgt_id = _safe_id(integ.target_component_id)
            lines.append(_edge(src_id, tgt_id, integ))

    mermaid = "\n".join(lines) + "\n"
    return C4Diagram(
        level="component",
        title=title,
        scope=scope_component_id,
        mermaid=mermaid,
        component_ids=[c.id for c in scoped],
    )


# ===================================================================
# C4 Level 4 — Code
# ===================================================================


def render_c4_code(
    components: list[Component],
    title: str | None = None,
) -> C4Diagram:
    """Render a C4 Code-level diagram.

    Shows directory structure as nested subgraphs. Since we lack full
    AST data, this is a simplified view based on boundary paths.
    """
    title = title or "Code Diagram"

    if not components:
        return C4Diagram(
            level="code",
            title=title,
            scope="code",
            mermaid="flowchart TD\n",
            component_ids=[],
        )

    lines: list[str] = ["flowchart TD"]

    # Group by directory-level boundary paths
    dir_groups: dict[str, list[Component]] = {}
    for c in components:
        bp = _boundary_path(c)
        dir_groups.setdefault(bp, []).append(c)

    for dir_path, grp_comps in sorted(dir_groups.items()):
        sg_id = _safe_id(f"dir_{dir_path}")
        lines.append(f"    subgraph {sg_id}[{_quote_label(dir_path)}]")
        for c in grp_comps:
            cid = _safe_id(c.id)
            tech = ""
            if c.tech_stack:
                tech = "<br/>" + ", ".join(t.name for t in c.tech_stack[:3])
            label = f"{c.name}{tech}"
            lines.append(f"        {cid}[{_quote_label(label)}]")
        lines.append("    end")

    mermaid = "\n".join(lines) + "\n"
    return C4Diagram(
        level="code",
        title=title,
        scope="code",
        mermaid=mermaid,
        component_ids=[c.id for c in components],
    )


# ===================================================================
# Convenience — generate all diagrams
# ===================================================================


def generate_all_diagrams(
    components: list[Component],
    integrations: list[IntegrationPoint],
    coverage: list[ComponentTestCoverage] | None = None,
) -> list[C4Diagram]:
    """Generate context + container + component diagrams.

    If *coverage* is provided, the container diagram nodes are annotated
    with colour classes reflecting coverage levels.
    """
    diagrams: list[C4Diagram] = []

    diagrams.append(render_c4_context(components, integrations))
    container_diag = render_c4_container(components, integrations)

    # Annotate coverage on container diagram if available
    if coverage:
        cov_map = _coverage_map(coverage)
        extra_lines: list[str] = []
        extra_lines.extend(_coverage_classdefs())
        for comp_id, level in cov_map.items():
            nid = _safe_id(comp_id)
            cls_name = _COVERAGE_CLASS.get(level)
            if cls_name:
                extra_lines.append(f"    class {nid} {cls_name}")

        annotated = container_diag.mermaid.rstrip("\n")
        annotated += "\n" + "\n".join(extra_lines) + "\n"
        container_diag = container_diag.model_copy(update={"mermaid": annotated})

    diagrams.append(container_diag)
    diagrams.append(render_c4_component(components, integrations))

    return diagrams


__all__ = [
    "generate_all_diagrams",
    "render_c4_code",
    "render_c4_component",
    "render_c4_container",
    "render_c4_context",
]
