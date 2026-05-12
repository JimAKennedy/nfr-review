"""Graphviz DOT text generator for dependency graphs.

Converts EcosystemDepsReport data into valid DOT digraph text with
nodes clustered by ecosystem and edges representing dependency relationships.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nfr_review.dep_solver import TreeNode
    from nfr_review.deps_analysis import EcosystemDepsReport

_DOT_ESCAPE_RE = re.compile(r'([\\"])')


def _escape_dot(value: str) -> str:
    return _DOT_ESCAPE_RE.sub(r"\\\1", value)


def _node_id(ecosystem: str, pkg_name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", f"{ecosystem}__{pkg_name}")
    return safe


def _render_tree_edges(
    ecosystem: str,
    node: TreeNode,
    lines: list[str],
    visited: set[tuple[str, str]],
) -> None:
    parent_id = _node_id(ecosystem, node.name)
    for child in node.children:
        child_id = _node_id(ecosystem, child.name)
        edge_key = (parent_id, child_id)
        if edge_key not in visited:
            visited.add(edge_key)
            lines.append(f"  {parent_id} -> {child_id};")
        _render_tree_edges(ecosystem, child, lines, visited)


def _emit_flat_node(
    eco: str,
    name: str,
    version: str,
    seen_nodes: set[str],
    lines: list[str],
) -> None:
    nid = _node_id(eco, name)
    if nid in seen_nodes:
        return
    seen_nodes.add(nid)
    if version:
        label = f"{_escape_dot(name)}\\n{_escape_dot(version)}"
    else:
        label = _escape_dot(name)
    lines.append(f'    {nid} [label="{label}"];')


def _emit_tree_nodes(
    eco: str,
    nodes: list[TreeNode],
    seen_nodes: set[str],
    lines: list[str],
) -> None:
    for node in nodes:
        _emit_flat_node(eco, node.name, node.version, seen_nodes, lines)
        if node.children:
            _emit_tree_nodes(eco, node.children, seen_nodes, lines)


def render_dot_dependency_graph(reports: list[EcosystemDepsReport]) -> str:
    """Produce a DOT digraph string from dependency reports.

    Nodes are clustered by ecosystem with labels showing name and version.
    Edges connect parent to child based on TreeNode.children.
    Returns a minimal valid digraph when reports are empty.
    """
    lines: list[str] = []
    lines.append("digraph dependencies {")
    lines.append("  rankdir=LR;")
    lines.append('  node [shape=box, style=filled, fillcolor="#e8e8e8"];')

    if not reports:
        lines.append("}")
        return "\n".join(lines) + "\n"

    for idx, report in enumerate(reports):
        eco = report.ecosystem
        lines.append(f"  subgraph cluster_{idx} {{")
        lines.append(f'    label="{_escape_dot(eco)}";')
        lines.append("    style=rounded;")

        seen_nodes: set[str] = set()

        if report.tree:
            _emit_tree_nodes(eco, report.tree, seen_nodes, lines)
        else:
            for upgrade in report.upgrades:
                version = upgrade.declared_version or ""
                _emit_flat_node(eco, upgrade.name, version, seen_nodes, lines)

        lines.append("  }")

        if report.tree:
            edge_visited: set[tuple[str, str]] = set()
            for root in report.tree:
                _render_tree_edges(eco, root, lines, edge_visited)

    lines.append("}")
    return "\n".join(lines) + "\n"


__all__ = ["render_dot_dependency_graph"]
