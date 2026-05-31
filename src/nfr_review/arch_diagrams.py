# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""C4 architecture diagram generators producing Mermaid text.

Generates C4 diagrams at context, container, component, and code levels
from discovered components, integrations, and test coverage data.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from nfr_review.arch_discovery import DvcPipeline
from nfr_review.arch_models import C4Diagram, Component, IntegrationPoint

if TYPE_CHECKING:
    from nfr_review.arch_models import ComponentTestCoverage, CoverageLevel

# ---------------------------------------------------------------------------
# Helpers — mirror patterns from output/diagrams.py
# ---------------------------------------------------------------------------

_MERMAID_ID_RE = re.compile(r"[^a-zA-Z0-9_]")
_MERMAID_RESERVED = frozenset(
    {
        "default",
        "graph",
        "subgraph",
        "end",
        "style",
        "class",
        "click",
        "linkstyle",
        "classDef",
        "direction",
    }
)

_MAX_NODES_PER_DIAGRAM = 60


def _safe_id(raw: str) -> str:
    """Turn an arbitrary string into a Mermaid-safe node ID."""
    cleaned = _MERMAID_ID_RE.sub("_", raw)
    if cleaned.lower() in _MERMAID_RESERVED:
        cleaned = f"g_{cleaned}"
    return cleaned


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
        return _normalize_boundary(comp.boundaries[0].path)
    return "."


_ROOT_PATHS = frozenset({".", "./", "", "root", "default"})


def _normalize_boundary(path: str) -> str:
    """Collapse all root-equivalent boundary strings to ``"."``."""
    stripped = path.strip().rstrip("/")
    if stripped in _ROOT_PATHS:
        return "."
    return path


def _boundary_path(comp: Component) -> str:
    """Return the most specific boundary path for component-level grouping."""
    if comp.boundaries:
        return _normalize_boundary(comp.boundaries[0].path)
    return "."


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


def _cap_components(
    components: list[Component],
    limit: int = _MAX_NODES_PER_DIAGRAM,
) -> tuple[list[Component], int]:
    """Return at most *limit* components and the number omitted."""
    if len(components) <= limit:
        return components, 0
    return components[:limit], len(components) - limit


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

    # Emit edges (deduplicated — multiple internal components may connect to same external)
    internal_ids = {c.id for c in internal}
    seen_edges: set[tuple[str, str]] = set()
    for integ in integrations:
        src = integ.source_component_id
        tgt = integ.target_component_id
        src_internal = src in internal_ids
        tgt_internal = tgt in internal_ids

        if src_internal and tgt_internal:
            continue

        src_node = "sys_inner" if src_internal else _safe_id(src)
        tgt_node = "sys_inner" if tgt_internal else _safe_id(tgt)
        if (src_node, tgt_node) not in seen_edges:
            seen_edges.add((src_node, tgt_node))
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

    # Separate containers, infrastructure, and libraries
    containers: list[Component] = []
    infra_by_env: dict[str, list[Component]] = {}
    libraries: list[Component] = []
    for c in components:
        if c.environment is not None:
            infra_by_env.setdefault(c.environment, []).append(c)
        elif c.component_type in _CONTAINER_TYPES or c.component_type == "external":
            containers.append(c)
        elif c.component_type == "library":
            libraries.append(c)
        else:
            containers.append(c)

    # Group app containers by boundary
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

    # Emit infrastructure grouped by environment
    _ENV_DISPLAY: dict[str, str] = {
        "prod": "Production Infrastructure",
        "staging": "Staging Infrastructure",
        "test": "Test Infrastructure",
        "dev": "Development Infrastructure",
    }
    for env_name in sorted(infra_by_env, key=lambda e: (e != "prod", e)):
        env_comps = infra_by_env[env_name]
        sg_id = _safe_id(f"infra_{env_name}")
        label = _ENV_DISPLAY.get(env_name, f"{env_name.title()} Infrastructure")
        lines.append(f"    subgraph {sg_id}[{_quote_label(label)}]")
        for c in env_comps:
            cid = _safe_id(c.id)
            node_label = f"{c.name}<br/>{c.component_type}"
            lines.append(f"        {_node_declaration(cid, node_label, c.component_type)}")
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

    # Emit edges (deduplicate — same pair may be discovered by multiple strategies)
    seen_edges: set[tuple[str, str]] = set()
    for integ in integrations:
        if integ.source_component_id in comp_map and integ.target_component_id in comp_map:
            src_id = _safe_id(integ.source_component_id)
            tgt_id = _safe_id(integ.target_component_id)
            if src_id == tgt_id:
                continue
            if (src_id, tgt_id) not in seen_edges:
                seen_edges.add((src_id, tgt_id))
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

    scoped, omitted = _cap_components(scoped)
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

    if omitted:
        lines.append(f"    truncated[{_quote_label(f'... +{omitted} more components')}]")
        lines.append("    style truncated fill:#f5f5f5,stroke:#999,stroke-dasharray:5 5")

    # Emit internal edges (deduplicated, only between shown components)
    seen_edges: set[tuple[str, str]] = set()
    for integ in integrations:
        if integ.source_component_id in scoped_ids and integ.target_component_id in scoped_ids:
            src_id = _safe_id(integ.source_component_id)
            tgt_id = _safe_id(integ.target_component_id)
            if src_id == tgt_id:
                continue
            if (src_id, tgt_id) not in seen_edges:
                seen_edges.add((src_id, tgt_id))
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
    focus_comps_all = groups.get(focus_group, [])
    focus_comps, detail_omitted = _cap_components(focus_comps_all)

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
            if tgt_grp is not None and tgt_grp != focus_group:
                external_groups_needed.add(tgt_grp)
                cross_edges.append(integ)
        elif tgt_in and not src_in:
            src_grp = comp_to_group.get(integ.source_component_id)
            if src_grp is not None and src_grp != focus_group:
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
    if detail_omitted:
        lines.append(f"        truncated[{_quote_label(f'... +{detail_omitted} more')}]")
        lines.append("        style truncated fill:#f5f5f5,stroke:#999,stroke-dasharray:5 5")
    lines.append("    end")

    for ext_grp in sorted(external_groups_needed):
        ext_comps = groups.get(ext_grp, [])
        gid = _safe_id(f"ext_{ext_grp}")
        ext_label = _group_name(ext_grp)
        count = len(ext_comps)
        lines.append(f"    {gid}[{_quote_label(f'{ext_label} ({count})')}]")
        lines.append(f"    style {gid} fill:#f5f5f5,stroke:#999,stroke-dasharray:5 5")

    seen_edges: set[tuple[str, str]] = set()
    for integ in internal_edges:
        src_id = _safe_id(integ.source_component_id)
        tgt_id = _safe_id(integ.target_component_id)
        if src_id == tgt_id:
            continue
        if (src_id, tgt_id) not in seen_edges:
            seen_edges.add((src_id, tgt_id))
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
        if src_id == tgt_id:
            continue
        if (src_id, tgt_id) not in seen_edges:
            seen_edges.add((src_id, tgt_id))
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

    capped, code_omitted = _cap_components(components)
    lines: list[str] = ["flowchart TD"]

    # Group by directory-level boundary paths
    dir_groups: dict[str, list[Component]] = {}
    for c in capped:
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

    if code_omitted:
        lines.append(f"    truncated[{_quote_label(f'... +{code_omitted} more components')}]")
        lines.append("    style truncated fill:#f5f5f5,stroke:#999,stroke-dasharray:5 5")

    mermaid = "\n".join(lines) + "\n"
    return C4Diagram(
        level="code",
        title=title,
        scope="code",
        mermaid=mermaid,
        component_ids=[c.id for c in components],
    )


# ===================================================================
# Class Diagram — from enriched C++ AST evidence
# ===================================================================

_ACCESS_SYMBOL = {"public": "+", "protected": "#", "private": "-"}
_MAX_MEMBERS_PER_CLASS = 15


def _sanitize_member_type(raw: str) -> str:
    """Escape characters in type strings that break Mermaid syntax."""
    s = raw.replace("::", ".").replace("<", "~").replace(">", "~")
    return s.replace("[", "~").replace("]", "~").replace('"', "").replace("'", "")


# Tokens to ignore when extracting type references from C++ field/return types.
_CPP_TYPE_NOISE = frozenset(
    {
        "std",
        "const",
        "volatile",
        "mutable",
        "void",
        "bool",
        "int",
        "char",
        "float",
        "double",
        "long",
        "short",
        "signed",
        "unsigned",
        "size_t",
        "ptrdiff_t",
        "int8_t",
        "int16_t",
        "int32_t",
        "int64_t",
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "string",
        "wstring",
        "auto",
        "unique_ptr",
        "shared_ptr",
        "weak_ptr",
        "SharedPointer",
        "vector",
        "array",
        "map",
        "unordered_map",
        "set",
        "unordered_set",
        "deque",
        "list",
        "queue",
        "stack",
        "pair",
        "tuple",
        "optional",
        "variant",
        "atomic",
        "mutex",
        "thread",
        "condition_variable",
        "uniform_real_distribution",
        "normal_distribution",
        "mt19937",
        "FILE",
        "tresult",
        "SMTG_OVERRIDE",
    }
)
_CPP_PTR_INDICATORS = frozenset({"unique_ptr", "shared_ptr", "weak_ptr", "SharedPointer"})
_CPP_TOKEN_RE = re.compile(r"\b([A-Za-z_]\w*)\b")


def _extract_type_refs(type_str: str, known_names: set[str]) -> list[tuple[str, bool]]:
    """Extract referenced class names from a C++ type string.

    Returns ``[(class_name, is_owned), ...]`` where *is_owned* is True for
    by-value / unique_ptr (composition) and False for raw-pointer, reference,
    or shared_ptr (aggregation).
    """
    if not type_str:
        return []

    is_pointer = "*" in type_str or "&" in type_str
    has_shared = any(p in type_str for p in ("shared_ptr", "weak_ptr", "SharedPointer"))

    refs: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for tok in _CPP_TOKEN_RE.findall(type_str):
        if tok in _CPP_TYPE_NOISE or tok in seen:
            continue
        if tok in known_names:
            is_owned = not (is_pointer or has_shared)
            refs.append((tok, is_owned))
            seen.add(tok)
    return refs


def render_class_diagram(
    class_data: list[dict],
    title: str | None = None,
    *,
    group_by_namespace: bool = False,
) -> C4Diagram:
    """Render a Mermaid class diagram from enriched C++ AST class data.

    *class_data* is a list of class dicts as produced by the cpp-ast
    collector's enriched payload (base_classes, methods, fields,
    parameters, friends, namespace, outer_class).

    When *group_by_namespace* is True, classes are grouped inside
    Mermaid ``namespace`` blocks reflecting their C++ namespace.
    """
    title = title or "Class Diagram"

    if not class_data:
        return C4Diagram(
            level="code",
            title=title,
            scope="classes",
            mermaid="classDiagram\n",
            component_ids=[],
        )

    lines: list[str] = ["classDiagram"]
    known_names = {c["name"] for c in class_data if c.get("name")}

    # -- Namespace grouping (collect classes by ns) --
    ns_groups: dict[str, list[dict]] = {}
    for cls in class_data:
        ns = cls.get("namespace", "") or ""
        ns_groups.setdefault(ns, []).append(cls)

    def _emit_class_block(cls: dict, indent: str) -> None:
        name = cls.get("name", "")
        if not name:
            return
        cid = _safe_id(name)

        if cls.get("is_abstract"):
            lines.append(f"{indent}class {cid}")
            lines.append(f"{indent}<<abstract>> {cid}")
        elif cls.get("is_struct"):
            lines.append(f"{indent}class {cid}")
            lines.append(f"{indent}<<struct>> {cid}")
        else:
            lines.append(f"{indent}class {cid}")

        member_count = 0
        for field in cls.get("fields", []):
            if member_count >= _MAX_MEMBERS_PER_CLASS:
                break
            sym = _ACCESS_SYMBOL.get(field.get("access", "private"), "-")
            ftype = _sanitize_member_type(field.get("type", ""))
            fname = field.get("name", "")
            lines.append(f"{indent}{cid} : {sym}{fname} {ftype}")
            member_count += 1

        for method in cls.get("methods", []):
            if member_count >= _MAX_MEMBERS_PER_CLASS:
                break
            mname = method.get("name", "")
            if mname.startswith("~"):
                continue
            sym = _ACCESS_SYMBOL.get(method.get("access", "public"), "+")
            rtype = _sanitize_member_type(method.get("return_type", ""))
            virt = "*" if method.get("is_pure_virtual") else ""
            lines.append(f"{indent}{cid} : {sym}{mname}(){virt} {rtype}")
            member_count += 1

    if group_by_namespace:
        for ns in sorted(ns_groups):
            group = ns_groups[ns]
            if ns:
                safe_ns = ns.replace("::", "_")
                lines.append(f"    namespace {safe_ns} {{")
                for cls in group:
                    _emit_class_block(cls, "        ")
                lines.append("    }")
            else:
                for cls in group:
                    _emit_class_block(cls, "    ")
    else:
        for cls in class_data:
            _emit_class_block(cls, "    ")

    # -- Inheritance edges --
    inheritance_pairs: set[tuple[str, str]] = set()
    for cls in class_data:
        name = cls.get("name", "")
        if not name:
            continue
        cid = _safe_id(name)
        for base in cls.get("base_classes", []):
            base_name = base.get("name", "")
            if base_name in known_names:
                bid = _safe_id(base_name)
                lines.append(f"    {bid} <|-- {cid}")
                inheritance_pairs.add((name, base_name))
            else:
                ext_id = _safe_id(base_name)
                lines.append(f"    class {ext_id}")
                lines.append(f"    <<external>> {ext_id}")
                lines.append(f"    {ext_id} <|-- {cid}")
                known_names.add(base_name)
                inheritance_pairs.add((name, base_name))

    # -- Composition / aggregation edges (from field types) --
    edge_seen: set[tuple[str, str, str]] = set()
    for cls in class_data:
        name = cls.get("name", "")
        if not name:
            continue
        cid = _safe_id(name)
        for field in cls.get("fields", []):
            for ref_name, is_owned in _extract_type_refs(field.get("type", ""), known_names):
                if ref_name == name:
                    continue
                pair = (name, ref_name)
                if pair in inheritance_pairs or (ref_name, name) in inheritance_pairs:
                    continue
                arrow = "*--" if is_owned else "o--"
                edge_key = (name, ref_name, arrow)
                if edge_key in edge_seen:
                    continue
                edge_seen.add(edge_key)
                rid = _safe_id(ref_name)
                lines.append(f"    {cid} {arrow} {rid}")

    # -- Dependency edges (from method return types + parameter types) --
    for cls in class_data:
        name = cls.get("name", "")
        if not name:
            continue
        cid = _safe_id(name)
        for method in cls.get("methods", []):
            dep_types: list[str] = []
            if method.get("return_type"):
                dep_types.append(method["return_type"])
            for param in method.get("parameters", []):
                if param.get("type"):
                    dep_types.append(param["type"])
            for type_str in dep_types:
                for ref_name, _ in _extract_type_refs(type_str, known_names):
                    if ref_name == name:
                        continue
                    pair = (name, ref_name)
                    if pair in inheritance_pairs or (ref_name, name) in inheritance_pairs:
                        continue
                    if any((name, ref_name, a) in edge_seen for a in ("*--", "o--")):
                        continue
                    dep_key = (name, ref_name, "..>")
                    if dep_key in edge_seen:
                        continue
                    edge_seen.add(dep_key)
                    rid = _safe_id(ref_name)
                    lines.append(f"    {cid} ..> {rid}")

    # -- Friend edges (dashed dependency) --
    for cls in class_data:
        name = cls.get("name", "")
        if not name:
            continue
        cid = _safe_id(name)
        for friend_name in cls.get("friends", []):
            if friend_name not in known_names or friend_name == name:
                continue
            friend_key = (name, friend_name, "..>")
            reverse_key = (friend_name, name, "..>")
            if friend_key in edge_seen or reverse_key in edge_seen:
                continue
            edge_seen.add(friend_key)
            fid = _safe_id(friend_name)
            lines.append(f'    {cid} ..> {fid} : "friend"')

    # -- Nested class edges --
    for cls in class_data:
        name = cls.get("name", "")
        outer = cls.get("outer_class", "")
        if not name or not outer or outer not in known_names:
            continue
        nest_key = (outer, name, "nest")
        if nest_key in edge_seen:
            continue
        edge_seen.add(nest_key)
        oid = _safe_id(outer)
        nid = _safe_id(name)
        lines.append(f'    {oid} *-- {nid} : "inner"')

    mermaid = "\n".join(lines) + "\n"
    return C4Diagram(
        level="code",
        title=title,
        scope="classes",
        mermaid=mermaid,
        component_ids=[],
    )


# ===================================================================
# Pipeline Diagram — from DVC stage DAG
# ===================================================================


def render_pipeline_diagram(
    pipeline: DvcPipeline,
    title: str | None = None,
) -> C4Diagram:
    """Render a Mermaid flowchart from a parsed DVC pipeline.

    Stages are shown as nodes with their command. Edges follow the
    implicit DAG derived from stage output-to-input dependencies.
    Stages with no edges are shown as isolated nodes.
    """
    title = title or "ML Pipeline"

    if not pipeline.stages:
        return C4Diagram(
            level="code",
            title=title,
            scope="pipeline",
            mermaid="flowchart TD\n",
            component_ids=[],
        )

    lines: list[str] = ["flowchart TD"]

    for stage in pipeline.stages:
        sid = _safe_id(stage.name)
        cmd_short = stage.cmd
        if len(cmd_short) > 40:
            cmd_short = cmd_short[:37] + "..."
        label = f"{stage.name}<br/>{cmd_short}"
        lines.append(f"    {sid}[{_quote_label(label)}]")

    for src, tgt in pipeline.edges:
        src_id = _safe_id(src)
        tgt_id = _safe_id(tgt)
        lines.append(f"    {src_id} --> {tgt_id}")

    mermaid = "\n".join(lines) + "\n"
    return C4Diagram(
        level="code",
        title=title,
        scope="pipeline",
        mermaid=mermaid,
        component_ids=[],
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
    class_data: list[dict] | None = None,
    pipeline_data: list[DvcPipeline] | None = None,
) -> list[C4Diagram]:
    """Generate context + container + component + class + pipeline diagrams.

    If *coverage* is provided, the container diagram nodes are annotated
    with colour classes reflecting coverage levels.

    *diagram_mode* controls component diagram layout:
    - ``"hierarchical"`` (default): overview + per-group detail diagrams.
    - ``"flat"``: single monolithic component diagram (original behavior).

    If *class_data* is provided (enriched class dicts from cpp-ast),
    a Mermaid class diagram is appended.

    If *pipeline_data* is provided (parsed DVC pipelines), a Mermaid
    pipeline flowchart is appended for each pipeline.
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

        # Coverage legend
        used_levels: set[CoverageLevel] = set(cov_map.values())
        _LEVEL_LABELS: dict[CoverageLevel, str] = {
            "none": "None",
            "minimal": "Minimal",
            "partial": "Partial",
            "adequate": "Adequate",
            "comprehensive": "Comprehensive",
        }
        legend_order: list[CoverageLevel] = [
            "comprehensive",
            "adequate",
            "partial",
            "minimal",
            "none",
        ]
        legend_lines: list[str] = [
            '    subgraph legend["Test Coverage"]',
            "        direction LR",
        ]
        for lvl in legend_order:
            if lvl in used_levels:
                lid = f"leg_{lvl}"
                cls_name = _COVERAGE_CLASS[lvl]
                legend_lines.append(
                    f"        {lid}[{_quote_label(_LEVEL_LABELS[lvl])}]:::{cls_name}"
                )
        legend_lines.append("    end")
        extra_lines.extend(legend_lines)

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

    if class_data:
        by_lang: dict[str, list[dict]] = {}
        for cls in class_data:
            lang = cls.get("language", "Unknown")
            by_lang.setdefault(lang, []).append(cls)
        if len(by_lang) > 1:
            for lang in sorted(by_lang):
                diagrams.append(
                    render_class_diagram(by_lang[lang], title=f"Class Diagram ({lang})")
                )
        else:
            diagrams.append(render_class_diagram(class_data))

    if pipeline_data:
        for pipeline in pipeline_data:
            diagrams.append(render_pipeline_diagram(pipeline))

    return diagrams


__all__ = [
    "generate_all_diagrams",
    "render_c4_code",
    "render_c4_component",
    "render_c4_component_detail",
    "render_c4_component_overview",
    "render_c4_container",
    "render_c4_context",
    "render_class_diagram",
    "render_pipeline_diagram",
]
