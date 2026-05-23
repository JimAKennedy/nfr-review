# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the ``nfr-review init`` CLI command."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from ruamel.yaml import YAML

from nfr_review.cli import cli

JAVA_FIXTURE = Path(__file__).parent / "fixtures" / "java-sample-repo"


def test_init_dry_run_prints_valid_yaml() -> None:
    """``init --dry-run`` should print valid YAML with detected tech keys."""
    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(JAVA_FIXTURE), "--dry-run"])
    assert result.exit_code == 0, result.output

    yaml = YAML(typ="safe")
    data = yaml.load(result.stdout)
    assert data["version"] == 1
    assert data["tech"]["java"] is True
    assert data["tech"]["kubernetes"] is True


def test_init_writes_config_file(tmp_path: Path) -> None:
    """``init`` without --dry-run creates nfr-review.yaml in target dir."""
    # Create a minimal repo with a Java file to trigger detection
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "Main.java").write_text("public class Main {}\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(tmp_path)])
    assert result.exit_code == 0, result.output

    cfg_path = tmp_path / "nfr-review.yaml"
    assert cfg_path.exists()

    yaml = YAML(typ="safe")
    data = yaml.load(cfg_path.read_text())
    assert data["version"] == 1
    assert data["tech"]["java"] is True


def test_init_nonexistent_directory_exits_1(tmp_path: Path) -> None:
    """``init`` on a nonexistent directory should exit with code 1."""
    missing = tmp_path / "does-not-exist"
    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(missing)])
    assert result.exit_code == 1
