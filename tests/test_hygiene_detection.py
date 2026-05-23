# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests that hygiene command has technology detection wired in."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from nfr_review.cli import cli

JAVA_FIXTURE = Path(__file__).parent / "fixtures" / "java-sample-repo"


def test_hygiene_detects_technologies() -> None:
    """hygiene on java-sample-repo should detect technologies and produce output."""
    runner = CliRunner()
    result = runner.invoke(cli, ["hygiene", str(JAVA_FIXTURE)])
    assert result.exit_code == 0, result.output
    # The detect phase should print the detected technologies to stderr
    assert "Detecting technologies" in result.output
    assert "Technologies:" in result.output
