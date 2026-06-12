# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for nfr_review.output.deps_report — ASCII tree and upgrade table renderers."""

from __future__ import annotations

from nfr_review.dep_solver import TreeNode
from nfr_review.deps_analysis import DepUpgradeInfo, EcosystemDepsReport
from nfr_review.output.deps_report import (
    render_ascii_tree,
    render_deps_section,
    render_deps_terminal,
    render_upgrade_table,
)


def _tree(name: str, ver: str, children: list[TreeNode] | None = None) -> TreeNode:
    return TreeNode(name=name, version=ver, children=children or [])


def _upgrade(
    name: str,
    declared: str,
    latest: str | None = None,
    recommended: str | None = None,
    gap: str = "none",
) -> DepUpgradeInfo:
    return DepUpgradeInfo(
        name=name,
        declared_version=declared,
        latest_version=latest,
        recommended_version=recommended,
        gap_description=gap,
    )


# ── render_ascii_tree ────────────────────────────────────────────────


def test_ascii_tree_empty():
    assert render_ascii_tree([]) == "(no dependencies resolved)\n"


def test_ascii_tree_single_root():
    root = _tree("mylib", "1.0.0")
    result = render_ascii_tree([root])
    assert "mylib" in result
    assert "1.0.0" in result


def test_ascii_tree_version_annotation():
    root = _tree("mylib", "1.2.0")
    result = render_ascii_tree([root], declared_versions={"mylib": "1.0.0"})
    assert "1.0.0 → 1.2.0" in result


def test_ascii_tree_no_version_diff():
    root = _tree("mylib", "1.0.0")
    result = render_ascii_tree([root], declared_versions={"mylib": "1.0.0"})
    assert "→" not in result
    assert "1.0.0" in result


def test_ascii_tree_nested():
    child = _tree("child-lib", "2.0.0")
    root = _tree("parent", "1.0.0", [child])
    result = render_ascii_tree([root])
    assert "parent" in result
    assert "child-lib" in result
    assert "└── " in result


def test_ascii_tree_multiple_children():
    children = [_tree("alpha", "1.0"), _tree("beta", "2.0")]
    root = _tree("root", "0.1", children)
    result = render_ascii_tree([root])
    assert "├── " in result
    assert "└── " in result


def test_ascii_tree_multiple_roots():
    roots = [_tree("root-a", "1.0"), _tree("root-b", "2.0")]
    result = render_ascii_tree(roots)
    assert "root-a" in result
    assert "root-b" in result


# ── render_upgrade_table ─────────────────────────────────────────────


def test_upgrade_table_empty():
    assert render_upgrade_table([]) == "No dependencies found.\n"


def test_upgrade_table_single():
    upgrades = [_upgrade("requests", "2.28.0", "2.31.0", "2.31.0", "3 minor")]
    result = render_upgrade_table(upgrades)
    assert "| 1 |" in result
    assert "requests" in result
    assert "2.28.0" in result
    assert "2.31.0" in result
    assert "3 minor" in result


def test_upgrade_table_missing_versions():
    upgrades = [_upgrade("unknown-pkg", "1.0.0", None, None, "unknown")]
    result = render_upgrade_table(upgrades)
    assert "| - |" in result


# ── render_deps_section ──────────────────────────────────────────────


def test_deps_section_no_reports():
    result = render_deps_section([])
    assert "No dependency manifests detected" in result


def test_deps_section_with_tree():
    child = _tree("sub", "0.2")
    root = _tree("main-dep", "1.0", [child])
    upgrades = [_upgrade("main-dep", "1.0", "1.1", "1.1", "1 minor")]
    report = EcosystemDepsReport(
        ecosystem="python",
        manifest_files=["requirements.txt"],
        upgrades=upgrades,
        tree=[root],
    )
    result = render_deps_section([report])
    assert "PYTHON" in result
    assert "requirements.txt" in result
    assert "Upgrade Summary" in result
    assert "Dependency Tree" in result
    assert "main-dep" in result


def test_deps_section_unsolvable():
    report = EcosystemDepsReport(
        ecosystem="maven",
        manifest_files=["pom.xml"],
        upgrades=[],
        unsolvable=True,
        blocking_constraints=["dep-a requires >=2.0, dep-b requires <2.0"],
    )
    result = render_deps_section([report])
    assert "Resolution failed" in result
    assert "dep-a requires" in result


# ── render_deps_terminal ─────────────────────────────────────────────


def test_deps_terminal_no_reports():
    result = render_deps_terminal([])
    assert "No dependency manifests detected" in result


def test_deps_terminal_with_report():
    upgrades = [_upgrade("flask", "2.0", "3.0", "3.0", "1 major")]
    report = EcosystemDepsReport(
        ecosystem="python",
        manifest_files=["setup.py"],
        upgrades=upgrades,
    )
    result = render_deps_terminal([report])
    assert "PYTHON" in result
    assert "setup.py" in result
    assert "flask" in result


def test_deps_terminal_unsolvable():
    report = EcosystemDepsReport(
        ecosystem="npm",
        manifest_files=["package.json"],
        upgrades=[],
        unsolvable=True,
        blocking_constraints=["conflict-a", "conflict-b"],
    )
    result = render_deps_terminal([report])
    assert "FAILED" in result
    assert "conflict-a" in result
