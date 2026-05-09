"""Tests for pytest subprocess runner (M008 S03)."""

from __future__ import annotations

import subprocess as sp
from pathlib import Path
from unittest.mock import patch

from nfr_review.output.pytest_runner import PytestResult, _parse_summary, run_pytest


class TestParseSummary:
    """Tests for _parse_summary against various pytest output shapes."""

    def test_all_passed(self) -> None:
        result = _parse_summary("51 passed in 0.06s\n")
        assert result.passed == 51
        assert result.failed == 0
        assert result.duration_seconds == 0.06

    def test_mixed_results(self) -> None:
        result = _parse_summary("10 passed, 2 failed, 1 skipped in 1.23s\n")
        assert result.passed == 10
        assert result.failed == 2
        assert result.skipped == 1
        assert result.duration_seconds == 1.23

    def test_with_errors(self) -> None:
        result = _parse_summary("5 passed, 3 errors in 0.50s\n")
        assert result.passed == 5
        assert result.errors == 3
        assert result.duration_seconds == 0.50

    def test_with_warnings(self) -> None:
        result = _parse_summary("20 passed, 3 warnings in 2.10s\n")
        assert result.passed == 20
        assert result.warnings == ["3 warnings emitted"]

    def test_only_failed(self) -> None:
        result = _parse_summary("4 failed in 0.80s\n")
        assert result.passed == 0
        assert result.failed == 4
        assert result.duration_seconds == 0.80

    def test_multiline_output_finds_summary(self) -> None:
        output = (
            "FAILED tests/test_foo.py::test_bar\n"
            "FAILED tests/test_foo.py::test_baz\n"
            "2 failed, 8 passed in 3.45s\n"
        )
        result = _parse_summary(output)
        assert result.failed == 2
        assert result.passed == 8
        assert result.duration_seconds == 3.45

    def test_no_summary_line(self) -> None:
        result = _parse_summary("no tests ran\n")
        assert result.passed == 0
        assert result.failed == 0
        assert result.duration_seconds == 0.0

    def test_single_error(self) -> None:
        result = _parse_summary("1 error in 0.01s\n")
        assert result.errors == 1


class TestRunPytest:
    """Tests for run_pytest with monkeypatched subprocess."""

    def _mock_proc(self, stdout: str, stderr: str = "", returncode: int = 0) -> object:
        return type(
            "CompletedProcess",
            (),
            {"stdout": stdout, "stderr": stderr, "returncode": returncode},
        )()

    def test_successful_run(self) -> None:
        with patch(
            "nfr_review.output.pytest_runner.subprocess.run",
            return_value=self._mock_proc("51 passed in 0.06s\n"),
        ):
            result = run_pytest(Path("/tmp/project"))

        assert result.passed == 51
        assert result.failed == 0
        assert result.exit_code == 0
        assert result.duration_seconds == 0.06

    def test_failed_tests(self) -> None:
        with patch(
            "nfr_review.output.pytest_runner.subprocess.run",
            return_value=self._mock_proc("3 failed, 7 passed in 1.20s\n", returncode=1),
        ):
            result = run_pytest(Path("/tmp/project"))

        assert result.passed == 7
        assert result.failed == 3
        assert result.exit_code == 1

    def test_pytest_not_found(self) -> None:
        with patch(
            "nfr_review.output.pytest_runner.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = run_pytest(Path("/tmp/project"))

        assert result.exit_code == -1
        assert "not found" in result.raw_output

    def test_timeout(self) -> None:
        with patch(
            "nfr_review.output.pytest_runner.subprocess.run",
            side_effect=sp.TimeoutExpired(cmd="pytest", timeout=300),
        ):
            result = run_pytest(Path("/tmp/project"), timeout=300)

        assert result.exit_code == -1
        assert "timed out" in result.raw_output

    def test_total_property(self) -> None:
        r = PytestResult(passed=5, failed=2, skipped=1, errors=1)
        assert r.total == 9

    def test_raw_output_captured(self) -> None:
        with patch(
            "nfr_review.output.pytest_runner.subprocess.run",
            return_value=self._mock_proc("10 passed in 0.50s\n", stderr="some warning\n"),
        ):
            result = run_pytest(Path("/tmp/project"))

        assert "10 passed" in result.raw_output
        assert "some warning" in result.raw_output
