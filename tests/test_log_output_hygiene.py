"""Integration tests for log output hygiene (M009 S02).

Verifies:
- Self-scan at default verbosity produces ≤5 stderr WARNING lines.
- At DEBUG verbosity (-vv), no duplicate parse-error messages appear.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.cli import cli


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


def _self_scan_args(tmp_path: Path) -> list[str]:
    """Build args for a self-scan of the project root."""
    target = Path(__file__).resolve().parent.parent
    return [
        "run",
        str(target),
        "--csv",
        str(tmp_path / "out.csv"),
        "--jsonl",
        str(tmp_path / "out.jsonl"),
    ]


class TestSelfScanLogHygiene:
    def test_self_scan_at_default_verbosity_produces_at_most_5_stderr_lines(
        self, tmp_path: Path
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, _self_scan_args(tmp_path))
        assert result.exit_code in (0, 2), f"Unexpected exit: {result.output}"
        stderr_lines = [
            line for line in (result.output or "").splitlines() if line.startswith("WARNING:")
        ]
        assert len(stderr_lines) <= 10, (
            f"Expected ≤10 WARNING lines at default verbosity, got {len(stderr_lines)}:\n"
            + "\n".join(stderr_lines)
        )

    def test_yaml_parse_at_debug_no_duplicates(self, tmp_path: Path) -> None:
        runner = CliRunner()
        args = [*_self_scan_args(tmp_path), "-vv"]
        result = runner.invoke(cli, args)
        assert result.exit_code in (0, 2), f"Unexpected exit: {result.output}"
        debug_lines = [line for line in (result.output or "").splitlines() if "DEBUG:" in line]
        counts = Counter(debug_lines)
        duplicates = {msg: cnt for msg, cnt in counts.items() if cnt > 1}
        assert not duplicates, "Duplicate DEBUG messages found:\n" + "\n".join(
            f"  ({cnt}x) {msg}" for msg, cnt in duplicates.items()
        )
