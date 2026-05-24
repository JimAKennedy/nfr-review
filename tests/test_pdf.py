"""Tests for PDF report generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.engine import RunResult
from nfr_review.models import Finding, RunMetadata
from nfr_review.output.pdf import (
    _category_severity_table_html,
    _exec_summary_html,
    _findings_html,
    _md_deps_to_html,
    _png_dimensions,
    _provenance_html,
    _test_results_html,
    render_pdf,
)
from nfr_review.output.summary_models import ExecSummary, RemediationItem

weasyprint = pytest.importorskip("weasyprint", reason="weasyprint not installed")


def _make_finding(
    rule_id: str = "TEST-001",
    severity: str = "medium",
    rag: str = "amber",
    locator: str = "src/foo.py:10",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rag=rag,
        severity=severity,
        summary=f"Test finding for {rule_id}",
        recommendation="Fix it",
        evidence_locator=locator,
        collector_name="test-collector",
        collector_version="1.0",
        confidence=0.8,
        pattern_tag="test",
    )


def _make_run_result(findings: list[Finding] | None = None) -> RunResult:
    return RunResult(
        findings=findings
        or [
            _make_finding("SEC-001", "critical", "red"),
            _make_finding("DEP-002", "high", "red"),
            _make_finding("DOC-003", "medium", "amber"),
            _make_finding("STYLE-004", "low", "green"),
        ],
        rule_results=[],
        run_metadata=RunMetadata(
            tool_version="0.1.0",
            target_repo="/tmp/test-repo",
            timestamp="2026-05-20T10:00:00Z",
            git_sha="abc1234",
            git_branch="main",
            rules_run=["SEC-001", "DEP-002", "DOC-003", "STYLE-004"],
        ),
    )


def _make_exec_summary() -> ExecSummary:
    return ExecSummary(
        verdict="conditional",
        verdict_explanation="The project has moderate issues requiring attention.",
        risk_highlights=["Outdated deps with CVEs", "Missing license headers"],
        remediation_priorities=[
            RemediationItem(
                title="Update vulnerable deps",
                urgency="immediate",
                description="Critical CVEs in 3 dependencies.",
            ),
            RemediationItem(
                title="Add license headers",
                urgency="short-term",
                description="12 files missing headers.",
            ),
        ],
        production_risks="Main risk is outdated dependencies.",
        open_source_readiness="Close to ready, needs license work.",
        overall_score=62,
    )


class TestRenderPdf:
    def test_minimal_pdf(self, tmp_path: Path) -> None:
        """Minimal report with just findings produces valid PDF."""
        out = tmp_path / "report.pdf"
        result = render_pdf(nfr_result=_make_run_result(), output_path=out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 1000
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_full_pdf_with_summary(self, tmp_path: Path) -> None:
        """Report with exec summary, test results, and findings."""
        from nfr_review.output.pytest_runner import PytestResult

        out = tmp_path / "full-report.pdf"
        result = render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            exec_summary=_make_exec_summary(),
            pytest_result=PytestResult(
                passed=45, failed=2, skipped=3, errors=0, duration_seconds=12.5
            ),
        )
        assert result == out
        assert out.read_bytes()[:5] == b"%PDF-"
        assert out.stat().st_size > 2000

    def test_pdf_with_diagram_images(self, tmp_path: Path) -> None:
        """Diagram PNG images are embedded in the PDF."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        png_path = img_dir / "chart.png"
        png_path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        out = tmp_path / "report-with-diagrams.pdf"
        result = render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            diagram_paths={"Severity Distribution": png_path},
        )
        assert result == out
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_empty_findings(self, tmp_path: Path) -> None:
        """Report with zero findings still produces valid PDF."""
        out = tmp_path / "empty.pdf"
        result = render_pdf(
            nfr_result=RunResult(findings=[], rule_results=[]),
            output_path=out,
        )
        assert result == out
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Output directory is created automatically."""
        out = tmp_path / "nested" / "deep" / "report.pdf"
        render_pdf(nfr_result=_make_run_result(), output_path=out)
        assert out.exists()

    def test_png_dimensions_reads_ihdr(self, tmp_path: Path) -> None:
        """_png_dimensions reads width/height from PNG IHDR chunk."""
        import struct

        w, h = 800, 2400
        ihdr_data = struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00"
        ihdr_crc = b"\x00\x00\x00\x00"
        raw = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc
        dims = _png_dimensions(raw)
        assert dims == (800, 2400)

    def test_png_dimensions_returns_none_for_non_png(self) -> None:
        assert _png_dimensions(b"not a png at all") is None
        assert _png_dimensions(b"") is None

    def test_tall_diagram_gets_explicit_dimensions(self, tmp_path: Path) -> None:
        """Tall PNG diagram gets inline style constraining it to page."""
        import struct

        w, h = 1489, 4669
        ihdr_data = struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00"
        ihdr_crc = b"\x00\x00\x00\x00"
        png = (
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + b"IHDR"
            + ihdr_data
            + ihdr_crc
            + b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        img_path = tmp_path / "tall.png"
        img_path.write_bytes(png)

        out = tmp_path / "tall-diagram.pdf"
        result = render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            diagram_paths={"Tall Graph": img_path},
        )
        assert result == out
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_hygiene_findings_included(self, tmp_path: Path) -> None:
        """Hygiene findings are merged into the report."""
        nfr = _make_run_result([_make_finding("NFR-001", "high", "red")])
        hygiene = RunResult(
            findings=[_make_finding("HYG-001", "medium", "amber")],
            rule_results=[],
        )
        out = tmp_path / "merged.pdf"
        result = render_pdf(
            nfr_result=nfr,
            output_path=out,
            hygiene_result=hygiene,
        )
        assert result == out
        assert out.stat().st_size > 1000

    def test_grouped_findings_in_pdf(self, tmp_path: Path) -> None:
        """Duplicate findings are grouped by rule_id+summary with locations listed."""
        findings = [
            _make_finding("CPP-001", "high", "red", locator="src/a.cpp:10"),
            _make_finding("CPP-001", "high", "red", locator="src/b.cpp:20"),
            _make_finding("CPP-001", "high", "red", locator="src/c.cpp:30"),
        ]
        out = tmp_path / "grouped.pdf"
        result = render_pdf(nfr_result=_make_run_result(findings), output_path=out)
        assert result == out
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_deps_section_renders_html_tables(self, tmp_path: Path) -> None:
        """Markdown deps section is converted to proper HTML tables in PDF."""
        deps_md = (
            "## Dependency Analysis\n\n"
            "### PYPI Dependencies\n\n"
            "#### Upgrade Summary\n\n"
            "| # | Package | Current | Latest |\n"
            "|---|---------|---------|--------|\n"
            "| 1 | click | 8.1.0 | 8.3.0 |\n"
            "| 2 | pydantic | 2.0.0 | 2.5.0 |\n"
        )
        out = tmp_path / "deps.pdf"
        result = render_pdf(
            nfr_result=_make_run_result(),
            output_path=out,
            deps_section_md=deps_md,
        )
        assert result == out
        assert out.read_bytes()[:5] == b"%PDF-"


class TestMdDepsToHtml:
    def test_headings_converted(self) -> None:
        result = _md_deps_to_html("## Main Heading\n### Sub Heading\n#### Detail")
        assert "<h2>Main Heading</h2>" in result
        assert "<h3>Sub Heading</h3>" in result
        assert "<h4>Detail</h4>" in result

    def test_table_converted(self) -> None:
        md = "| Name | Version |\n|------|---------|\n| click | 8.3 |\n| ruff | 0.5 |\n"
        result = _md_deps_to_html(md)
        assert "<table>" in result
        assert "<th>Name</th>" in result
        assert "<td>click</td>" in result
        assert "<td>ruff</td>" in result

    def test_code_block_converted(self) -> None:
        md = "```\nclick  8.1 → 8.3\npydantic  2.0\n```\n"
        result = _md_deps_to_html(md)
        assert "<pre" in result
        assert "<code>" in result

    def test_empty_input(self) -> None:
        assert _md_deps_to_html("") == ""

    def test_blockquote_converted(self) -> None:
        result = _md_deps_to_html("> Resolution failed")
        assert "<blockquote" in result
        assert "Resolution failed" in result


class TestExecSummaryHtml:
    """Verify exec summary HTML contains all required sections."""

    def test_verdict_rendered(self) -> None:
        summary = _make_exec_summary()
        html = _exec_summary_html(summary)
        assert "Conditional" in html
        assert "verdict-box" in html

    def test_overall_score_rendered(self) -> None:
        summary = _make_exec_summary()
        html = _exec_summary_html(summary)
        assert "62/100" in html
        assert "verdict-score" in html

    def test_verdict_explanation_rendered(self) -> None:
        summary = _make_exec_summary()
        html = _exec_summary_html(summary)
        assert "moderate issues requiring attention" in html

    def test_risk_highlights_rendered(self) -> None:
        summary = _make_exec_summary()
        html = _exec_summary_html(summary)
        assert "Key Risks" in html
        assert "Outdated deps with CVEs" in html
        assert "Missing license headers" in html
        assert "risk-item" in html

    def test_remediation_priorities_rendered(self) -> None:
        summary = _make_exec_summary()
        html = _exec_summary_html(summary)
        assert "Remediation Priorities" in html
        assert "Update vulnerable deps" in html
        assert "immediate" in html
        assert "Add license headers" in html
        assert "short-term" in html
        assert "Critical CVEs in 3 dependencies" in html

    def test_production_risks_rendered(self) -> None:
        summary = _make_exec_summary()
        html = _exec_summary_html(summary)
        assert "Production Risks" in html
        assert "outdated dependencies" in html

    def test_open_source_readiness_rendered(self) -> None:
        summary = _make_exec_summary()
        html = _exec_summary_html(summary)
        assert "Open-Source Readiness" in html
        assert "needs license work" in html

    def test_fit_verdict_uses_green(self) -> None:
        summary = ExecSummary(
            verdict="fit",
            verdict_explanation="All clear.",
            risk_highlights=[],
            remediation_priorities=[],
            production_risks="None.",
            open_source_readiness="Ready.",
            overall_score=95,
        )
        html = _exec_summary_html(summary)
        assert "Fit for Purpose" in html
        assert "#28a745" in html
        assert "95/100" in html

    def test_unfit_verdict_uses_red(self) -> None:
        summary = ExecSummary(
            verdict="unfit",
            verdict_explanation="Critical issues.",
            risk_highlights=["Fatal flaw"],
            remediation_priorities=[],
            production_risks="Major.",
            open_source_readiness="Not ready.",
            overall_score=15,
        )
        html = _exec_summary_html(summary)
        assert "Not Fit for Purpose" in html
        assert "#dc3545" in html
        assert "15/100" in html


class TestCategorySeverityTableHtml:
    """Verify the category x severity summary table is rendered correctly."""

    def test_table_has_all_severity_columns(self) -> None:
        findings = [_make_finding("SEC-001", "critical", "red")]
        html = _category_severity_table_html(findings, "Test Summary")
        assert "<h3>Test Summary</h3>" in html
        for col in ("Category", "Critical", "High", "Medium", "Low", "Info", "Total"):
            assert f"<th>{col}</th>" in html

    def test_table_has_category_rows(self) -> None:
        findings = [
            _make_finding("SEC-001", "critical", "red"),
            _make_finding("OBS-001", "medium", "amber"),
            _make_finding("HYG-BLD-001", "low", "green"),
        ]
        html = _category_severity_table_html(findings, "By Category")
        assert "HYG-BLD" in html
        assert "OBS" in html
        assert "SEC" in html

    def test_table_counts_correct(self) -> None:
        findings = [
            _make_finding("SEC-001", "critical", "red"),
            _make_finding("SEC-002", "critical", "red"),
            _make_finding("OBS-001", "medium", "amber"),
        ]
        html = _category_severity_table_html(findings, "Counts")
        assert "<strong>3</strong>" in html


class TestFindingsHtml:
    """Verify findings HTML grouping and content."""

    def test_findings_grouped_by_rule_and_summary(self) -> None:
        findings = [
            _make_finding("CPP-001", "high", "red", "src/a.cpp:10"),
            _make_finding("CPP-001", "high", "red", "src/b.cpp:20"),
            _make_finding("CPP-001", "high", "red", "src/c.cpp:30"),
        ]
        html = _findings_html(findings, "Source Code Findings")
        assert html.count("[CPP-001]") == 1
        assert "src/a.cpp:10" in html
        assert "src/b.cpp:20" in html
        assert "src/c.cpp:30" in html
        assert "location-table" in html

    def test_findings_preserves_severity_and_confidence(self) -> None:
        findings = [_make_finding("SEC-001", "critical", "red", "src/app.py:5")]
        html = _findings_html(findings, "Findings")
        assert "<th>Severity</th>" in html
        assert "<th>Confidence</th>" in html
        assert "<td>critical</td>" in html
        assert "<td>80%</td>" in html

    def test_findings_preserves_recommendation(self) -> None:
        findings = [_make_finding("DOC-001", "medium", "amber")]
        html = _findings_html(findings, "Findings")
        assert "Recommendation: Fix it" in html

    def test_findings_empty(self) -> None:
        html = _findings_html([], "Empty Findings")
        assert "No findings." in html

    def test_findings_rag_sections(self) -> None:
        findings = [
            _make_finding("A", "critical", "red"),
            _make_finding("B", "medium", "amber"),
            _make_finding("C", "low", "green"),
        ]
        html = _findings_html(findings, "All")
        assert "RED (1)" in html
        assert "AMBER (1)" in html
        assert "GREEN (1)" in html

    def test_grouped_findings_show_per_location_severity(self) -> None:
        """Each occurrence row shows its own severity and confidence."""
        f1 = Finding(
            rule_id="CPP-001",
            rag="red",
            severity="high",
            summary="Test finding for CPP-001",
            recommendation="Fix it",
            evidence_locator="src/a.cpp:10",
            collector_name="test-collector",
            collector_version="1.0",
            confidence=0.9,
            pattern_tag="test",
        )
        f2 = Finding(
            rule_id="CPP-001",
            rag="red",
            severity="medium",
            summary="Test finding for CPP-001",
            recommendation="Fix it",
            evidence_locator="src/b.cpp:20",
            collector_name="test-collector",
            collector_version="1.0",
            confidence=0.7,
            pattern_tag="test",
        )
        html = _findings_html([f1, f2], "Findings")
        assert html.count("[CPP-001]") == 1
        assert "<td>high</td>" in html
        assert "<td>90%</td>" in html
        assert "<td>medium</td>" in html
        assert "<td>70%</td>" in html

    def test_location_table_has_three_columns(self) -> None:
        """Location table includes Location, Severity, and Confidence headers."""
        findings = [_make_finding("SEC-001", "critical", "red", "src/app.py:5")]
        html = _findings_html(findings, "Findings")
        assert "<th>Location</th>" in html
        assert "<th>Severity</th>" in html
        assert "<th>Confidence</th>" in html

    def test_distinct_rules_get_separate_blocks(self) -> None:
        findings = [
            _make_finding("SEC-001", "critical", "red", "src/a.py:1"),
            _make_finding("SEC-002", "high", "red", "src/b.py:2"),
        ]
        html = _findings_html(findings, "Findings")
        assert "[SEC-001]" in html
        assert "[SEC-002]" in html


class TestProvenanceHtml:
    """Verify provenance metadata section."""

    def test_provenance_includes_repo_and_sha(self) -> None:
        result = _make_run_result()
        html = _provenance_html(result)
        assert "test-repo" in html
        assert "abc1234" in html
        assert "main" in html
        assert "0.1.0" in html

    def test_provenance_empty_without_metadata(self) -> None:
        result = RunResult(findings=[], rule_results=[])
        html = _provenance_html(result)
        assert html == ""


class TestTestResultsHtml:
    """Verify test results section rendering."""

    def test_passing_results(self) -> None:
        from nfr_review.output.pytest_runner import PytestResult

        pr = PytestResult(passed=10, failed=0, skipped=1, errors=0, duration_seconds=3.5)
        html = _test_results_html(pr)
        assert "PASSED" in html
        assert "#28a745" in html
        assert "<td>10</td>" in html

    def test_failing_results(self) -> None:
        from nfr_review.output.pytest_runner import PytestResult

        pr = PytestResult(passed=8, failed=2, skipped=0, errors=1, duration_seconds=5.0)
        html = _test_results_html(pr)
        assert "FAILED" in html
        assert "#dc3545" in html
        assert "<td>2</td>" in html

    def test_no_test_results(self) -> None:
        html = _test_results_html(None)
        assert "not performed" in html


def _capture_pdf_html(tmp_path: Path, **kwargs: object) -> str:
    """Render PDF with a mock weasyprint and return the HTML string."""
    import sys
    from types import ModuleType

    captured: dict[str, str] = {}
    fake_wp = ModuleType("weasyprint")

    class FakeHTML:
        def __init__(self, string: str = "", **kw: object) -> None:
            captured["html"] = string

        def write_pdf(self, path: str) -> None:
            Path(path).write_bytes(b"%PDF-fake")

    fake_wp.HTML = FakeHTML  # type: ignore[attr-defined]
    original = sys.modules.get("weasyprint")
    sys.modules["weasyprint"] = fake_wp
    try:
        out = tmp_path / "verify.pdf"
        render_pdf(
            nfr_result=kwargs.pop("nfr_result", _make_run_result()), output_path=out, **kwargs
        )  # type: ignore[arg-type]
    finally:
        if original is not None:
            sys.modules["weasyprint"] = original
        else:
            sys.modules.pop("weasyprint", None)
    return captured["html"]


class TestRenderPdfContentIntegration:
    """Integration tests verifying the full HTML passed to weasyprint."""

    def test_exec_summary_present_in_full_pdf(self, tmp_path: Path) -> None:
        """When exec_summary is provided, the PDF HTML includes it."""
        html = _capture_pdf_html(tmp_path, exec_summary=_make_exec_summary())
        assert "Executive Summary" in html
        assert "62/100" in html
        assert "Conditional" in html
        assert "Key Risks" in html
        assert "Remediation Priorities" in html
        assert "Findings Summary" in html
        assert "Source Code Findings" in html

    def test_no_exec_summary_omits_section(self, tmp_path: Path) -> None:
        """When exec_summary is None, the exec summary section is absent."""
        html = _capture_pdf_html(tmp_path, exec_summary=None)
        assert "Executive Summary" not in html
        assert "Findings Summary" in html
        assert "Source Code Findings" in html

    def test_jdepend_section_rendered(self, tmp_path: Path) -> None:
        """JDepend markdown section is converted to HTML in the PDF."""
        jdepend_md = (
            "## JDepend Structural Analysis\n\n"
            "| Package | Ca | Ce | A | I | D | Classes |\n"
            "|---------|----|----|---|---|---|---------|\n"
            "| com.example | 3 | 5 | 0.2 | 0.63 | 0.17 | 10 |\n"
        )
        html = _capture_pdf_html(tmp_path, jdepend_section_md=jdepend_md)
        assert "JDepend Structural Analysis" in html
        assert "com.example" in html

    def test_adr_section_rendered(self, tmp_path: Path) -> None:
        """ADR markdown section is converted to HTML in the PDF."""
        adr_md = (
            "## Architecture Decision Records\n\n"
            "**2 ADRs** found in repository.\n\n"
            "| # | Title | Status | Superseded By |\n"
            "|---|-------|--------|---------------|\n"
            "| 1 | Use Spring Boot | accepted | — |\n"
        )
        html = _capture_pdf_html(tmp_path, adr_section_md=adr_md)
        assert "Architecture Decision Records" in html
        assert "Use Spring Boot" in html

    def test_derived_adrs_section_rendered(self, tmp_path: Path) -> None:
        """Derived ADRs markdown section is converted to HTML in the PDF."""
        derived_md = (
            "## Derived Architecture Decision Records\n\n"
            "| # | Decision | Category | Confidence |\n"
            "|---|----------|----------|------------|\n"
            "| 1 | Use Redis | infrastructure | 85% |\n"
        )
        html = _capture_pdf_html(tmp_path, derived_adrs_section_md=derived_md)
        assert "Derived Architecture Decision Records" in html
        assert "Use Redis" in html

    def test_all_new_sections_rendered_in_order(self, tmp_path: Path) -> None:
        """ADR, JDepend, Derived ADR, and Deps sections appear in correct order."""
        html = _capture_pdf_html(
            tmp_path,
            adr_section_md="## Architecture Decision Records\n\nADR content\n",
            jdepend_section_md="## JDepend Structural Analysis\n\nJDepend content\n",
            derived_adrs_section_md=(
                "## Derived Architecture Decision Records\n\nDerived content\n"
            ),
            deps_section_md="## Dependency Analysis\n\nDeps content\n",
        )
        adr_pos = html.index("Architecture Decision Records")
        jdepend_pos = html.index("JDepend Structural Analysis")
        derived_pos = html.index("Derived Architecture Decision Records")
        deps_pos = html.index("Appendix A")
        assert adr_pos < jdepend_pos < derived_pos < deps_pos
