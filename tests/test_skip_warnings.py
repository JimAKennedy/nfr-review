# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests that skipped-rule warnings are surfaced at default verbosity."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from nfr_review.cli import cli

CMAKE_FIXTURE = Path(__file__).parent / "fixtures" / "cmake-sample-repo"


def test_run_prints_skipped_rule_warnings(tmp_path: Path) -> None:
    """Running on a non-Spring repo should print WARNING for skipped Spring rules."""
    csv_path = tmp_path / "out.csv"
    jsonl_path = tmp_path / "out.jsonl"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            str(CMAKE_FIXTURE),
            "--csv",
            str(csv_path),
            "--jsonl",
            str(jsonl_path),
        ],
    )
    assert result.exit_code == 0, result.output
    # Should show the summary warning about skipped rules
    assert "rules skipped" in result.output
    assert "use -v to see details" in result.output
