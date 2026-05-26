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


def _group_name(path: str) -> str:
    """Human-readable name for a boundary-path group."""
    normalized = path.strip().rstrip("/")
    if normalized in (".", "./", "root", "", "default"):
        return "Project Root"
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _package_boundary(comp: Component) -> str | None:
    """Return the package boundary path if one exists, else None."""
    for b in comp.boundaries:
        if b.boundary_type == "package":
            return b.path
    return None


def _render_nodes_with_package_nesting(
    lines: list[str],
    group_key: str,
    components: list[Component],
    base_indent: str,
    node_fn,
) -> None:
    """Render component nodes, nesting by package when package boundaries exist.

    *node_fn(comp, indent)* returns a single Mermaid line for the node.
    When no component in *components* has a package boundary, all nodes
    are rendered flat at *base_indent*.
    """
    pkgs: dict[str | None, list[Component]] = {}
    for c in components:
        pkg = _package_boundary(c)
        pkgs.setdefault(pkg, []).append(c)

    if not any(k is not None for k in pkgs):
        for c in components:
            lines.append(node_fn(c, base_indent))
        return

    nested_indent = base_indent + "    "
    for pkg_name in sorted(pkgs, key=lambda x: x or ""):
        pkg_comps = pkgs[pkg_name]
        if pkg_name is not None:
            sg_id = _safe_id(f"pkg_{group_key}_{pkg_name}")
            lines.append(f"{base_indent}subgraph {sg_id}[{_quote_label(pkg_name)}]")
            for c in pkg_comps:
                lines.append(node_fn(c, nested_indent))
            lines.append(f"{base_indent}end")
        else:
            for c in pkg_comps:
                lines.append(node_fn(c, base_indent))


def _group_components_by_boundary(
    components: list[Component],
) -> dict[str, list[Component]]:
    """Group components by their top-level boundary path."""
    groups: dict[str, list[Component]] = {}
    for c in components:
        bp = _boundary_path(c)
        groups.setdefault(bp, []).append(c)
    return groups


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
    def _container_node(c: Component, indent: str) -> str:
        cid = _safe_id(c.id)
        label = f"{c.name}<br/>{c.component_type}"
        return f"{indent}{_node_declaration(cid, label, c.component_type)}"

    for grp_name, grp_comps in sorted(boundary_groups.items()):
        sg_id = _safe_id(grp_name)
        lines.append(f"    subgraph {sg_id}[{_quote_label(_group_name(grp_name))}]")
        _render_nodes_with_package_nesting(
            lines, grp_name, grp_comps, "        ", _container_node
        )
        lines.append("    end")

    # Emit library subgraphs
    for grp_name, grp_comps in sorted(lib_groups.items()):
        sg_id = _safe_id(f"libs_{grp_name}")
        lines.append(f"    subgraph {sg_id}[{_quote_label(_group_name(grp_name) + ' libs')}]")
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

    def _comp_node(c: Component, indent: str) -> str:
        cid = _safe_id(c.id)
        label = f"{c.name}<br/>{c.component_type}"
        return f"{indent}{_node_declaration(cid, label, c.component_type)}"

    for grp_name, grp_comps in sorted(path_groups.items()):
        sg_id = _safe_id(f"grp_{grp_name}")
        lines.append(f"    subgraph {sg_id}[{_quote_label(_group_name(grp_name))}]")
        _render_nodes_with_package_nesting(lines, grp_name, grp_comps, "        ", _comp_node)
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
# C4 Level 3 — Component (hierarchical decomposition)
# ===================================================================


def render_c4_component_overview(
    components: list[Component],
    integrations: list[IntegrationPoint],
    title: str | None = None,
) -> C4Diagram:
    """Render an overview component diagram with collapsed boundary groups.

    Each top-level boundary group is represented as a single node.
    Edges show inter-group connectivity (deduplicated).
    """
    title = title or "Component Overview"

    if not components:
        return C4Diagram(
            level="component",
            title=title,
            scope="overview",
            mermaid="flowchart TD\n",
            component_ids=[],
        )

    groups = _group_components_by_boundary(components)
    comp_to_group: dict[str, str] = {}
    for bp, grp_comps in groups.items():
        for c in grp_comps:
            comp_to_group[c.id] = bp

    lines: list[str] = ["flowchart TD"]

    for bp, grp_comps in sorted(groups.items()):
        gid = _safe_id(f"grp_{bp}")
        label = _group_name(bp)
        count = len(grp_comps)
        lines.append(f"    {gid}[{_quote_label(f'{label} ({count})')}]")

    seen_edges: set[tuple[str, str]] = set()
    for integ in integrations:
        src_grp = comp_to_group.get(integ.source_component_id)
        tgt_grp = comp_to_group.get(integ.target_component_id)
        if src_grp is None or tgt_grp is None or src_grp == tgt_grp:
            continue
        edge_key = (src_grp, tgt_grp)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        src_id = _safe_id(f"grp_{src_grp}")
        tgt_id = _safe_id(f"grp_{tgt_grp}")
        lines.append(f"    {src_id} --> {tgt_id}")

    mermaid = "\n".join(lines) + "\n"
    return C4Diagram(
        level="component",
        title=title,
        scope="overview",
        mermaid=mermaid,
        component_ids=[c.id for c in components],
    )


def render_c4_component_detail(
    components: list[Component],
    integrations: list[IntegrationPoint],
    focus_group: str,
    title: str | None = None,
) -> C4Diagram:
    """Render a detail component diagram for one boundary group.

    Shows full internal detail for *focus_group*. Connected components
    from other groups appear as collapsed single-node stubs.
    """
    groups = _group_components_by_boundary(components)
    focus_comps = groups.get(focus_group, [])

    display_name = _group_name(focus_group)
    title = title or f"Components — {display_name}"

    if not focus_comps:
        return C4Diagram(
            level="component",
            title=title,
            scope=focus_group,
            mermaid="flowchart TD\n",
            component_ids=[],
        )

    focus_ids = {c.id for c in focus_comps}
    comp_to_group: dict[str, str] = {}
    for bp, grp_comps in groups.items():
        for c in grp_comps:
            comp_to_group[c.id] = bp

    external_groups_needed: set[str] = set()
    internal_edges: list[IntegrationPoint] = []
    cross_edges: list[IntegrationPoint] = []

    for integ in integrations:
        src_in = integ.source_component_id in focus_ids
        tgt_in = integ.target_component_id in focus_ids
        if src_in and tgt_in:
            internal_edges.append(integ)
        elif src_in and not tgt_in:
            tgt_grp = comp_to_group.get(integ.target_component_id)
            if tgt_grp is not None:
                external_groups_needed.add(tgt_grp)
                cross_edges.append(integ)
        elif tgt_in and not src_in:
            src_grp = comp_to_group.get(integ.source_component_id)
            if src_grp is not None:
                external_groups_needed.add(src_grp)
                cross_edges.append(integ)

    lines: list[str] = ["flowchart TD"]

    def _detail_node(c: Component, indent: str) -> str:
        cid = _safe_id(c.id)
        label = f"{c.name}<br/>{c.component_type}"
        return f"{indent}{_node_declaration(cid, label, c.component_type)}"

    sg_id = _safe_id(f"focus_{focus_group}")
    lines.append(f"    subgraph {sg_id}[{_quote_label(display_name)}]")
    _render_nodes_with_package_nesting(
        lines, focus_group, focus_comps, "        ", _detail_node
    )
    lines.append("    end")

    for ext_grp in sorted(external_groups_needed):
        ext_comps = groups.get(ext_grp, [])
        gid = _safe_id(f"ext_{ext_grp}")
        ext_label = _group_name(ext_grp)
        count = len(ext_comps)
        lines.append(f"    {gid}[{_quote_label(f'{ext_label} ({count})')}]")
        lines.append(f"    style {gid} fill:#f5f5f5,stroke:#999,stroke-dasharray:5 5")

    for integ in internal_edges:
        src_id = _safe_id(integ.source_component_id)
        tgt_id = _safe_id(integ.target_component_id)
        lines.append(_edge(src_id, tgt_id, integ))

    for integ in cross_edges:
        src_in = integ.source_component_id in focus_ids
        if src_in:
            src_id = _safe_id(integ.source_component_id)
            tgt_grp = comp_to_group.get(integ.target_component_id, "")
            tgt_id = _safe_id(f"ext_{tgt_grp}")
        else:
            src_grp = comp_to_group.get(integ.source_component_id, "")
            src_id = _safe_id(f"ext_{src_grp}")
            tgt_id = _safe_id(integ.target_component_id)
        lines.append(_edge(src_id, tgt_id, integ))

    mermaid = "\n".join(lines) + "\n"
    all_shown_ids = [c.id for c in focus_comps]
    return C4Diagram(
        level="component",
        title=title,
        scope=focus_group,
        mermaid=mermaid,
        component_ids=all_shown_ids,
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

    def _code_node(c: Component, indent: str) -> str:
        cid = _safe_id(c.id)
        tech = ""
        if c.tech_stack:
            tech = "<br/>" + ", ".join(t.name for t in c.tech_stack[:3])
        label = f"{c.name}{tech}"
        return f"{indent}{cid}[{_quote_label(label)}]"

    for dir_path, grp_comps in sorted(dir_groups.items()):
        sg_id = _safe_id(f"dir_{dir_path}")
        lines.append(f"    subgraph {sg_id}[{_quote_label(_group_name(dir_path))}]")
        _render_nodes_with_package_nesting(lines, dir_path, grp_comps, "        ", _code_node)
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
    *,
    diagram_mode: str = "hierarchical",
) -> list[C4Diagram]:
    """Generate context + container + component diagrams.

    If *coverage* is provided, the container diagram nodes are annotated
    with colour classes reflecting coverage levels.

    *diagram_mode* controls component diagram layout:
    - ``"hierarchical"`` (default): overview + per-group detail diagrams.
    - ``"flat"``: single monolithic component diagram (original behavior).
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

    if diagram_mode == "flat":
        diagrams.append(render_c4_component(components, integrations))
    else:
        groups = _group_components_by_boundary(components)
        if len(groups) <= 1:
            diagrams.append(render_c4_component(components, integrations))
        else:
            diagrams.append(render_c4_component_overview(components, integrations))
            for bp in sorted(groups):
                diagrams.append(render_c4_component_detail(components, integrations, bp))

    return diagrams


__all__ = [
    "generate_all_diagrams",
    "render_c4_code",
    "render_c4_component",
    "render_c4_component_detail",
    "render_c4_component_overview",
    "render_c4_container",
    "render_c4_context",
]
