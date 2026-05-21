"""Tests for PDF report generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.engine import RunResult
from nfr_review.models import Finding, RunMetadata
from nfr_review.output.pdf import _png_dimensions, render_pdf
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
