"""Tests for _configure_logging() and CLI verbosity flags.

Covers the logging subsystem added in M009 S01: level configuration,
handler selection, root logger isolation, and CLI flag wiring.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.cli import _configure_logging, _DedupFilter, cli


@pytest.fixture(autouse=True)
def _reset_nfr_logger():
    """Save and restore the nfr_review logger state between tests."""
    logger = logging.getLogger("nfr_review")
    orig_level = logger.level
    orig_handlers = list(logger.handlers)
    orig_propagate = logger.propagate
    yield
    logger.handlers[:] = orig_handlers
    logger.setLevel(orig_level)
    logger.propagate = orig_propagate


def _runner() -> CliRunner:
    return CliRunner()


def _run_args(tmp_path: Path) -> list[str]:
    """Build minimal run args that won't collide across tests."""
    target = tmp_path / "repo"
    target.mkdir(exist_ok=True)
    return [
        "run",
        str(target),
        "--csv",
        str(tmp_path / "out.csv"),
        "--jsonl",
        str(tmp_path / "out.jsonl"),
    ]


# ---------------------------------------------------------------------------
# Unit tests: _configure_logging()
# ---------------------------------------------------------------------------


class TestConfigureLoggingLevel:
    def test_default_is_warning(self) -> None:
        _configure_logging(verbose=0, quiet=False, log_file=None)
        assert logging.getLogger("nfr_review").level == logging.WARNING

    def test_verbose_sets_info(self) -> None:
        _configure_logging(verbose=1, quiet=False, log_file=None)
        assert logging.getLogger("nfr_review").level == logging.INFO

    def test_double_verbose_sets_debug(self) -> None:
        _configure_logging(verbose=2, quiet=False, log_file=None)
        assert logging.getLogger("nfr_review").level == logging.DEBUG

    def test_quiet_sets_error(self) -> None:
        _configure_logging(verbose=0, quiet=True, log_file=None)
        assert logging.getLogger("nfr_review").level == logging.ERROR


class TestConfigureLoggingHandlers:
    def test_stream_handler_when_no_log_file(self) -> None:
        _configure_logging(verbose=0, quiet=False, log_file=None)
        logger = logging.getLogger("nfr_review")
        assert len(logger.handlers) == 1
        handler = logger.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert not isinstance(handler, logging.FileHandler)

    def test_file_handler_when_log_file_set(self, tmp_path: Path) -> None:
        log_file = tmp_path / "test.log"
        _configure_logging(verbose=1, quiet=False, log_file=log_file)
        logger = logging.getLogger("nfr_review")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.FileHandler)
        logger.info("hello from test")
        logger.handlers[0].flush()
        assert "hello from test" in log_file.read_text()

    def test_bad_path_falls_back_to_stream(self) -> None:
        _configure_logging(verbose=1, quiet=False, log_file=Path("/nonexistent/dir/file.log"))
        logger = logging.getLogger("nfr_review")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)
        assert not isinstance(logger.handlers[0], logging.FileHandler)

    def test_handlers_cleared_on_reconfig(self) -> None:
        _configure_logging(verbose=0, quiet=False, log_file=None)
        _configure_logging(verbose=1, quiet=False, log_file=None)
        assert len(logging.getLogger("nfr_review").handlers) == 1


class TestConfigureLoggingIsolation:
    def test_does_not_affect_root_logger(self) -> None:
        root = logging.getLogger()
        orig_level = root.level
        orig_handler_count = len(root.handlers)
        _configure_logging(verbose=2, quiet=False, log_file=None)
        assert root.level == orig_level
        assert len(root.handlers) == orig_handler_count

    def test_propagate_is_false(self) -> None:
        _configure_logging(verbose=0, quiet=False, log_file=None)
        assert logging.getLogger("nfr_review").propagate is False


# ---------------------------------------------------------------------------
# CLI integration tests: run command verbosity flags
# ---------------------------------------------------------------------------


class TestRunVerbosityFlags:
    def test_verbose_flag_accepted(self, tmp_path: Path) -> None:
        result = _runner().invoke(cli, [*_run_args(tmp_path), "-v"])
        assert result.exit_code == 0, result.stderr

    def test_double_verbose_accepted(self, tmp_path: Path) -> None:
        result = _runner().invoke(cli, [*_run_args(tmp_path), "-vv"])
        assert result.exit_code == 0, result.stderr

    def test_quiet_flag_accepted(self, tmp_path: Path) -> None:
        result = _runner().invoke(cli, [*_run_args(tmp_path), "-q"])
        assert result.exit_code == 0, result.stderr

    def test_verbose_and_quiet_mutually_exclusive(self, tmp_path: Path) -> None:
        result = _runner().invoke(cli, [*_run_args(tmp_path), "-v", "-q"])
        assert result.exit_code != 0
        combined = (result.output or "") + (result.stderr or "")
        assert "mutually exclusive" in combined.lower()

    def test_log_file_creates_file(self, tmp_path: Path) -> None:
        log_file = tmp_path / "diag.log"
        result = _runner().invoke(cli, [*_run_args(tmp_path), "--log-file", str(log_file)])
        assert result.exit_code == 0, result.stderr
        assert log_file.exists()

    def test_log_file_bad_path_still_runs(self, tmp_path: Path) -> None:
        result = _runner().invoke(
            cli,
            [*_run_args(tmp_path), "--log-file", "/nonexistent/dir/nfr.log"],
        )
        assert result.exit_code == 0, result.stderr
        assert "cannot open log file" in result.stderr


# ---------------------------------------------------------------------------
# Unit tests: _DedupFilter
# ---------------------------------------------------------------------------


class TestDedupFilter:
    def test_dedup_filter_suppresses_repeated_messages(self) -> None:
        _configure_logging(verbose=0, quiet=False, log_file=None)
        logger = logging.getLogger("nfr_review.test_dedup")
        logger.setLevel(logging.WARNING)
        handler = logging.getLogger("nfr_review").handlers[0]
        records: list[logging.LogRecord] = []
        orig_emit = handler.emit
        handler.emit = lambda r: records.append(r)  # type: ignore[assignment]
        try:
            logger.warning("duplicate msg")
            logger.warning("duplicate msg")
            logger.warning("duplicate msg")
        finally:
            handler.emit = orig_emit  # type: ignore[assignment]
        assert len(records) == 1

    def test_dedup_filter_allows_distinct_messages(self) -> None:
        _configure_logging(verbose=0, quiet=False, log_file=None)
        logger = logging.getLogger("nfr_review.test_dedup2")
        logger.setLevel(logging.WARNING)
        handler = logging.getLogger("nfr_review").handlers[0]
        records: list[logging.LogRecord] = []
        orig_emit = handler.emit
        handler.emit = lambda r: records.append(r)  # type: ignore[assignment]
        try:
            logger.warning("message A")
            logger.warning("message B")
        finally:
            handler.emit = orig_emit  # type: ignore[assignment]
        assert len(records) == 2

    def test_reset_clears_seen_set(self) -> None:
        f = _DedupFilter()
        record = logging.LogRecord("test", logging.WARNING, "", 0, "hello", (), None)
        assert f.filter(record) is True
        assert f.filter(record) is False
        f.reset()
        assert f.filter(record) is True
