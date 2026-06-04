"""Tests for pytest subprocess runner (M008 S03)."""

from __future__ import annotations

import subprocess as sp
from pathlib import Path
from unittest.mock import patch

from nfr_review.output.pytest_runner import (
    PytestResult,
    _detect_expensive_markers,
    _parse_summary,
    run_pytest,
)


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

    def _pytest_args(self, mock_run: object) -> list[str]:
        """Extract pytest args after 'python -m pytest' from the captured command."""
        cmd = mock_run.call_args[0][0]  # type: ignore[union-attr]
        pytest_idx = cmd.index("pytest")
        return cmd[pytest_idx + 1 :]

    def test_excludes_expensive_markers(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.pytest.ini_options]\n"
            "markers = [\n"
            '    "regression: clones repos",\n'
            '    "slow: full pass",\n'
            "]\n"
        )
        with patch(
            "nfr_review.output.pytest_runner.subprocess.run",
            return_value=self._mock_proc("40 passed, 5 deselected in 1.00s\n"),
        ) as mock_run:
            run_pytest(tmp_path)

        args = self._pytest_args(mock_run)
        assert "-m" in args
        idx = args.index("-m")
        expr = args[idx + 1]
        assert "not regression" in expr
        assert "not slow" in expr

    def test_no_marker_exclusion_without_pyproject(self, tmp_path: Path) -> None:
        with patch(
            "nfr_review.output.pytest_runner.subprocess.run",
            return_value=self._mock_proc("10 passed in 0.50s\n"),
        ) as mock_run:
            run_pytest(tmp_path)

        args = self._pytest_args(mock_run)
        assert "-m" not in args

    def test_no_marker_exclusion_without_expensive_markers(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.pytest.ini_options]\nmarkers = [\n    "unit: fast tests",\n]\n'
        )
        with patch(
            "nfr_review.output.pytest_runner.subprocess.run",
            return_value=self._mock_proc("10 passed in 0.50s\n"),
        ) as mock_run:
            run_pytest(tmp_path)

        args = self._pytest_args(mock_run)
        assert "-m" not in args


class TestDetectExpensiveMarkers:
    """Tests for _detect_expensive_markers helper."""

    def test_finds_regression_and_slow(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.pytest.ini_options]\n"
            "markers = [\n"
            '    "regression: clones repos and diffs output",\n'
            '    "slow: full analysis pass (may hit network)",\n'
            '    "unit: fast tests",\n'
            "]\n"
        )
        result = _detect_expensive_markers(tmp_path)
        assert sorted(result) == ["regression", "slow"]

    def test_no_pyproject(self, tmp_path: Path) -> None:
        assert _detect_expensive_markers(tmp_path) == []

    def test_no_markers_section(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
        assert _detect_expensive_markers(tmp_path) == []

    def test_only_regression(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.pytest.ini_options]\nmarkers = ["regression: clones repos"]\n'
        )
        assert _detect_expensive_markers(tmp_path) == ["regression"]

    def test_invalid_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("not valid toml {{{\n")
        assert _detect_expensive_markers(tmp_path) == []
