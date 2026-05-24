"""Tests for diagram rendering (Mermaid → PNG, DOT → PNG)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nfr_review.output.render import render_dot_to_png, render_mermaid_to_png

SAMPLE_MERMAID = """\
pie title Severity Distribution
    "Critical" : 3
    "High" : 7
    "Medium" : 12
"""

SAMPLE_DOT = """\
digraph dependencies {
  rankdir=LR;
  node [shape=box];
  A -> B;
  B -> C;
}
"""


class TestRenderMermaidToPng:
    def test_empty_input_returns_none(self, tmp_path: Path) -> None:
        assert render_mermaid_to_png("", tmp_path / "out.png") is None
        assert render_mermaid_to_png("   \n  ", tmp_path / "out.png") is None

    def test_missing_mmdc_returns_none(self, tmp_path: Path) -> None:
        with patch("nfr_review.output.render.shutil.which", return_value=None):
            result = render_mermaid_to_png(SAMPLE_MERMAID, tmp_path / "out.png")
        assert result is None

    def test_mmdc_failure_returns_none(self, tmp_path: Path) -> None:
        with (
            patch("nfr_review.output.render.shutil.which", return_value="/usr/bin/mmdc"),
            patch(
                "nfr_review.output.render.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "mmdc", stderr=b"error"),
            ),
        ):
            result = render_mermaid_to_png(SAMPLE_MERMAID, tmp_path / "out.png")
        assert result is None

    def test_mmdc_timeout_returns_none(self, tmp_path: Path) -> None:
        with (
            patch("nfr_review.output.render.shutil.which", return_value="/usr/bin/mmdc"),
            patch(
                "nfr_review.output.render.subprocess.run",
                side_effect=subprocess.TimeoutExpired("mmdc", 30),
            ),
        ):
            result = render_mermaid_to_png(SAMPLE_MERMAID, tmp_path / "out.png")
        assert result is None

    @pytest.mark.skipif(shutil.which("mmdc") is None, reason="mmdc not installed")
    def test_real_mmdc_renders_png(self, tmp_path: Path) -> None:
        out = tmp_path / "severity.png"
        result = render_mermaid_to_png(SAMPLE_MERMAID, out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 100
        assert out.read_bytes()[:4] == b"\x89PNG"


class TestRenderDotToPng:
    def test_empty_input_returns_none(self, tmp_path: Path) -> None:
        assert render_dot_to_png("", tmp_path / "out.png") is None
        assert render_dot_to_png("   \n  ", tmp_path / "out.png") is None

    def test_missing_dot_returns_none(self, tmp_path: Path) -> None:
        with patch("nfr_review.output.render.shutil.which", return_value=None):
            result = render_dot_to_png(SAMPLE_DOT, tmp_path / "out.png")
        assert result is None

    def test_dot_failure_returns_none(self, tmp_path: Path) -> None:
        with (
            patch("nfr_review.output.render.shutil.which", return_value="/usr/bin/dot"),
            patch(
                "nfr_review.output.render.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "dot", stderr=b"error"),
            ),
        ):
            result = render_dot_to_png(SAMPLE_DOT, tmp_path / "out.png")
        assert result is None

    @pytest.mark.skipif(shutil.which("dot") is None, reason="graphviz dot not installed")
    def test_real_dot_renders_png(self, tmp_path: Path) -> None:
        out = tmp_path / "deps.png"
        result = render_dot_to_png(SAMPLE_DOT, out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 100
        assert out.read_bytes()[:4] == b"\x89PNG"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Output directory is created automatically."""
        out = tmp_path / "nested" / "deep" / "deps.png"
        with (
            patch("nfr_review.output.render.shutil.which", return_value="/usr/bin/dot"),
            patch("nfr_review.output.render.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            render_dot_to_png(SAMPLE_DOT, out)
        assert out.parent.exists()


@pytest.mark.skipif(shutil.which("mmdc") is None, reason="mmdc not installed")
class TestDepGraphEndToEnd:
    """Validate that generated dep graph Mermaid text actually renders."""

    def test_dep_graph_with_tree_renders(self, tmp_path: Path) -> None:
        from nfr_review.dep_solver import TreeNode
        from nfr_review.output.diagrams import render_mermaid_dep_graph

        tree = [
            TreeNode(
                name="spring-boot-starter-web",
                version="3.2.0",
                children=[
                    TreeNode(name="spring-web", version="6.1.0", children=[]),
                    TreeNode(name="tomcat-embed-core", version="10.1.0", children=[]),
                ],
            ),
        ]

        class FakeReport:
            ecosystem = "maven"
            tree = None
            upgrades = []  # type: ignore[var-annotated]

        report = FakeReport()
        report.tree = tree  # type: ignore[assignment]
        mermaid = render_mermaid_dep_graph([report])  # type: ignore[arg-type]

        out = tmp_path / "dep-graph.png"
        result = render_mermaid_to_png(mermaid, out)
        assert result is not None, f"mmdc failed to render dep graph:\n{mermaid}"
        assert out.stat().st_size > 100
        assert out.read_bytes()[:4] == b"\x89PNG"

    def test_dep_graph_flat_renders(self, tmp_path: Path) -> None:
        from nfr_review.output.diagrams import render_mermaid_dep_graph

        class FakeReport:
            ecosystem = "npm"
            tree = None
            upgrades = []  # type: ignore[var-annotated]

        report = FakeReport()
        report.upgrades = [  # type: ignore[assignment]
            type("U", (), {"name": "@scope/pkg", "declared_version": "^1.0.0"})(),
            type("U", (), {"name": "react", "declared_version": "^19.0.0"})(),
        ]
        mermaid = render_mermaid_dep_graph([report])  # type: ignore[arg-type]

        out = tmp_path / "dep-graph-flat.png"
        result = render_mermaid_to_png(mermaid, out)
        assert result is not None, f"mmdc failed to render flat dep graph:\n{mermaid}"
        assert out.stat().st_size > 100

    def test_dep_graph_with_maven_properties_renders(self, tmp_path: Path) -> None:
        from nfr_review.output.diagrams import render_mermaid_dep_graph

        class FakeReport:
            ecosystem = "maven"
            tree = None
            upgrades = []  # type: ignore[var-annotated]

        report = FakeReport()
        report.upgrades = [  # type: ignore[assignment]
            type(
                "U",
                (),
                {
                    "name": "software.amazon.awssdk:s3",
                    "declared_version": "${aws.sdk.version}",
                },
            )(),
            type(
                "U",
                (),
                {
                    "name": "io.awspring.cloud:spring-cloud-aws-starter",
                    "declared_version": "${spring.cloud.aws.version}",
                },
            )(),
        ]
        mermaid = render_mermaid_dep_graph([report])  # type: ignore[arg-type]

        out = tmp_path / "dep-graph-props.png"
        result = render_mermaid_to_png(mermaid, out)
        assert result is not None, (
            f"mmdc failed to render Maven-property dep graph:\n{mermaid}"
        )
        assert out.stat().st_size > 100

    def test_multi_ecosystem_renders(self, tmp_path: Path) -> None:
        from nfr_review.dep_solver import TreeNode
        from nfr_review.output.diagrams import render_mermaid_dep_graph

        class FakeReport:
            ecosystem = ""
            tree = None
            upgrades = []  # type: ignore[var-annotated]

        r1 = FakeReport()
        r1.ecosystem = "maven"
        r1.tree = [  # type: ignore[assignment]
            TreeNode(
                name="spring-core",
                version="6.1.0",
                children=[TreeNode(name="spring-jcl", version="6.1.0", children=[])],
            ),
        ]

        r2 = FakeReport()
        r2.ecosystem = "npm"
        r2.upgrades = [  # type: ignore[assignment]
            type("U", (), {"name": "react", "declared_version": "^19.0.0"})(),
        ]

        mermaid = render_mermaid_dep_graph([r1, r2])  # type: ignore[arg-type]

        out = tmp_path / "dep-graph-multi.png"
        result = render_mermaid_to_png(mermaid, out)
        assert result is not None, f"mmdc failed to render multi-ecosystem graph:\n{mermaid}"
        assert out.stat().st_size > 100
