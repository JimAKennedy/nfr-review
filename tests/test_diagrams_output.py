# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for nfr_review.output.diagrams — Mermaid and DOT diagram generators."""

from __future__ import annotations

from nfr_review.dep_solver import TreeNode
from nfr_review.deps_analysis import DepUpgradeInfo, EcosystemDepsReport
from nfr_review.models import Finding
from nfr_review.output.diagrams import (
    extract_sequence_diagrams,
    render_jdepend_dot,
    render_jdepend_mermaid,
    render_jdepend_metrics_table,
    render_mermaid_dep_graph,
    render_mermaid_severity_pie,
    render_mermaid_tech_overview,
)


def _tree(name: str, ver: str, children: list[TreeNode] | None = None) -> TreeNode:
    return TreeNode(name=name, version=ver, children=children or [])


def _upgrade(name: str, declared: str) -> DepUpgradeInfo:
    return DepUpgradeInfo(
        name=name,
        declared_version=declared,
        latest_version=None,
        recommended_version=None,
        gap_description="none",
    )


def _finding(severity: str = "medium", summary: str = "test") -> Finding:
    return Finding(
        rule_id="TEST-001",
        rag="amber",
        severity=severity,
        summary=summary,
        recommendation="Fix it.",
        evidence_locator="test.py:1",
        collector_name="test",
        collector_version="1.0",
        confidence=0.9,
        pattern_tag="test-pattern",
    )


# ── render_mermaid_severity_pie ──────────────────────────────────────


def test_severity_pie_empty():
    result = render_mermaid_severity_pie([])
    assert "pie title Severity Distribution" in result
    assert '"' not in result


def test_severity_pie_counts():
    findings = [
        _finding("critical"),
        _finding("high"),
        _finding("high"),
        _finding("medium"),
    ]
    result = render_mermaid_severity_pie(findings)
    assert '"Critical" : 1' in result
    assert '"High" : 2' in result
    assert '"Medium" : 1' in result
    assert "Low" not in result


def test_severity_pie_ordering():
    findings = [_finding("low"), _finding("critical")]
    result = render_mermaid_severity_pie(findings)
    critical_pos = result.index("Critical")
    low_pos = result.index("Low")
    assert critical_pos < low_pos


# ── render_mermaid_tech_overview ─────────────────────────────────────


def test_tech_overview_empty():
    result = render_mermaid_tech_overview({})
    assert "flowchart LR" in result
    assert "scan[NFR Review Scan]" in result


def test_tech_overview_only_detected():
    tech = {"spring": True, "django": False, "docker": True}
    result = render_mermaid_tech_overview(tech)
    assert "docker" in result.lower() or "Docker" in result
    assert "spring" in result.lower() or "Spring" in result
    assert "django" not in result.lower()


def test_tech_overview_sorted():
    tech = {"zeppelin": True, "alpha": True}
    result = render_mermaid_tech_overview(tech)
    alpha_pos = result.index("alpha") if "alpha" in result else result.index("Alpha")
    zeppelin_pos = (
        result.index("zeppelin") if "zeppelin" in result else result.index("Zeppelin")
    )
    assert alpha_pos < zeppelin_pos


# ── render_mermaid_dep_graph ─────────────────────────────────────────


def test_dep_graph_empty():
    result = render_mermaid_dep_graph([])
    assert "graph TD" in result


def test_dep_graph_with_tree():
    child = _tree("sub-dep", "0.2")
    root = _tree("main-dep", "1.0", [child])
    report = EcosystemDepsReport(
        ecosystem="python",
        manifest_files=["req.txt"],
        upgrades=[],
        tree=[root],
    )
    result = render_mermaid_dep_graph([report])
    assert "subgraph python" in result
    assert "main-dep" in result or "main_dep" in result
    assert "-->" in result


def test_dep_graph_without_tree():
    upgrades = [_upgrade("flask", "2.0"), _upgrade("requests", "2.28")]
    report = EcosystemDepsReport(
        ecosystem="python",
        manifest_files=["req.txt"],
        upgrades=upgrades,
    )
    result = render_mermaid_dep_graph([report])
    assert "flask" in result
    assert "requests" in result


def test_dep_graph_truncation():
    upgrades = [_upgrade(f"pkg-{i}", "1.0") for i in range(100)]
    report = EcosystemDepsReport(
        ecosystem="npm",
        manifest_files=["package.json"],
        upgrades=upgrades,
    )
    result = render_mermaid_dep_graph([report])
    assert "more" in result


# ── render_jdepend_metrics_table ─────────────────────────────────────


def test_jdepend_metrics_empty():
    assert render_jdepend_metrics_table([]) == ""


def test_jdepend_metrics_basic():
    packages = [
        {"name": "com.example.core", "ca": 5, "ce": 3, "a": 0.2, "i": 0.6, "d": 0.2},
    ]
    result = render_jdepend_metrics_table(packages)
    assert "JDepend Package Metrics" in result
    assert "com.example.core" in result
    assert "0.20" in result


def test_jdepend_metrics_sorted_by_distance():
    packages = [
        {"name": "low-d", "ca": 0, "ce": 0, "a": 0.0, "i": 0.0, "d": 0.1},
        {"name": "high-d", "ca": 0, "ce": 0, "a": 0.0, "i": 0.0, "d": 0.9},
    ]
    result = render_jdepend_metrics_table(packages)
    high_pos = result.index("high-d")
    low_pos = result.index("low-d")
    assert high_pos < low_pos


def test_jdepend_metrics_uppercase_keys():
    packages = [
        {"name": "pkg", "Ca": 2, "Ce": 4, "A": 0.5, "I": 0.7, "D": 0.3, "TotalClasses": 10},
    ]
    result = render_jdepend_metrics_table(packages)
    assert "pkg" in result
    assert "0.30" in result


# ── render_jdepend_dot ───────────────────────────────────────────────


def test_jdepend_dot_empty():
    assert render_jdepend_dot([]) == ""


def test_jdepend_dot_basic():
    packages = [
        {"name": "com.a", "d": 0.1, "depends_upon": ["com.b"]},
        {"name": "com.b", "d": 0.6, "depends_upon": []},
    ]
    result = render_jdepend_dot(packages)
    assert "digraph jdepend" in result
    assert "com_a" in result
    assert "com_b" in result
    assert "com_a -> com_b" in result


def test_jdepend_dot_color_by_distance():
    packages = [
        {"name": "healthy", "d": 0.1},
        {"name": "warning", "d": 0.4},
        {"name": "bad", "d": 0.7},
    ]
    result = render_jdepend_dot(packages)
    assert "#ccffcc" in result
    assert "#fff3cc" in result
    assert "#ffcccc" in result


# ── render_jdepend_mermaid ───────────────────────────────────────────


def test_jdepend_mermaid_empty():
    assert render_jdepend_mermaid([]) == ""


def test_jdepend_mermaid_basic():
    packages = [
        {"name": "com.a", "d": 0.1, "depends_upon": ["com.b"]},
        {"name": "com.b", "d": 0.5},
    ]
    result = render_jdepend_mermaid(packages)
    assert "graph TD" in result
    assert "com_a" in result
    assert "-->" in result


# ── extract_sequence_diagrams ────────────────────────────────────────


def test_extract_sequence_no_diagrams():
    findings = [_finding(summary="No diagrams here.")]
    assert extract_sequence_diagrams(findings) == {}


def test_extract_sequence_with_diagram():
    mermaid_block = (
        "```mermaid\nsequenceDiagram\n"
        "    participant A\n"
        "    participant B\n"
        "    A->>B: Hello\n```"
    )
    findings = [_finding(summary=f"Found issue.\n\n{mermaid_block}")]
    result = extract_sequence_diagrams(findings)
    assert len(result) == 1
    title = list(result.keys())[0]
    assert "Call Sequence" in title
    assert "sequenceDiagram" in result[title]
    assert "A->>B" in result[title]


def test_extract_sequence_multiple():
    block1 = "```mermaid\nsequenceDiagram\n    A->>B: First\n```"
    block2 = "```mermaid\nsequenceDiagram\n    C->>D: Second\n```"
    findings = [_finding(summary=f"{block1}\n\n{block2}")]
    result = extract_sequence_diagrams(findings)
    assert len(result) == 2
