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
