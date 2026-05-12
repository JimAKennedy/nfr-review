"""Tests for dependency analysis module."""

from __future__ import annotations

from nfr_review.dep_solver import TreeNode
from nfr_review.deps_analysis import DepUpgradeInfo, _compute_gap
from nfr_review.output.deps_report import (
    render_ascii_tree,
    render_deps_section,
    render_deps_terminal,
    render_upgrade_table,
)


class TestComputeGap:
    def test_up_to_date(self) -> None:
        assert _compute_gap("1.2.3", "1.2.3") == "up to date"

    def test_major_gap(self) -> None:
        assert _compute_gap("1.0.0", "3.0.0") == "2 major"

    def test_minor_gap(self) -> None:
        assert _compute_gap("1.0.0", "1.5.0") == "5 minor"

    def test_patch_gap(self) -> None:
        assert _compute_gap("1.0.0", "1.0.3") == "3 patch"

    def test_unknown_target(self) -> None:
        assert _compute_gap("1.0.0", None) == "unknown"

    def test_invalid_version(self) -> None:
        assert _compute_gap("not-a-version", "1.0.0") == "unknown"

    def test_target_older(self) -> None:
        assert _compute_gap("2.0.0", "1.0.0") == "up to date"


class TestRenderAsciiTree:
    def test_single_root_no_children(self) -> None:
        tree = [TreeNode(name="foo", version="1.0.0")]
        result = render_ascii_tree(tree)
        assert "foo  1.0.0" in result

    def test_version_arrow(self) -> None:
        tree = [TreeNode(name="foo", version="2.0.0")]
        declared = {"foo": "1.0.0"}
        result = render_ascii_tree(tree, declared)
        assert "foo  1.0.0 → 2.0.0" in result

    def test_no_arrow_same_version(self) -> None:
        tree = [TreeNode(name="foo", version="1.0.0")]
        declared = {"foo": "1.0.0"}
        result = render_ascii_tree(tree, declared)
        assert "→" not in result

    def test_nested_children(self) -> None:
        tree = [
            TreeNode(
                name="root",
                version="1.0.0",
                children=[
                    TreeNode(name="child-a", version="2.0.0"),
                    TreeNode(
                        name="child-b",
                        version="3.0.0",
                        children=[TreeNode(name="grandchild", version="0.1.0")],
                    ),
                ],
            )
        ]
        result = render_ascii_tree(tree)
        assert "├── child-a" in result
        assert "└── child-b" in result
        assert "    └── grandchild" in result

    def test_empty_tree(self) -> None:
        result = render_ascii_tree([])
        assert "no dependencies" in result


class TestRenderUpgradeTable:
    def test_basic_table(self) -> None:
        upgrades = [
            DepUpgradeInfo(
                name="pkg-a",
                declared_version="1.0.0",
                latest_version="2.0.0",
                recommended_version="2.0.0",
                gap_description="1 major",
            ),
        ]
        result = render_upgrade_table(upgrades)
        assert "| 1 | pkg-a" in result
        assert "1.0.0" in result
        assert "2.0.0" in result
        assert "1 major" in result

    def test_empty_list(self) -> None:
        result = render_upgrade_table([])
        assert "No dependencies" in result

    def test_missing_versions(self) -> None:
        upgrades = [
            DepUpgradeInfo(
                name="pkg-b",
                declared_version="",
                latest_version=None,
                recommended_version=None,
                gap_description="unknown",
            ),
        ]
        result = render_upgrade_table(upgrades)
        assert "pkg-b" in result
        assert "unknown" in result


class TestRenderDepsSection:
    def test_no_reports(self) -> None:
        result = render_deps_section([])
        assert "No dependency manifests" in result

    def test_renders_ecosystem(self) -> None:
        from nfr_review.deps_analysis import EcosystemDepsReport

        reports = [
            EcosystemDepsReport(
                ecosystem="maven",
                manifest_files=["pom.xml"],
                upgrades=[
                    DepUpgradeInfo(
                        name="foo:bar",
                        declared_version="1.0",
                        latest_version="2.0",
                        recommended_version="2.0",
                        gap_description="1 major",
                    ),
                ],
                tree=[TreeNode(name="foo:bar", version="2.0")],
            )
        ]
        result = render_deps_section(reports)
        assert "MAVEN Dependencies" in result
        assert "Upgrade Summary" in result
        assert "Dependency Tree" in result
        assert "foo:bar" in result

    def test_unsolvable(self) -> None:
        from nfr_review.deps_analysis import EcosystemDepsReport

        reports = [
            EcosystemDepsReport(
                ecosystem="npm",
                manifest_files=["package.json"],
                upgrades=[],
                unsolvable=True,
                blocking_constraints=["foo requires bar>=2.0"],
            )
        ]
        result = render_deps_section(reports)
        assert "Resolution failed" in result
        assert "foo requires bar>=2.0" in result


class TestRenderDepsTerminal:
    def test_no_reports(self) -> None:
        result = render_deps_terminal([])
        assert "No dependency manifests" in result
