"""Tests for Mermaid diagram text generators."""

from __future__ import annotations

from nfr_review.dep_solver import TreeNode
from nfr_review.deps_analysis import DepUpgradeInfo, EcosystemDepsReport
from nfr_review.models import Finding
from nfr_review.output.diagrams import (
    render_mermaid_dep_graph,
    render_mermaid_severity_pie,
    render_mermaid_tech_overview,
)


def _make_finding(severity: str = "medium", **overrides: object) -> Finding:
    defaults = {
        "rule_id": "TEST-001",
        "rag": "amber",
        "severity": severity,
        "summary": "test finding",
        "recommendation": "fix it",
        "evidence_locator": "test.py:1",
        "collector_name": "test",
        "collector_version": "1.0",
        "confidence": 0.9,
        "pattern_tag": "test-tag",
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


def _make_report(
    ecosystem: str,
    upgrades: list[tuple[str, str]] | None = None,
    tree: list[TreeNode] | None = None,
) -> EcosystemDepsReport:
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


# ── Severity Pie ─────────────────────────────────────────────


class TestSeverityPie:
    def test_empty_findings(self) -> None:
        result = render_mermaid_severity_pie([])
        assert result.startswith("pie title Severity Distribution")
        assert result.count('"') == 0

    def test_single_severity(self) -> None:
        findings = [_make_finding(severity="high")]
        result = render_mermaid_severity_pie(findings)
        assert '"High" : 1' in result

    def test_all_severities(self) -> None:
        severities = ("critical", "high", "medium", "low", "info")
        findings = [_make_finding(severity=s) for s in severities]
        result = render_mermaid_severity_pie(findings)
        for label in ("Critical", "High", "Medium", "Low", "Info"):
            assert f'"{label}" : 1' in result

    def test_multiple_same_severity(self) -> None:
        findings = [_make_finding(severity="high") for _ in range(3)]
        result = render_mermaid_severity_pie(findings)
        assert '"High" : 3' in result

    def test_pie_syntax_valid(self) -> None:
        findings = [_make_finding(severity="medium"), _make_finding(severity="high")]
        result = render_mermaid_severity_pie(findings)
        lines = result.strip().splitlines()
        assert lines[0].startswith("pie")
        assert "title" in lines[0]

    def test_severity_ordering(self) -> None:
        findings = [_make_finding(severity="info"), _make_finding(severity="critical")]
        result = render_mermaid_severity_pie(findings)
        crit_pos = result.index("Critical")
        info_pos = result.index("Info")
        assert crit_pos < info_pos


# ── Tech Overview ────────────────────────────────────────────


class TestTechOverview:
    def test_empty_dict(self) -> None:
        result = render_mermaid_tech_overview({})
        assert result.startswith("flowchart LR")
        assert "scan[NFR Review Scan]" in result

    def test_all_false(self) -> None:
        result = render_mermaid_tech_overview({"java": False, "python": False})
        lines = result.strip().splitlines()
        assert len(lines) == 2  # flowchart LR + scan node only

    def test_single_tech(self) -> None:
        result = render_mermaid_tech_overview({"java": True})
        assert "scan --> java[Java]" in result

    def test_multiple_techs(self) -> None:
        result = render_mermaid_tech_overview({"java": True, "python": True, "go": False})
        assert "java[Java]" in result
        assert "python[Python]" in result
        assert "go" not in result.split("scan[NFR Review Scan]")[1].split("\n")[0]

    def test_snake_case_labels(self) -> None:
        result = render_mermaid_tech_overview({"spring_boot": True})
        assert "spring_boot[Spring Boot]" in result

    def test_flowchart_syntax(self) -> None:
        result = render_mermaid_tech_overview({"helm": True})
        assert result.strip().splitlines()[0] == "flowchart LR"

    def test_deterministic_order(self) -> None:
        tech = {"python": True, "java": True, "go": True}
        r1 = render_mermaid_tech_overview(tech)
        r2 = render_mermaid_tech_overview(tech)
        assert r1 == r2
        lines = [ln.strip() for ln in r1.strip().splitlines() if "-->" in ln]
        labels = [ln.split("-->")[1].strip().split("[")[0] for ln in lines]
        assert labels == sorted(labels)


# ── Dep Graph ────────────────────────────────────────────────


class TestDepGraph:
    def test_empty_reports(self) -> None:
        result = render_mermaid_dep_graph([])
        assert result.startswith("graph LR")
        assert "subgraph" not in result

    def test_single_ecosystem_flat(self) -> None:
        report = _make_report("maven", upgrades=[("spring-core", "5.3.0"), ("guava", "31.1")])
        result = render_mermaid_dep_graph([report])
        assert "subgraph maven" in result
        assert "spring-core@5.3.0" in result
        assert "guava@31.1" in result
        assert "-->" not in result

    def test_single_ecosystem_tree(self) -> None:
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
        result = render_mermaid_dep_graph([report])
        assert "-->" in result
        assert "spring-core@5.3.0" in result
        assert "spring-jcl@5.3.0" in result

    def test_multi_ecosystem(self) -> None:
        r1 = _make_report("maven", upgrades=[("spring-core", "5.3.0")])
        r2 = _make_report("npm", upgrades=[("react", "18.2.0")])
        result = render_mermaid_dep_graph([r1, r2])
        assert "subgraph maven" in result
        assert "subgraph npm" in result
        assert result.count("end") == 2

    def test_special_chars_in_names(self) -> None:
        report = _make_report("npm", upgrades=[("@scope/pkg", "1.0.0")])
        result = render_mermaid_dep_graph([report])
        assert "npm___scope_pkg" in result
        assert "@scope/pkg@1.0.0" in result

    def test_dotted_package_name(self) -> None:
        report = _make_report("maven", upgrades=[("org.springframework.boot", "3.1.0")])
        result = render_mermaid_dep_graph([report])
        assert "maven__org_springframework_boot" in result
        assert "org.springframework.boot@3.1.0" in result

    def test_graph_syntax(self) -> None:
        r1 = _make_report(
            "maven",
            tree=[
                TreeNode(
                    name="a",
                    version="1.0",
                    children=[
                        TreeNode(name="b", version="2.0", children=[]),
                    ],
                ),
            ],
        )
        r2 = _make_report("npm", upgrades=[("react", "18.0")])
        result = render_mermaid_dep_graph([r1, r2])
        assert result.strip().splitlines()[0] == "graph LR"
        open_count = result.count("subgraph")
        close_count = result.count("    end")
        assert open_count == close_count

    def test_edge_deduplication(self) -> None:
        shared = TreeNode(name="shared", version="1.0", children=[])
        tree = [
            TreeNode(name="a", version="1.0", children=[shared]),
            TreeNode(name="b", version="1.0", children=[shared]),
        ]
        report = _make_report("maven", tree=tree)
        result = render_mermaid_dep_graph([report])
        output_lines = result.splitlines()
        edge_a = [
            ln
            for ln in output_lines
            if "maven__a" in ln and "-->" in ln and "maven__shared" in ln
        ]
        edge_b = [
            ln
            for ln in output_lines
            if "maven__b" in ln and "-->" in ln and "maven__shared" in ln
        ]
        assert len(edge_a) == 1
        assert len(edge_b) == 1

    def test_tree_node_deduplication(self) -> None:
        shared = TreeNode(name="shared", version="1.0", children=[])
        tree = [
            TreeNode(name="a", version="1.0", children=[shared]),
            TreeNode(name="b", version="1.0", children=[shared]),
        ]
        report = _make_report("maven", tree=tree)
        result = render_mermaid_dep_graph([report])
        node_lines = [ln for ln in result.splitlines() if "maven__shared[" in ln]
        assert len(node_lines) == 1

    def test_flat_dep_without_version(self) -> None:
        report = _make_report("pypi", upgrades=[("unknown-pkg", "")])
        result = render_mermaid_dep_graph([report])
        assert "pypi__unknown_pkg[unknown-pkg]" in result
        pkg_line = [ln for ln in result.splitlines() if "unknown_pkg" in ln][0]
        assert "@" not in pkg_line

    def test_tree_node_without_version(self) -> None:
        tree = [TreeNode(name="root", version="", children=[])]
        report = _make_report("pypi", tree=tree)
        result = render_mermaid_dep_graph([report])
        node_lines = [ln for ln in result.splitlines() if "pypi__root[" in ln]
        assert len(node_lines) == 1
        assert "root]" in node_lines[0]
