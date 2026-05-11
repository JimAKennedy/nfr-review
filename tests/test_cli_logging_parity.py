"""Tests proving --verbose, --quiet, --log-file work on hygiene and report commands.

Mirrors the TestRunVerbosityFlags pattern from test_cli_logging.py to ensure
parity across all three user-facing commands (M009 S03).
"""

from __future__ import annotations

import logging
from pathlib import Path

from click.testing import CliRunner

from nfr_review.cli import cli

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "hygiene-clean-repo"


def _runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Hygiene command logging tests
# ---------------------------------------------------------------------------


class TestHygieneVerbosityFlags:
    def test_hygiene_accepts_verbose_flag(self, tmp_path: Path) -> None:
        result = _runner().invoke(cli, ["hygiene", str(FIXTURE_DIR), "-v"])
        assert result.exit_code == 0, result.output

    def test_hygiene_accepts_quiet_flag(self, tmp_path: Path) -> None:
        result = _runner().invoke(cli, ["hygiene", str(FIXTURE_DIR), "-q"])
        assert result.exit_code == 0, result.output

    def test_hygiene_verbose_sets_info(self, tmp_path: Path) -> None:
        _runner().invoke(cli, ["hygiene", str(FIXTURE_DIR), "-v"])
        assert logging.getLogger("nfr_review").level == logging.INFO

    def test_hygiene_double_verbose_sets_debug(self, tmp_path: Path) -> None:
        _runner().invoke(cli, ["hygiene", str(FIXTURE_DIR), "-vv"])
        assert logging.getLogger("nfr_review").level == logging.DEBUG

    def test_hygiene_quiet_sets_error(self, tmp_path: Path) -> None:
        _runner().invoke(cli, ["hygiene", str(FIXTURE_DIR), "-q"])
        assert logging.getLogger("nfr_review").level == logging.ERROR

    def test_hygiene_verbose_quiet_exclusive(self, tmp_path: Path) -> None:
        result = _runner().invoke(cli, ["hygiene", str(FIXTURE_DIR), "-v", "-q"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()

    def test_hygiene_log_file_creates_file(self, tmp_path: Path) -> None:
        log_file = tmp_path / "hygiene.log"
        result = _runner().invoke(
            cli, ["hygiene", str(FIXTURE_DIR), "--log-file", str(log_file)]
        )
        assert result.exit_code == 0, result.output
        assert log_file.exists()


# ---------------------------------------------------------------------------
# Report command logging tests
# ---------------------------------------------------------------------------


class TestReportVerbosityFlags:
    def test_report_accepts_verbose_flag(self, tmp_path: Path) -> None:
        result = _runner().invoke(
            cli,
            ["report", str(FIXTURE_DIR), "--output-dir", str(tmp_path), "--no-tests", "-v"],
        )
        assert result.exit_code == 0, result.output

    def test_report_accepts_quiet_flag(self, tmp_path: Path) -> None:
        result = _runner().invoke(
            cli,
            ["report", str(FIXTURE_DIR), "--output-dir", str(tmp_path), "--no-tests", "-q"],
        )
        assert result.exit_code == 0, result.output

    def test_report_verbose_sets_info(self, tmp_path: Path) -> None:
        _runner().invoke(
            cli,
            ["report", str(FIXTURE_DIR), "--output-dir", str(tmp_path), "--no-tests", "-v"],
        )
        assert logging.getLogger("nfr_review").level == logging.INFO

    def test_report_quiet_sets_error(self, tmp_path: Path) -> None:
        _runner().invoke(
            cli,
            ["report", str(FIXTURE_DIR), "--output-dir", str(tmp_path), "--no-tests", "-q"],
        )
        assert logging.getLogger("nfr_review").level == logging.ERROR

    def test_report_verbose_quiet_exclusive(self, tmp_path: Path) -> None:
        result = _runner().invoke(
            cli,
            [
                "report",
                str(FIXTURE_DIR),
                "--output-dir",
                str(tmp_path),
                "--no-tests",
                "-v",
                "-q",
            ],
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()

    def test_report_log_file_creates_file(self, tmp_path: Path) -> None:
        log_file = tmp_path / "report.log"
        result = _runner().invoke(
            cli,
            [
                "report",
                str(FIXTURE_DIR),
                "--output-dir",
                str(tmp_path),
                "--no-tests",
                "--log-file",
                str(log_file),
            ],
        )
        assert result.exit_code == 0, result.output
        assert log_file.exists()
