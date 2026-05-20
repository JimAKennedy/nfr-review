"""E2E tests for the --pdf flag on the report command."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

weasyprint = pytest.importorskip("weasyprint", reason="weasyprint not installed")

from nfr_review.cli import cli  # noqa: E402


@pytest.fixture()
def fixture_repo() -> Path:
    return Path(__file__).parent / "fixtures" / "cmake-sample-repo"


class TestReportPdfFlag:
    def test_pdf_produced_alongside_md(self, tmp_path: Path, fixture_repo: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "report",
                str(fixture_repo),
                "--output-dir",
                str(tmp_path),
                "--no-tests",
                "--no-deps",
                "--pdf",
                "--no-summary",
            ],
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"

        md_files = list(tmp_path.glob("*-nfr-review-*.md"))
        pdf_files = list(tmp_path.glob("*-nfr-review-*.pdf"))

        assert len(md_files) == 1, f"Expected 1 MD file, got {md_files}"
        assert len(pdf_files) == 1, f"Expected 1 PDF file, got {pdf_files}"

        pdf_content = pdf_files[0].read_bytes()
        assert pdf_content[:5] == b"%PDF-"
        assert pdf_files[0].stat().st_size > 1000

    def test_pdf_flag_mentioned_in_summary(self, tmp_path: Path, fixture_repo: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "report",
                str(fixture_repo),
                "--output-dir",
                str(tmp_path),
                "--no-tests",
                "--no-deps",
                "--no-diagrams",
                "--pdf",
                "--no-summary",
            ],
        )
        assert result.exit_code == 0
        assert "pdf=" in result.output

    def test_report_without_pdf_flag(self, tmp_path: Path, fixture_repo: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "report",
                str(fixture_repo),
                "--output-dir",
                str(tmp_path),
                "--no-tests",
                "--no-deps",
                "--no-diagrams",
            ],
        )
        assert result.exit_code == 0
        assert "pdf=" not in result.output
        assert len(list(tmp_path.glob("*.pdf"))) == 0
