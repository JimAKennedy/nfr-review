"""Integration tests for the report CLI command (M008 S04)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from nfr_review.cli import cli


class TestReportCommand:
    """Tests for `nfr-review report` command."""

    def test_target_does_not_exist(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["report", str(tmp_path / "nonexistent")])
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_target_is_file(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hello")
        runner = CliRunner()
        result = runner.invoke(cli, ["report", str(f)])
        assert result.exit_code == 2  # Click Path(file_okay=False) validation
        assert "is a file" in result.output.lower()

    def test_report_against_fixture(self, tmp_path: Path) -> None:
        fixture = Path("tests/fixtures/hygiene-clean-repo")
        output_dir = tmp_path / "reports"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["report", str(fixture), "--output-dir", str(output_dir), "--no-tests"],
        )

        assert result.exit_code == 0, f"stderr: {result.output}"
        assert output_dir.exists()

        md_files = list(output_dir.glob("nfr-review-*.md"))
        csv_files = list(output_dir.glob("nfr-review-*.csv"))
        jsonl_files = list(output_dir.glob("nfr-review-*.jsonl"))

        assert len(md_files) == 1
        assert len(csv_files) == 1
        assert len(jsonl_files) == 1

        md_content = md_files[0].read_text()
        assert "# NFR Review Report" in md_content
        assert "## Provenance" in md_content
        assert "## Source Code Findings" in md_content
        assert "## Test Code Findings" in md_content

    def test_report_filenames_share_stem(self, tmp_path: Path) -> None:
        fixture = Path("tests/fixtures/hygiene-clean-repo")
        output_dir = tmp_path / "reports"

        runner = CliRunner()
        runner.invoke(
            cli,
            ["report", str(fixture), "--output-dir", str(output_dir), "--no-tests"],
        )

        md_files = list(output_dir.glob("*.md"))
        csv_files = list(output_dir.glob("*.csv"))
        jsonl_files = list(output_dir.glob("*.jsonl"))

        assert len(md_files) == 1
        stem = md_files[0].stem
        assert csv_files[0].stem == stem
        assert jsonl_files[0].stem == stem

    def test_report_creates_output_dir(self, tmp_path: Path) -> None:
        fixture = Path("tests/fixtures/hygiene-clean-repo")
        output_dir = tmp_path / "nested" / "reports"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["report", str(fixture), "--output-dir", str(output_dir), "--no-tests"],
        )

        assert result.exit_code == 0
        assert output_dir.exists()

    def test_report_with_pytest(self, tmp_path: Path) -> None:
        fixture = Path("tests/fixtures/hygiene-clean-repo")
        output_dir = tmp_path / "reports"

        mock_result = type(
            "CompletedProcess",
            (),
            {
                "stdout": "5 passed in 0.10s\n",
                "stderr": "",
                "returncode": 0,
            },
        )()

        with patch(
            "nfr_review.output.pytest_runner.subprocess.run",
            return_value=mock_result,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["report", str(fixture), "--output-dir", str(output_dir)],
            )

        assert result.exit_code == 0
        md_files = list(output_dir.glob("*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text()
        assert "## Test Results" in content
        assert "| Passed | 5 |" in content

    def test_report_summary_to_stderr(self, tmp_path: Path) -> None:
        fixture = Path("tests/fixtures/hygiene-clean-repo")
        output_dir = tmp_path / "reports"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["report", str(fixture), "--output-dir", str(output_dir), "--no-tests"],
        )

        assert "nfr-review report:" in result.output
        assert "findings=" in result.output
