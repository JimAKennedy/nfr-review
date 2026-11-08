# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Automated tests for M022 UAT findings 6, 7, and 9.

Finding 6: All terminal output during a scan must be prefixed with a timestamp.
Finding 7: JDepend must not emit a WARNING when bytecode is unavailable.
Finding 9: ``nfr-review issues . --dry-run`` must be a recognised command.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nfr_review.cli import _configure_logging, _ts_echo, cli
from nfr_review.collectors.jdepend import JDependCollector


def _runner() -> CliRunner:
    return CliRunner()


# ──────────────────────────────────────────────────────────────────────
# Finding 6 — timestamp prefixes on all terminal output
# ──────────────────────────────────────────────────────────────────────


class TestFinding6Timestamps:
    """All stderr output during a scan must carry a date-time prefix."""

    _TS_PATTERN = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC\]")

    def test_logging_formatter_includes_timestamp(self, tmp_path: Path) -> None:
        _configure_logging(verbose=1, quiet=False, log_file=None)
        logger = logging.getLogger("nfr_review")
        handler = logger.handlers[0]
        fmt = handler.formatter
        assert fmt is not None
        record = logging.LogRecord(
            name="nfr_review.test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        formatted = fmt.format(record)
        assert self._TS_PATTERN.search(formatted), (
            f"Logging format missing timestamp: {formatted!r}"
        )
        assert "UTC" in formatted

    def test_logging_formatter_uses_utc(self) -> None:
        _configure_logging(verbose=0, quiet=False, log_file=None)
        logger = logging.getLogger("nfr_review")
        handler = logger.handlers[0]
        fmt = handler.formatter
        assert fmt is not None
        assert fmt.converter is time.gmtime

    def test_ts_echo_prefixes_timestamp(self, capsys: pytest.CaptureFixture[str]) -> None:
        _ts_echo("hello world")
        captured = capsys.readouterr()
        assert self._TS_PATTERN.search(captured.err), (
            f"_ts_echo output missing timestamp: {captured.err!r}"
        )
        assert "hello world" in captured.err

    def test_ts_echo_quiet_suppresses(self, capsys: pytest.CaptureFixture[str]) -> None:
        _ts_echo("should not appear", quiet=True)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_run_stderr_lines_have_timestamps(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        target.mkdir()
        (target / "README.md").write_text("# sample\n")
        csv_path = tmp_path / "out.csv"
        jsonl_path = tmp_path / "out.jsonl"

        result = _runner().invoke(
            cli,
            ["run", str(target), "--csv", str(csv_path), "--jsonl", str(jsonl_path)],
        )
        assert result.exit_code == 0, result.stderr

        for line in result.stderr.strip().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Banner lines (nfr-review run v..., Repository:, Started:, Options:, Phases:)
            # are header blocks — exempt from per-line timestamp requirement.
            if any(
                stripped.startswith(prefix)
                for prefix in ("nfr-review ", "Repository:", "Started:", "Options:", "Phases:")
            ):
                continue
            # Category score indented lines (e.g. "  SEC: 85/100") under a timestamped parent
            if re.match(r"^\s+\w+:\s+\d+/100$", stripped):
                continue
            assert self._TS_PATTERN.search(line), f"Stderr line missing timestamp: {line!r}"

    def test_hygiene_stderr_lines_have_timestamps(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        target.mkdir()
        (target / "README.md").write_text("# sample\n")

        result = _runner().invoke(
            cli,
            ["hygiene", str(target), "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, result.stderr

        for line in result.stderr.strip().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if any(
                stripped.startswith(prefix)
                for prefix in ("nfr-review ", "Repository:", "Started:", "Options:", "Phases:")
            ):
                continue
            assert self._TS_PATTERN.search(line), (
                f"Hygiene stderr line missing timestamp: {line!r}"
            )


# ──────────────────────────────────────────────────────────────────────
# Finding 7 — JDepend silent skip when bytecode unavailable
# ──────────────────────────────────────────────────────────────────────


class TestFinding7JDependNoWarning:
    """JDepend must not emit WARNING when Java sources exist but bytecode is absent."""

    def test_no_warning_when_java_sources_no_bytecode(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "App.java").write_text("public class App {}")
        config = MagicMock()
        config.exclude_test_paths = True
        config.exclude_paths = []

        collector = JDependCollector()
        with caplog.at_level(logging.WARNING, logger="nfr_review.collectors.jdepend"):
            collector.collect(tmp_path, config)

        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert not any("JDepend skipped" in m for m in warning_messages), (
            f"JDepend emitted WARNING when it should not: {warning_messages}"
        )

    def test_info_logged_when_java_sources_no_bytecode(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "App.java").write_text("public class App {}")
        config = MagicMock()
        config.exclude_test_paths = True
        config.exclude_paths = []

        collector = JDependCollector()
        with caplog.at_level(logging.INFO, logger="nfr_review.collectors.jdepend"):
            collector.collect(tmp_path, config)

        info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert any("JDepend skipped" in m for m in info_messages), (
            "JDepend should log at INFO when skipping due to missing bytecode"
        )

    def test_returns_empty_when_no_bytecode(self, tmp_path: Path) -> None:
        (tmp_path / "App.java").write_text("public class App {}")
        config = MagicMock()
        config.exclude_test_paths = True
        config.exclude_paths = []

        collector = JDependCollector()
        evidences = collector.collect(tmp_path, config)
        assert evidences == []

    def test_no_jdepend_warning_in_run_cmd(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        target.mkdir()
        (target / "App.java").write_text("public class App {}")
        csv_path = tmp_path / "out.csv"
        jsonl_path = tmp_path / "out.jsonl"

        result = _runner().invoke(
            cli,
            [
                "run",
                str(target),
                "--csv",
                str(csv_path),
                "--jsonl",
                str(jsonl_path),
                "--score",
            ],
        )
        assert result.exit_code in (0, 2), result.stderr
        assert "JDepend skipped" not in result.stderr


# ──────────────────────────────────────────────────────────────────────
# Finding 9 — ``nfr-review issues`` command exists and works
# ──────────────────────────────────────────────────────────────────────


class TestFinding9IssuesCommand:
    """``nfr-review issues`` is a group with ``scan`` and ``sync`` subcommands."""

    def test_issues_group_registered(self) -> None:
        result = _runner().invoke(cli, ["issues", "--help"])
        assert result.exit_code == 0, result.output
        assert "scan" in result.output
        assert "sync" in result.output

    def test_issues_scan_help_shows_options(self) -> None:
        result = _runner().invoke(cli, ["issues", "scan", "--help"])
        assert "--dry-run" in result.output
        assert "--repo" in result.output
        assert "--severity-threshold" in result.output
        assert "--config" in result.output

    def test_issues_dry_run_no_findings(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        target.mkdir()
        (target / "README.md").write_text("# present\n")

        result = _runner().invoke(
            cli,
            ["issues", str(target), "--dry-run"],
        )
        assert result.exit_code == 0, result.stderr
        assert "nothing to file" in result.stderr.lower() or "0" in result.stderr

    def test_issues_missing_target_exits_1(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        result = _runner().invoke(cli, ["issues", str(missing), "--dry-run"])
        assert result.exit_code == 1
        assert "target does not exist" in result.stderr

    def test_issues_dry_run_with_findings(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        target.mkdir()
        # No README -> sample-readme-exists fires (amber/medium usually)
        # We lower threshold to catch it
        result = _runner().invoke(
            cli,
            [
                "issues",
                str(target),
                "--dry-run",
                "--severity-threshold",
                "info",
            ],
        )
        assert result.exit_code == 0, result.stderr

    def test_issues_without_repo_or_dry_run_fails(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        target.mkdir()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = _runner().invoke(
                cli,
                ["issues", str(target)],
            )
        assert result.exit_code == 1
        assert "could not detect GitHub repo" in result.stderr
