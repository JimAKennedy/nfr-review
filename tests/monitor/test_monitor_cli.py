# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the `nfr-review monitor` CLI command."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.cli import cli
from nfr_review.monitor.baseline import InteractionBaseline, save_baseline


@pytest.fixture
def baseline_file(tmp_path: Path) -> Path:
    bl = InteractionBaseline(
        source="test",
        trace_count=1,
        span_count=1,
        fingerprints=[],
    )
    p = tmp_path / "baseline.json"
    save_baseline(bl, p)
    return p


class TestMonitorCliValidation:
    def test_monitor_requires_baseline(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["monitor"])
        assert result.exit_code != 0
        assert "baseline" in result.output.lower() or "required" in result.output.lower()

    def test_monitor_rejects_missing_baseline(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["monitor", "--baseline", str(tmp_path / "nope.json")])
        assert result.exit_code != 0

    def test_monitor_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["monitor", "--help"])
        assert result.exit_code == 0
        assert "--baseline" in result.output
        assert "--port" in result.output
        assert "--window-seconds" in result.output
