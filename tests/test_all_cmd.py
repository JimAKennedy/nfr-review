# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Integration tests for the 'all' CLI command."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.cli import cli

FIXTURES = Path(__file__).parent / "fixtures"
REPO_A = FIXTURES / "ci-sample-repo"
REPO_B = FIXTURES / "adr-sample-repo"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestAllCommand:
    """Tests for nfr-review all."""

    def test_help_shows_options(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["all", "--help"])
        assert result.exit_code == 0
        assert "--no-arch" in result.output
        assert "--no-tests" in result.output
        assert "--no-pdf" in result.output
        assert "TARGETS..." in result.output

    def test_two_repos_produces_per_repo_output(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "all",
                str(REPO_A),
                str(REPO_B),
                "--output-dir",
                str(tmp_path),
                "--no-pdf",
                "--no-tests",
                "--no-deps",
                "--no-diagrams",
                "--no-arch",
                "--no-score",
                "-q",
            ],
        )
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"

        md_files = list(tmp_path.glob("*-nfr-review-*.md"))
        csv_files = list(tmp_path.glob("*-nfr-review-*.csv"))
        jsonl_files = list(tmp_path.glob("*-nfr-review-*.jsonl"))

        assert len(md_files) == 2, f"Expected 2 md files, got {md_files}"
        assert len(csv_files) == 2, f"Expected 2 csv files, got {csv_files}"
        assert len(jsonl_files) == 2, f"Expected 2 jsonl files, got {jsonl_files}"

        repo_a_name = REPO_A.resolve().name
        repo_b_name = REPO_B.resolve().name
        md_names = {f.name for f in md_files}
        assert any(repo_a_name in n for n in md_names)
        assert any(repo_b_name in n for n in md_names)

    def test_single_repo_works(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            cli,
            [
                "all",
                str(REPO_A),
                "--output-dir",
                str(tmp_path),
                "--no-pdf",
                "--no-tests",
                "--no-deps",
                "--no-diagrams",
                "--no-arch",
                "--no-score",
                "-q",
            ],
        )
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"

        md_files = list(tmp_path.glob("*-nfr-review-*.md"))
        assert len(md_files) == 1

    def test_no_targets_fails(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["all"])
        assert result.exit_code != 0
