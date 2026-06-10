# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the self-contained HTML report output."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from nfr_review.output.html import _md_to_html, render_html_report

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "cpp-integration-repo"


@pytest.fixture()
def sample_markdown() -> str:
    return """\
# NFR Review Report — sample-repo

## Report Details

| Field | Value |
|-------|-------|
| **Repository** | `sample-repo` |
| **Tool version** | 0.1.0 |

## Findings Summary

### Findings Summary

| Category | Critical | High | Medium | Low | Info | Total |
|----------|----------|------|--------|-----|------|-------|
| security | 1 | 2 | 0 | 0 | 0 | 3 |
| **Total** | **1** | **2** | **0** | **0** | **0** | **3** |

## Diagrams

### Severity Distribution

```mermaid
pie title Finding Severity
    "Critical" : 1
    "High" : 2
```

### Tech Overview

```mermaid
graph LR
    A[Source] --> B[Build]
```

## Test Results

No test results available.
"""


class TestRenderHtmlReport:
    def test_produces_valid_html_structure(self, sample_markdown: str) -> None:
        html = render_html_report(sample_markdown)
        assert html.startswith("<!DOCTYPE html>")
        assert "<html lang=" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "</head>" in html
        assert "<body>" in html
        assert "</body>" in html

    def test_contains_mermaid_js_bundle(self, sample_markdown: str) -> None:
        html = render_html_report(sample_markdown)
        assert '<script type="module">' in html
        assert "mermaid.initialize" in html
        assert "startOnLoad" in html

    def test_mermaid_blocks_use_pre_class(self, sample_markdown: str) -> None:
        html = render_html_report(sample_markdown)
        mermaid_blocks = re.findall(r'<pre class="mermaid">', html)
        assert len(mermaid_blocks) == 2

    def test_no_fenced_mermaid_code_blocks(self, sample_markdown: str) -> None:
        html = render_html_report(sample_markdown)
        assert "```mermaid" not in html

    def test_all_sections_present(self, sample_markdown: str) -> None:
        html = render_html_report(sample_markdown)
        assert "NFR Review Report" in html
        assert "Report Details" in html
        assert "Findings Summary" in html
        assert "Severity Distribution" in html
        assert "Tech Overview" in html
        assert "Test Results" in html

    def test_no_external_resource_loading(self, sample_markdown: str) -> None:
        html = render_html_report(sample_markdown)
        assert 'src="http' not in html
        assert "src='http" not in html
        assert 'href="http' not in html
        assert "href='http" not in html
        assert '<link rel="stylesheet"' not in html

    def test_self_contained_css(self, sample_markdown: str) -> None:
        html = render_html_report(sample_markdown)
        assert "<style>" in html
        assert "font-family" in html

    def test_tables_rendered(self, sample_markdown: str) -> None:
        html = render_html_report(sample_markdown)
        assert "<table>" in html
        assert "<th>" in html
        assert "<td>" in html

    def test_headings_rendered(self, sample_markdown: str) -> None:
        html = render_html_report(sample_markdown)
        assert "<h1>" in html
        assert "<h2>" in html
        assert "<h3>" in html


class TestMdToHtml:
    def test_heading_levels(self) -> None:
        md = "# H1\n## H2\n### H3\n#### H4"
        html = _md_to_html(md)
        assert "<h1>H1</h1>" in html
        assert "<h2>H2</h2>" in html
        assert "<h3>H3</h3>" in html
        assert "<h4>H4</h4>" in html

    def test_inline_code(self) -> None:
        html = _md_to_html("Use `foo()` here")
        assert "<code>foo()</code>" in html

    def test_bold_text(self) -> None:
        html = _md_to_html("This is **bold** text")
        assert "<strong>bold</strong>" in html

    def test_table_conversion(self) -> None:
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = _md_to_html(md)
        assert "<table>" in html
        assert "<th>A</th>" in html
        assert "<td>1</td>" in html

    def test_mermaid_fence_becomes_pre(self) -> None:
        md = "```mermaid\ngraph LR\n    A-->B\n```"
        html = _md_to_html(md)
        assert '<pre class="mermaid">' in html
        assert "graph LR" in html
        assert "```" not in html

    def test_regular_code_fence(self) -> None:
        md = "```python\nprint('hi')\n```"
        html = _md_to_html(md)
        assert "<pre><code>" in html
        assert "print" in html
        assert '<pre class="mermaid">' not in html

    def test_html_escaping_in_code(self) -> None:
        md = "```\n<script>alert('xss')</script>\n```"
        html = _md_to_html(md)
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_horizontal_rule(self) -> None:
        html = _md_to_html("above\n\n---\n\nbelow")
        assert "<hr>" in html

    def test_paragraphs(self) -> None:
        html = _md_to_html("First paragraph.\n\nSecond paragraph.")
        assert "<p>First paragraph.</p>" in html
        assert "<p>Second paragraph.</p>" in html


class TestCliIntegration:
    @pytest.mark.skipif(not FIXTURE_REPO.exists(), reason="fixture not available")
    def test_report_html_flag(self, tmp_path: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "nfr_review.cli",
                "report",
                str(FIXTURE_REPO),
                "--html",
                "--no-pdf",
                "--no-summary",
                "--output-dir",
                str(tmp_path),
                "-q",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        html_files = list(tmp_path.glob("*.html"))
        assert len(html_files) == 1
        content = html_files[0].read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "mermaid.initialize" in content
        assert '<pre class="mermaid">' in content
