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
    from nfr_review.dep_solver import TreeNode
    from nfr_review.deps_analysis import EcosystemDepsReport
    from nfr_review.models import Finding

_SEVERITY_ORDER: tuple[str, ...] = ("critical", "high", "medium", "low", "info")

_MERMAID_ID_RE = re.compile(r"[^a-zA-Z0-9_]")


def _safe_id(ecosystem: str, pkg_name: str) -> str:
    return _MERMAID_ID_RE.sub("_", f"{ecosystem}__{pkg_name}")


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
        lines.append(f"    scan --> {node_id}[{label}]")

    return "\n".join(lines) + "\n"


def _render_mermaid_tree_edges(
    ecosystem: str,
    node: TreeNode,
    lines: list[str],
    visited: set[tuple[str, str]],
) -> None:
    parent_id = _safe_id(ecosystem, node.name)
    for child in node.children:
        child_id = _safe_id(ecosystem, child.name)
        edge_key = (parent_id, child_id)
        if edge_key not in visited:
            visited.add(edge_key)
            lines.append(f"        {parent_id} --> {child_id}")
        _render_mermaid_tree_edges(ecosystem, child, lines, visited)


def render_mermaid_dep_graph(reports: list[EcosystemDepsReport]) -> str:
    """Render a Mermaid graph showing dependencies grouped by ecosystem."""
    lines: list[str] = []
    lines.append("graph LR")

    if not reports:
        return "\n".join(lines) + "\n"

    for report in reports:
        eco = report.ecosystem
        lines.append(f"    subgraph {eco}")

        if report.tree:
            seen: set[str] = set()
            for root in report.tree:
                _emit_mermaid_tree_nodes(eco, root, lines, seen)
        else:
            for upgrade in report.upgrades:
                nid = _safe_id(eco, upgrade.name)
                ver = upgrade.declared_version or ""
                if ver:
                    lines.append(f"        {nid}[{upgrade.name}@{ver}]")
                else:
                    lines.append(f"        {nid}[{upgrade.name}]")

        lines.append("    end")

        if report.tree:
            edge_visited: set[tuple[str, str]] = set()
            for root in report.tree:
                _render_mermaid_tree_edges(eco, root, lines, edge_visited)

    return "\n".join(lines) + "\n"


def _emit_mermaid_tree_nodes(
    eco: str,
    node: TreeNode,
    lines: list[str],
    seen: set[str],
) -> None:
    nid = _safe_id(eco, node.name)
    if nid not in seen:
        seen.add(nid)
        if node.version:
            lines.append(f"        {nid}[{node.name}@{node.version}]")
        else:
            lines.append(f"        {nid}[{node.name}]")
    for child in node.children:
        _emit_mermaid_tree_nodes(eco, child, lines, seen)


__all__ = [
    "render_mermaid_dep_graph",
    "render_mermaid_severity_pie",
    "render_mermaid_tech_overview",
]
