"""Tests for DOT dependency graph generation."""

from __future__ import annotations

import re

from nfr_review.dep_solver import TreeNode
from nfr_review.deps_analysis import EcosystemDepsReport
from nfr_review.output.dot import render_dot_dependency_graph


def _make_report(
    ecosystem: str,
    upgrades: list[tuple[str, str]] | None = None,
    tree: list[TreeNode] | None = None,
) -> EcosystemDepsReport:
    from nfr_review.deps_analysis import DepUpgradeInfo

    upgrade_list = [
        DepUpgradeInfo(
            name=name,
            declared_version=ver,
            latest_version=None,
            recommended_version=None,
            gap_description="unknown",
        )
        for name, ver in (upgrades or [])
    ]
    return EcosystemDepsReport(
        ecosystem=ecosystem,
        manifest_files=["pom.xml"],
        upgrades=upgrade_list,
        tree=tree,
    )


class TestSingleEcosystemFlatDeps:
    """(1) Single ecosystem with flat deps (no tree)."""

    def test_produces_valid_digraph(self) -> None:
        report = _make_report("maven", upgrades=[("spring-core", "5.3.0"), ("guava", "31.1")])
        dot = render_dot_dependency_graph([report])
        assert dot.startswith("digraph ")
        assert dot.strip().endswith("}")
        assert "spring_core" in dot or "spring" in dot
        assert "guava" in dot

    def test_nodes_have_labels_with_version(self) -> None:
        report = _make_report("maven", upgrades=[("spring-core", "5.3.0")])
        dot = render_dot_dependency_graph([report])
        assert "spring-core" in dot
        assert "5.3.0" in dot

    def test_no_edges_for_flat_deps(self) -> None:
        report = _make_report("maven", upgrades=[("a", "1.0"), ("b", "2.0")])
        dot = render_dot_dependency_graph([report])
        assert "->" not in dot


class TestSingleEcosystemWithTree:
    """(2) Single ecosystem with tree structure."""

    def test_edges_connect_parent_to_child(self) -> None:
        tree = [
            TreeNode(
                name="spring-core",
                version="5.3.0",
                children=[
                    TreeNode(name="spring-jcl", version="5.3.0", children=[]),
                ],
            ),
        ]
        report = _make_report("maven", tree=tree)
        dot = render_dot_dependency_graph([report])
        assert "->" in dot
        assert "spring" in dot

    def test_nested_tree_produces_multiple_edges(self) -> None:
        tree = [
            TreeNode(
                name="a",
                version="1.0",
                children=[
                    TreeNode(
                        name="b",
                        version="2.0",
                        children=[
                            TreeNode(name="c", version="3.0", children=[]),
                        ],
                    ),
                ],
            ),
        ]
        report = _make_report("maven", tree=tree)
        dot = render_dot_dependency_graph([report])
        arrows = dot.count("->")
        assert arrows >= 2

    def test_no_duplicate_edges(self) -> None:
        child = TreeNode(name="shared", version="1.0", children=[])
        tree = [
            TreeNode(name="a", version="1.0", children=[child]),
            TreeNode(name="b", version="1.0", children=[child]),
        ]
        report = _make_report("maven", tree=tree)
        dot = render_dot_dependency_graph([report])
        edge_pattern = re.compile(r"maven__a\s*->\s*maven__shared")
        assert len(edge_pattern.findall(dot)) == 1


class TestMultiEcosystemClustering:
    """(3) Multi-ecosystem clustering."""

    def test_separate_subgraph_clusters(self) -> None:
        r1 = _make_report("maven", upgrades=[("spring-core", "5.3.0")])
        r2 = _make_report("npm", upgrades=[("react", "18.2.0")])
        dot = render_dot_dependency_graph([r1, r2])
        assert "cluster_0" in dot
        assert "cluster_1" in dot
        assert '"maven"' in dot
        assert '"npm"' in dot

    def test_nodes_grouped_by_ecosystem(self) -> None:
        r1 = _make_report("pypi", upgrades=[("requests", "2.31.0")])
        r2 = _make_report("npm", upgrades=[("axios", "1.4.0")])
        dot = render_dot_dependency_graph([r1, r2])
        assert "pypi__requests" in dot
        assert "npm__axios" in dot


class TestEmptyReports:
    """(4) Empty reports produce valid minimal digraph."""

    def test_empty_list(self) -> None:
        dot = render_dot_dependency_graph([])
        assert dot.startswith("digraph ")
        assert dot.strip().endswith("}")
        assert "subgraph" not in dot

    def test_report_with_no_deps_or_tree(self) -> None:
        report = _make_report("maven", upgrades=[], tree=None)
        dot = render_dot_dependency_graph([report])
        assert dot.startswith("digraph ")
        assert dot.strip().endswith("}")


class TestSpecialCharacters:
    """(5) Packages with special characters in names."""

    def test_scoped_npm_package(self) -> None:
        report = _make_report("npm", upgrades=[("@scope/pkg", "1.0.0")])
        dot = render_dot_dependency_graph([report])
        assert dot.startswith("digraph ")
        assert "@scope/pkg" in dot
        assert dot.strip().endswith("}")

    def test_package_with_dots(self) -> None:
        report = _make_report("maven", upgrades=[("org.springframework.boot", "3.1.0")])
        dot = render_dot_dependency_graph([report])
        assert "org.springframework.boot" in dot

    def test_package_with_quotes(self) -> None:
        report = _make_report("npm", upgrades=[('pkg"name', "1.0")])
        dot = render_dot_dependency_graph([report])
        assert '\\"' in dot or "pkg" in dot


class TestLargeGraph:
    """(6) Large graph (20+ nodes) produces valid DOT."""

    def test_twenty_plus_nodes(self) -> None:
        upgrades = [(f"pkg-{i}", f"{i}.0.0") for i in range(25)]
        report = _make_report("pypi", upgrades=upgrades)
        dot = render_dot_dependency_graph([report])
        assert dot.startswith("digraph ")
        assert dot.strip().endswith("}")
        for i in range(25):
            assert f"pkg-{i}" in dot

    def test_large_tree_graph(self) -> None:
        children = [
            TreeNode(name=f"dep-{i}", version=f"{i}.0", children=[]) for i in range(20)
        ]
        tree = [TreeNode(name="root", version="1.0", children=children)]
        report = _make_report("maven", tree=tree)
        dot = render_dot_dependency_graph([report])
        assert dot.count("->") == 20
        assert "digraph" in dot


class TestDotSyntaxValidity:
    """Structural DOT syntax validation."""

    def test_balanced_braces(self) -> None:
        tree = [
            TreeNode(
                name="a",
                version="1.0",
                children=[TreeNode(name="b", version="2.0", children=[])],
            ),
        ]
        r1 = _make_report("maven", tree=tree)
        r2 = _make_report("npm", upgrades=[("react", "18.0")])
        dot = render_dot_dependency_graph([r1, r2])
        assert dot.count("{") == dot.count("}")

    def test_edge_syntax(self) -> None:
        tree = [
            TreeNode(
                name="parent",
                version="1.0",
                children=[TreeNode(name="child", version="2.0", children=[])],
            ),
        ]
        report = _make_report("maven", tree=tree)
        dot = render_dot_dependency_graph([report])
        edge_lines = [line.strip() for line in dot.splitlines() if "->" in line]
        for line in edge_lines:
            assert line.endswith(";")
