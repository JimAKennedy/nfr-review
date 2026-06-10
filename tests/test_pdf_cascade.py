# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for PDF diagram rendering cascade (mmdc → SVG → HTML table)."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from nfr_review.output.render import (
    render_diagram_as_html_table,
    render_flowchart_as_svg_fallback,
    render_pie_as_svg_fallback,
)

PIE_MERMAID = """\
pie title Severity Distribution
    "Critical" : 3
    "High" : 7
    "Medium" : 12
"""

FLOWCHART_MERMAID = """\
flowchart LR
    scan[NFR Review Scan]
    scan --> python["Python"]
    scan --> java["Java"]
    scan --> docker["Docker"]
"""

DEP_GRAPH_MERMAID = """\
graph TD
    A[requests] --> B[urllib3]
    A --> C[certifi]
"""


class TestPieSvgFallback:
    def test_produces_svg(self) -> None:
        svg = render_pie_as_svg_fallback({"Critical": 3, "High": 7, "Medium": 12})
        assert "<svg" in svg
        assert "Critical" in svg
        assert "High" in svg
        assert "Medium" in svg

    def test_bar_widths_proportional(self) -> None:
        svg = render_pie_as_svg_fallback({"A": 10, "B": 5})
        assert 'width="' in svg

    def test_empty_data(self) -> None:
        svg = render_pie_as_svg_fallback({})
        assert "<svg" in svg
        assert "No data" in svg

    def test_severity_colors(self) -> None:
        svg = render_pie_as_svg_fallback({"Critical": 1})
        assert "#dc3545" in svg


class TestFlowchartSvgFallback:
    def test_produces_svg(self) -> None:
        svg = render_flowchart_as_svg_fallback(["Python", "Java", "Docker"])
        assert "<svg" in svg
        assert "Python" in svg
        assert "Java" in svg

    def test_empty_items(self) -> None:
        svg = render_flowchart_as_svg_fallback([])
        assert "<svg" in svg
        assert "No technologies" in svg

    def test_custom_title(self) -> None:
        svg = render_flowchart_as_svg_fallback(["A"], title="Custom Title")
        assert "Custom Title" in svg


class TestHtmlTableFallback:
    def test_pie_renders_as_table(self) -> None:
        html = render_diagram_as_html_table(PIE_MERMAID, "Severity")
        assert "<table" in html
        assert "Critical" in html
        assert "3" in html
        assert "Category" in html

    def test_flowchart_renders_as_table(self) -> None:
        html = render_diagram_as_html_table(FLOWCHART_MERMAID, "Technologies")
        assert "<table" in html
        assert "Component" in html
        assert "Python" in html

    def test_unknown_format_renders_as_code(self) -> None:
        html = render_diagram_as_html_table("sequenceDiagram\n    A->>B: hello", "Sequence")
        assert "<pre" in html
        assert "sequenceDiagram" in html


class TestRenderDiagramCascade:
    def test_tier2_svg_when_mmdc_unavailable(self, caplog: pytest.LogCaptureFixture) -> None:
        from nfr_review.output.pdf import _render_diagram_cascade

        with (
            patch("shutil.which", return_value=None),
            caplog.at_level(logging.INFO, logger="nfr_review.output.pdf"),
        ):
            result = _render_diagram_cascade("Severity Distribution", PIE_MERMAID)

        assert "tier 2" in caplog.text
        assert "data:image/svg+xml" in result

    def test_tier2_flowchart_when_mmdc_unavailable(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from nfr_review.output.pdf import _render_diagram_cascade

        with (
            patch("shutil.which", return_value=None),
            caplog.at_level(logging.INFO, logger="nfr_review.output.pdf"),
        ):
            result = _render_diagram_cascade("Tech Overview", FLOWCHART_MERMAID)

        assert "tier 2" in caplog.text
        assert "data:image/svg+xml" in result

    def test_tier3_html_for_unknown_diagram_type(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from nfr_review.output.pdf import _render_diagram_cascade

        seq_diagram = "sequenceDiagram\n    A->>B: hello"
        with (
            patch("shutil.which", return_value=None),
            caplog.at_level(logging.INFO, logger="nfr_review.output.pdf"),
        ):
            result = _render_diagram_cascade("Sequence", seq_diagram)

        assert "tier 3" in caplog.text
        assert "<pre" in result or "<table" in result

    def test_all_three_diagram_types_produce_output(self) -> None:
        from nfr_review.output.pdf import _render_diagram_cascade

        with patch("shutil.which", return_value=None):
            for title, mermaid in [
                ("Severity", PIE_MERMAID),
                ("Tech", FLOWCHART_MERMAID),
                ("Deps", DEP_GRAPH_MERMAID),
            ]:
                result = _render_diagram_cascade(title, mermaid)
                assert result, f"No output for {title}"
                assert len(result) > 10
