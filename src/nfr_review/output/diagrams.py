# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Mermaid diagram text generators for NFR review reports.

Converts existing model data into valid Mermaid diagram text for three
diagram types: severity pie chart, technology overview flowchart, and
dependency graph.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nfr_review.arch_models import Component, IntegrationPoint
    from nfr_review.dep_solver import TreeNode
    from nfr_review.deps_analysis import EcosystemDepsReport
    from nfr_review.models import Evidence, Finding

_SEVERITY_ORDER: tuple[str, ...] = ("critical", "high", "medium", "low", "info")

_MERMAID_ID_RE = re.compile(r"[^a-zA-Z0-9_]")

_MAX_DEP_NODES = 80


def _safe_id(ecosystem: str, pkg_name: str) -> str:
    return _MERMAID_ID_RE.sub("_", f"{ecosystem}__{pkg_name}")


def _quote_label(text: str) -> str:
    return '"' + text.replace('"', "#quot;") + '"'


def _to_title_case(key: str) -> str:
    return key.replace("_", " ").title()


def render_mermaid_severity_pie(findings: list[Finding]) -> str:
    """Render a Mermaid pie chart showing finding counts by severity."""
    lines: list[str] = []
    lines.append("pie title Severity Distribution")

    if not findings:
        return "\n".join(lines) + "\n"

    counts: dict[str, int] = dict(Counter(f.severity for f in findings))
    for sev in _SEVERITY_ORDER:
        n = counts.get(sev, 0)
        if n > 0:
            label = sev.capitalize()
            lines.append(f'    "{label}" : {n}')

    return "\n".join(lines) + "\n"


def render_mermaid_tech_overview(tech_dict: dict[str, bool]) -> str:
    """Render a Mermaid flowchart showing detected technologies."""
    lines: list[str] = []
    lines.append("flowchart LR")
    lines.append("    scan[NFR Review Scan]")

    detected = {k: v for k, v in tech_dict.items() if v}
    for key in sorted(detected):
        node_id = _MERMAID_ID_RE.sub("_", key)
        label = _to_title_case(key)
        lines.append(f"    scan --> {node_id}[{_quote_label(label)}]")

    return "\n".join(lines) + "\n"


def _count_unique_tree_nodes(roots: list[TreeNode]) -> int:
    """Count unique node names across a tree forest."""
    names: set[str] = set()

    def _walk(node: TreeNode) -> None:
        if node.name not in names:
            names.add(node.name)
            for child in node.children:
                _walk(child)

    for root in roots:
        _walk(root)
    return len(names)


def _render_mermaid_tree_edges(
    ecosystem: str,
    node: TreeNode,
    lines: list[str],
    visited: set[tuple[str, str]],
    rendered_nodes: set[str] | None = None,
) -> None:
    parent_id = _safe_id(ecosystem, node.name)
    for child in node.children:
        child_id = _safe_id(ecosystem, child.name)
        if rendered_nodes is not None and (
            parent_id not in rendered_nodes or child_id not in rendered_nodes
        ):
            continue
        edge_key = (parent_id, child_id)
        if edge_key not in visited:
            visited.add(edge_key)
            lines.append(f"        {parent_id} --> {child_id}")
        _render_mermaid_tree_edges(ecosystem, child, lines, visited, rendered_nodes)


def render_mermaid_dep_graph(reports: list[EcosystemDepsReport]) -> str:
    """Render a Mermaid graph showing dependencies grouped by ecosystem."""
    lines: list[str] = []
    lines.append("graph TD")

    if not reports:
        return "\n".join(lines) + "\n"

    for report in reports:
        eco = report.ecosystem
        lines.append(f"    subgraph {eco}")

        if report.tree:
            seen: set[str] = set()
            for root in report.tree:
                _emit_mermaid_tree_nodes(eco, root, lines, seen)
            if len(seen) >= _MAX_DEP_NODES:
                trunc_id = _safe_id(eco, "__truncated__")
                total_unique = _count_unique_tree_nodes(report.tree)
                remaining = total_unique - len(seen)
                if remaining > 0:
                    lines.append(
                        f"        {trunc_id}[{_quote_label(f'... +{remaining} more')}]"
                    )
        else:
            shown = report.upgrades[:_MAX_DEP_NODES]
            for upgrade in shown:
                nid = _safe_id(eco, upgrade.name)
                ver = upgrade.declared_version or ""
                if ver:
                    lines.append(f"        {nid}[{_quote_label(f'{upgrade.name}@{ver}')}]")
                else:
                    lines.append(f"        {nid}[{_quote_label(upgrade.name)}]")
            remaining = len(report.upgrades) - len(shown)
            if remaining > 0:
                trunc_id = _safe_id(eco, "__truncated__")
                lines.append(f"        {trunc_id}[{_quote_label(f'... +{remaining} more')}]")

        lines.append("    end")

        if report.tree:
            edge_visited: set[tuple[str, str]] = set()
            for root in report.tree:
                _render_mermaid_tree_edges(eco, root, lines, edge_visited, seen)

    return "\n".join(lines) + "\n"


def _emit_mermaid_tree_nodes(
    eco: str,
    node: TreeNode,
    lines: list[str],
    seen: set[str],
    max_nodes: int = _MAX_DEP_NODES,
) -> None:
    if len(seen) >= max_nodes:
        return
    nid = _safe_id(eco, node.name)
    if nid not in seen:
        seen.add(nid)
        if node.version:
            lines.append(f"        {nid}[{_quote_label(f'{node.name}@{node.version}')}]")
        else:
            lines.append(f"        {nid}[{_quote_label(node.name)}]")
    for child in node.children:
        _emit_mermaid_tree_nodes(eco, child, lines, seen, max_nodes)


def render_jdepend_metrics_table(packages: list[dict]) -> str:
    """Render an HTML table of JDepend package metrics sorted by distance.

    Filters out noise rows where Ca, Ce, and total_classes are all zero
    (external dependencies that jdepend cannot introspect).  Numeric columns
    use ``white-space: nowrap`` so values like ``0.86`` never wrap in PDF.
    """
    if not packages:
        return ""

    # Filter out all-zero noise rows (external deps jdepend can't introspect)
    filtered: list[dict] = []
    for pkg in packages:
        ca = pkg.get("ca", pkg.get("Ca", 0))
        ce = pkg.get("ce", pkg.get("Ce", 0))
        total = pkg.get("total_classes", pkg.get("TotalClasses", 0))
        # Keep if at least one metric is non-zero
        if ca or ce or (isinstance(total, int) and total):
            filtered.append(pkg)

    if not filtered:
        return ""

    sorted_pkgs = sorted(filtered, key=lambda p: p.get("d", p.get("D", 0.0)), reverse=True)

    nw = ' class="nowrap"'
    rows: list[str] = []
    for pkg in sorted_pkgs:
        name = pkg.get("name", "unknown")
        ca = pkg.get("ca", pkg.get("Ca", 0))
        ce = pkg.get("ce", pkg.get("Ce", 0))
        a = pkg.get("a", pkg.get("A", 0.0))
        i = pkg.get("i", pkg.get("I", 0.0))
        d = pkg.get("d", pkg.get("D", 0.0))
        total = pkg.get("total_classes", pkg.get("TotalClasses", "-"))
        rows.append(
            f"<tr><td><code>{name}</code></td>"
            f"<td{nw}>{ca}</td><td{nw}>{ce}</td>"
            f"<td{nw}>{a:.2f}</td><td{nw}>{i:.2f}</td>"
            f"<td{nw}>{d:.2f}</td><td{nw}>{total}</td></tr>"
        )

    return (
        "<h3>JDepend Package Metrics</h3>\n"
        '<table class="jdepend-metrics"><thead><tr>'
        "<th>Package</th><th>Ca</th><th>Ce</th>"
        "<th>A</th><th>I</th><th>D</th><th>Classes</th>"
        "</tr></thead><tbody>\n" + "\n".join(rows) + "\n</tbody></table>\n"
        "<p><em>Ca=Afferent Coupling, Ce=Efferent Coupling,"
        " A=Abstractness, I=Instability, D=Distance from Main Sequence</em></p>\n"
    )


def render_jdepend_dot(packages: list[dict]) -> str:
    """Render a DOT digraph of JDepend package dependencies.

    Uses DependsUpon data from the evidence payload when available.
    Nodes are colored by distance from the main sequence.
    """
    if not packages:
        return ""

    lines = [
        "digraph jdepend {",
        "  rankdir=LR;",
        "  node [shape=box, style=filled, fontsize=10];",
    ]

    for pkg in packages:
        name = pkg.get("name", "unknown")
        node_id = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        d = pkg.get("d", pkg.get("D", 0.0))
        if d > 0.5:
            color = "#ffcccc"
        elif d > 0.3:
            color = "#fff3cc"
        else:
            color = "#ccffcc"
        label = f"{name}\\nD={d:.2f}"
        lines.append(f'  {node_id} [label="{label}", fillcolor="{color}"];')

    for pkg in packages:
        name = pkg.get("name", "unknown")
        node_id = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        for dep in pkg.get("depends_upon", []):
            dep_id = re.sub(r"[^a-zA-Z0-9_]", "_", dep)
            lines.append(f"  {node_id} -> {dep_id};")

    lines.append("}")
    return "\n".join(lines) + "\n"


def render_jdepend_mermaid(packages: list[dict]) -> str:
    """Render a Mermaid flowchart of JDepend package dependencies."""
    if not packages:
        return ""

    lines = ["graph TD"]

    pkg_ids: dict[str, str] = {}
    for pkg in packages:
        name = pkg.get("name", "unknown")
        node_id = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        pkg_ids[name] = node_id
        d = pkg.get("d", pkg.get("D", 0.0))
        short = name.rsplit(".", 1)[-1] if "." in name else name
        label = f"{short} D={d:.2f}"
        lines.append(f"    {node_id}[{_quote_label(label)}]")

    for pkg in packages:
        name = pkg.get("name", "unknown")
        node_id = pkg_ids[name]
        for dep in pkg.get("depends_upon", []):
            dep_id = re.sub(r"[^a-zA-Z0-9_]", "_", dep)
            lines.append(f"    {node_id} --> {dep_id}")

    return "\n".join(lines) + "\n"


_SEQUENCE_RE = re.compile(
    r"```mermaid\s*\n(sequenceDiagram\b.*?)```",
    re.DOTALL,
)


def extract_sequence_diagrams(findings: list[Finding]) -> dict[str, str]:
    """Extract Mermaid sequenceDiagram blocks embedded in finding summaries."""
    diagrams: dict[str, str] = {}
    idx = 0
    for f in findings:
        for m in _SEQUENCE_RE.finditer(f.summary):
            idx += 1
            mermaid = m.group(1).strip()
            title = f"Call Sequence {idx}"
            diagrams[title] = mermaid
    return diagrams


def build_topology_diagram(evidence: list[Evidence]) -> dict[str, str]:
    """Build a topology Mermaid diagram from OTel trace evidence."""
    from nfr_review.output.topology import build_topology_graph, render_topology_mermaid

    graph = build_topology_graph(evidence)
    if not graph.edges:
        return {}
    return {"Runtime Service Topology": render_topology_mermaid(graph)}


def collect_dynamic_diagrams(
    findings: list[Finding],
    evidence: list[Evidence],
) -> dict[str, str]:
    """Collect all dynamic diagrams (topology + sequence) into a single dict."""
    result: dict[str, str] = {}
    result.update(build_topology_diagram(evidence))
    result.update(extract_sequence_diagrams(findings))
    return result


def render_mermaid_repo_deps(
    components: list[Component],
    integrations: list[IntegrationPoint],
) -> str | None:
    """Render a Mermaid flowchart of repo-to-repo dependencies.

    Each edge is annotated with the boundary component names that
    connect the two repos.  Returns ``None`` when there are no
    cross-repo edges.
    """
    comp_map: dict[str, Component] = {c.id: c for c in components}

    edge_annotations: dict[tuple[str, str], list[str]] = {}
    for ip in integrations:
        if not ip.is_cross_repo:
            continue
        src = comp_map.get(ip.source_component_id)
        tgt = comp_map.get(ip.target_component_id)
        if not src or not tgt or not src.repo or not tgt.repo:
            continue
        if src.repo == tgt.repo:
            continue
        key = (src.repo, tgt.repo)
        annotation = f"{src.name} -> {tgt.name}"
        edge_annotations.setdefault(key, []).append(annotation)

    if not edge_annotations:
        return None

    repos: set[str] = set()
    for s, t in edge_annotations:
        repos.add(s)
        repos.add(t)

    lines = ["flowchart LR"]
    for repo in sorted(repos):
        nid = _MERMAID_ID_RE.sub("_", repo)
        lines.append(f"    {nid}[{_quote_label(repo)}]")

    for (src_repo, tgt_repo), edge_labels in sorted(edge_annotations.items()):
        src_id = _MERMAID_ID_RE.sub("_", src_repo)
        tgt_id = _MERMAID_ID_RE.sub("_", tgt_repo)
        unique = list(dict.fromkeys(edge_labels))
        shown = unique[:5]
        label = " | ".join(shown)
        if len(unique) > 5:
            label += f" | +{len(unique) - 5} more"
        lines.append(f"    {src_id} -->|{_quote_label(label)}| {tgt_id}")

    return "\n".join(lines) + "\n"


__all__ = [
    "build_topology_diagram",
    "collect_dynamic_diagrams",
    "extract_sequence_diagrams",
    "render_jdepend_dot",
    "render_jdepend_mermaid",
    "render_jdepend_metrics_table",
    "render_mermaid_dep_graph",
    "render_mermaid_repo_deps",
    "render_mermaid_severity_pie",
    "render_mermaid_tech_overview",
]
