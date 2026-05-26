# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the architecture review orchestrator and CLI command."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.arch_models import ArchReport
from nfr_review.arch_orchestrator import run_arch_review
from nfr_review.cli import cli


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure for testing."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("# sample\n")
    (src / "main.py").write_text("def main():\n    pass\n")

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text("def test_main():\n    pass\n")

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "sample"\nversion = "0.1.0"\n')
    (tmp_path / "README.md").write_text("# Sample\n")
    return tmp_path


class TestRunArchReview:
    """Tests for run_arch_review orchestrator."""

    def test_returns_arch_report(self, sample_repo: Path) -> None:
        report = run_arch_review([sample_repo], skip_llm=True)
        assert isinstance(report, ArchReport)

    def test_metadata_populated(self, sample_repo: Path) -> None:
        report = run_arch_review([sample_repo], skip_llm=True)
        assert report.metadata.tool_version
        assert report.metadata.timestamp
        assert len(report.metadata.repos_analyzed) == 1
        assert report.metadata.repos_analyzed[0].name == sample_repo.name

    def test_llm_not_available_when_skipped(self, sample_repo: Path) -> None:
        report = run_arch_review([sample_repo], skip_llm=True)
        assert report.metadata.llm_available is False
        assert report.metadata.llm_model is None

    def test_components_discovered(self, sample_repo: Path) -> None:
        report = run_arch_review([sample_repo], skip_llm=True)
        assert isinstance(report.components, list)

    def test_diagrams_generated(self, sample_repo: Path) -> None:
        report = run_arch_review([sample_repo], skip_llm=True)
        assert isinstance(report.diagrams, list)

    def test_risk_findings_list(self, sample_repo: Path) -> None:
        report = run_arch_review([sample_repo], skip_llm=True)
        assert isinstance(report.risk_findings, list)

    def test_recommendations_list(self, sample_repo: Path) -> None:
        report = run_arch_review([sample_repo], skip_llm=True)
        assert isinstance(report.recommendations, list)

    def test_custom_repo_names(self, sample_repo: Path) -> None:
        report = run_arch_review([sample_repo], repo_names=["my-repo"], skip_llm=True)
        assert report.metadata.repos_analyzed[0].name == "my-repo"

    def test_progress_callback(self, sample_repo: Path) -> None:
        messages: list[str] = []
        report = run_arch_review([sample_repo], skip_llm=True, progress=messages.append)
        assert isinstance(report, ArchReport)
        assert len(messages) > 0
        assert any("component" in m.lower() for m in messages)

    def test_multi_repo(self, tmp_path: Path) -> None:
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        (repo_a / "main.py").write_text("x = 1\n")

        repo_b = tmp_path / "repo-b"
        repo_b.mkdir()
        (repo_b / "app.py").write_text("y = 2\n")

        report = run_arch_review([repo_a, repo_b], skip_llm=True)
        assert len(report.metadata.repos_analyzed) == 2

    def test_schema_version_set(self, sample_repo: Path) -> None:
        report = run_arch_review([sample_repo], skip_llm=True)
        assert report.schema_version == "1.0.0"

    def test_dynamic_scenarios_empty(self, sample_repo: Path) -> None:
        report = run_arch_review([sample_repo], skip_llm=True)
        assert report.dynamic_scenarios == []


class TestArchCliCommand:
    """Tests for the 'nfr-review arch' CLI command."""

    def test_arch_basic_run(self, sample_repo: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["arch", str(sample_repo), "--no-llm"])
            assert result.exit_code == 0, result.output + (
                result.stderr if hasattr(result, "stderr") else ""
            )

    def test_arch_json_output(self, sample_repo: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "arch",
                str(sample_repo),
                "--no-llm",
                "--output-dir",
                str(out_dir),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        json_file = out_dir / "architecture-report.json"
        assert json_file.exists()

    def test_arch_markdown_output(self, sample_repo: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "arch",
                str(sample_repo),
                "--no-llm",
                "--output-dir",
                str(out_dir),
                "--format",
                "md",
            ],
        )
        assert result.exit_code == 0
        md_file = out_dir / "architecture-report.md"
        assert md_file.exists()

    def test_arch_multiple_formats(self, sample_repo: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "arch",
                str(sample_repo),
                "--no-llm",
                "--output-dir",
                str(out_dir),
                "--format",
                "json",
                "--format",
                "md",
            ],
        )
        assert result.exit_code == 0
        assert (out_dir / "architecture-report.json").exists()
        assert (out_dir / "architecture-report.md").exists()

    def test_arch_no_target_fails(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["arch"])
        assert result.exit_code != 0

    def test_arch_nonexistent_target_fails(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["arch", "/nonexistent/path"])
        assert result.exit_code != 0

    def test_arch_verbose_quiet_conflict(self, sample_repo: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["arch", str(sample_repo), "-v", "-q"])
        assert result.exit_code != 0

    def test_arch_quiet_mode(self, sample_repo: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "arch",
                str(sample_repo),
                "--no-llm",
                "-q",
                "--output-dir",
                str(out_dir),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0

    def test_arch_multi_repo(self, tmp_path: Path) -> None:
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        (repo_a / "main.py").write_text("x = 1\n")

        repo_b = tmp_path / "repo-b"
        repo_b.mkdir()
        (repo_b / "app.py").write_text("y = 2\n")

        out_dir = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "arch",
                str(repo_a),
                str(repo_b),
                "--no-llm",
                "--output-dir",
                str(out_dir),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
