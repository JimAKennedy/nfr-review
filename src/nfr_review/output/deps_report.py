# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Dependency tree and upgrade summary renderers.

Produces ASCII tree output, upgrade summary tables, and markdown sections
for dependency analysis results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nfr_review.dep_solver import TreeNode
    from nfr_review.deps_analysis import DepUpgradeInfo, EcosystemDepsReport


def render_ascii_tree(
    roots: list[TreeNode],
    declared_versions: dict[str, str] | None = None,
) -> str:
    """Render a dependency tree as ASCII art with version annotations.

    Each node shows ``name  declared → resolved`` when both versions
    are known and differ, or just ``name  version`` otherwise.
    """
    if not roots:
        return "(no dependencies resolved)\n"

    lines: list[str] = []

    def _render_node(
        node: TreeNode,
        prefix: str,
        is_last: bool,
        is_root: bool,
    ) -> None:
        connector = "" if is_root else ("└── " if is_last else "├── ")
        declared = (declared_versions or {}).get(node.name)

        if declared and declared != node.version and node.version:
            label = f"{node.name}  {declared} → {node.version}"
        elif node.version:
            label = f"{node.name}  {node.version}"
        else:
            label = node.name

        lines.append(f"{prefix}{connector}{label}")

        child_prefix = prefix + ("" if is_root else ("    " if is_last else "│   "))
        for i, child in enumerate(node.children):
            _render_node(child, child_prefix, i == len(node.children) - 1, False)

    for i, root in enumerate(roots):
        _render_node(root, "", i == len(roots) - 1, True)

    return "\n".join(lines) + "\n"


def render_upgrade_table(upgrades: list[DepUpgradeInfo]) -> str:
    """Render an upgrade summary as a markdown table."""
    if not upgrades:
        return "No dependencies found.\n"

    lines = [
        "| # | Package | Current | Latest | Recommended | Gap |",
        "|---|---------|---------|--------|-------------|-----|",
    ]

    for i, u in enumerate(upgrades, 1):
        latest = u.latest_version or "-"
        recommended = u.recommended_version or "-"
        lines.append(
            f"| {i} | {u.name} | {u.declared_version or '-'} "
            f"| {latest} | {recommended} | {u.gap_description} |"
        )

    return "\n".join(lines) + "\n"


def render_deps_section(reports: list[EcosystemDepsReport]) -> str:
    """Render a complete dependency analysis section for the markdown report."""
    if not reports:
        return "## Appendix A — Dependency Tree\n\nNo dependency manifests detected.\n"

    sections: list[str] = ["## Appendix A — Dependency Tree", ""]

    for report in reports:
        sections.append(f"### {report.ecosystem.upper()} Dependencies")
        sections.append("")
        sections.append(f"**Manifests:** {', '.join(f'`{m}`' for m in report.manifest_files)}")
        sections.append("")

        if report.unsolvable:
            sections.append("> **Resolution failed** — constraints are unsolvable:")
            sections.append("")
            for constraint in report.blocking_constraints:
                sections.append(f"> - {constraint}")
            sections.append("")

        sections.append("#### Upgrade Summary")
        sections.append("")
        sections.append(render_upgrade_table(report.upgrades))

        if report.tree:
            declared_versions = {
                u.name: u.declared_version for u in report.upgrades if u.declared_version
            }
            sections.append("#### Dependency Tree")
            sections.append("")
            sections.append("```")
            sections.append(render_ascii_tree(report.tree, declared_versions).rstrip())
            sections.append("```")
            sections.append("")

    return "\n".join(sections)


def render_deps_terminal(reports: list[EcosystemDepsReport]) -> str:
    """Render dependency analysis for terminal output (non-markdown)."""
    if not reports:
        return "No dependency manifests detected.\n"

    sections: list[str] = []

    for report in reports:
        sections.append(f"{'=' * 60}")
        sections.append(f"  {report.ecosystem.upper()} Dependencies")
        sections.append(f"  Manifests: {', '.join(report.manifest_files)}")
        sections.append(f"{'=' * 60}")
        sections.append("")

        if report.unsolvable:
            sections.append("  !! Resolution FAILED — constraints are unsolvable:")
            for constraint in report.blocking_constraints:
                sections.append(f"     - {constraint}")
            sections.append("")

        sections.append("Upgrade Summary:")
        sections.append("")
        sections.append(render_upgrade_table(report.upgrades))

        if report.tree:
            declared_versions = {
                u.name: u.declared_version for u in report.upgrades if u.declared_version
            }
            sections.append("Dependency Tree:")
            sections.append("")
            sections.append(render_ascii_tree(report.tree, declared_versions))

    return "\n".join(sections)


__all__ = [
    "render_ascii_tree",
    "render_deps_section",
    "render_deps_terminal",
    "render_upgrade_table",
]
