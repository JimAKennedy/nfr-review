# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the architecture review orchestrator and CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from nfr_review.arch_models import ArchReport
from nfr_review.arch_orchestrator import run_arch_review
from nfr_review.cli import _execute_all_pipelines, cli
from nfr_review.config import LlmConfig
from nfr_review.llm_integration import ProviderUnavailableError


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

    def test_dvc_pipeline_diagram_when_dvc_yaml_present(self, sample_repo: Path) -> None:
        (sample_repo / "dvc.yaml").write_text(
            "stages:\n"
            "  prepare:\n"
            "    cmd: python prepare.py\n"
            "    outs:\n"
            "      - prepared/\n"
            "  train:\n"
            "    cmd: python train.py\n"
            "    deps:\n"
            "      - prepared/\n"
            "    outs:\n"
            "      - model.pt\n"
        )
        report = run_arch_review([sample_repo], skip_llm=True)
        pipeline_diagrams = [d for d in report.diagrams if d.scope == "pipeline"]
        assert len(pipeline_diagrams) == 1
        assert "prepare" in pipeline_diagrams[0].mermaid
        assert "train" in pipeline_diagrams[0].mermaid
        assert "prepare --> train" in pipeline_diagrams[0].mermaid

    def test_no_pipeline_diagram_without_dvc(self, sample_repo: Path) -> None:
        report = run_arch_review([sample_repo], skip_llm=True)
        pipeline_diagrams = [d for d in report.diagrams if d.scope == "pipeline"]
        assert len(pipeline_diagrams) == 0

    def test_dvc_in_subdirectory(self, sample_repo: Path) -> None:
        ml_dir = sample_repo / "training"
        ml_dir.mkdir()
        (ml_dir / "dvc.yaml").write_text("stages:\n  train:\n    cmd: python train.py\n")
        report = run_arch_review([sample_repo], skip_llm=True)
        pipeline_diagrams = [d for d in report.diagrams if d.scope == "pipeline"]
        assert len(pipeline_diagrams) == 1


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
        json_files = list(out_dir.glob("*-architecture-report.json"))
        assert len(json_files) == 1

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
        md_files = list(out_dir.glob("*-architecture-report.md"))
        assert len(md_files) == 1

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
        assert len(list(out_dir.glob("*-architecture-report.json"))) == 1
        assert len(list(out_dir.glob("*-architecture-report.md"))) == 1

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

    def test_arch_dsl_output(self, sample_repo: Path, tmp_path: Path) -> None:
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
                "dsl",
            ],
        )
        assert result.exit_code == 0, result.output
        dsl_files = list(out_dir.glob("*-architecture.dsl"))
        assert len(dsl_files) == 1
        content = dsl_files[0].read_text()
        assert content.startswith("workspace")

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


class _OfflineClient:
    """An available LLM client whose calls fail, so analysis falls back."""

    available = True

    def call(self, prompt: str, *, max_tokens: int = 1024) -> str:
        raise ProviderUnavailableError("offline test client")


class TestArchLlmModelDisclosure:
    @pytest.fixture()
    def created_with(self, monkeypatch: pytest.MonkeyPatch) -> list[LlmConfig | None]:
        """Clear NFR_LLM_* and record the config each client is created with."""
        for var in (
            "NFR_LLM_MODEL",
            "NFR_LLM_PROVIDER",
            "NFR_LLM_BACKEND",
            "NFR_LLM_BASE_URL",
        ):
            monkeypatch.delenv(var, raising=False)
        seen: list[LlmConfig | None] = []

        def _fake_create(config: LlmConfig | None = None) -> _OfflineClient:
            seen.append(config)
            return _OfflineClient()

        monkeypatch.setattr("nfr_review.llm_integration.create_llm_client", _fake_create)
        return seen

    def test_model_from_config_only(
        self, sample_repo: Path, created_with: list[LlmConfig | None]
    ) -> None:
        report = run_arch_review(
            [sample_repo], llm_config=LlmConfig(model="config-only-model")
        )
        assert report.metadata.llm_available is True
        assert report.metadata.llm_model == "config-only-model"
        assert created_with[0] is not None
        assert created_with[0].model == "config-only-model"

    def test_env_override_is_disclosed(
        self,
        sample_repo: Path,
        created_with: list[LlmConfig | None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NFR_LLM_MODEL", "env-model")
        report = run_arch_review([sample_repo], llm_config=LlmConfig(model="config-model"))
        assert report.metadata.llm_model == "env-model"

    def test_default_model_without_config(
        self, sample_repo: Path, created_with: list[LlmConfig | None]
    ) -> None:
        report = run_arch_review([sample_repo])
        assert report.metadata.llm_model == LlmConfig().model

    def test_all_pipeline_passes_config_llm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = tmp_path / "nfr-review.yaml"
        cfg.write_text("llm:\n  model: cfg-file-model\n", encoding="utf-8")
        seen: dict[str, object] = {}

        def _fake_run_arch_review(targets: list[Path], **kwargs: object) -> ArchReport:
            seen.update(kwargs)
            raise RuntimeError("stop after capturing the arguments")

        monkeypatch.setattr(
            "nfr_review.arch_orchestrator.run_arch_review", _fake_run_arch_review
        )
        with pytest.raises(click.exceptions.Exit):
            _execute_all_pipelines(
                target_list=[tmp_path],
                repo_names=["repo"],
                timestamp="20260101T000000",
                output_dir=tmp_path / "out",
                config_path=cfg,
                no_arch=False,
                no_tests=True,
                no_deps=True,
                no_diagrams=True,
                no_pdf=True,
                no_summary=True,
                test_timeout=1,
                no_score=True,
                max_resolve_rounds=None,
                no_llm=False,
                diagram_mode="hierarchical",
                exclude_tests=False,
                workers=1,
                quiet=True,
            )
        llm_config = seen["llm_config"]
        assert isinstance(llm_config, LlmConfig)
        assert llm_config.model == "cfg-file-model"


class TestArchTestPathExclusion:
    """``exclude_test_paths`` reaches config-integration discovery."""

    @staticmethod
    def _repo_with_test_config(root: Path) -> Path:
        cfg_dir = root / "src" / "test" / "resources"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "application.yml").write_text(
            "spring:\n  redis:\n    url: redis://test-cache:6379\n"
        )
        (root / "pyproject.toml").write_text('[project]\nname = "s"\nversion = "0.1.0"\n')
        return root

    def test_default_excludes_test_path_config(self, tmp_path: Path) -> None:
        repo = self._repo_with_test_config(tmp_path)
        report = run_arch_review([repo], skip_llm=True)
        assert [i for i in report.integration_points if i.protocol == "redis"] == []

    def test_exclusion_off_discovers_test_path_config(self, tmp_path: Path) -> None:
        repo = self._repo_with_test_config(tmp_path)
        report = run_arch_review([repo], skip_llm=True, exclude_test_paths=False)
        assert len([i for i in report.integration_points if i.protocol == "redis"]) == 1

    def test_all_command_include_tests_reaches_arch_review(self, tmp_path: Path) -> None:
        from nfr_review.cli import _execute_all_pipelines

        with (
            patch("nfr_review.arch_orchestrator.run_arch_review") as arch,
            patch("nfr_review.arch_report_render.render_arch_report", return_value={}),
            patch("nfr_review.cli.run_report_pipeline", return_value=MagicMock()),
        ):
            _execute_all_pipelines(
                target_list=[tmp_path],
                repo_names=["repo"],
                timestamp="20260101-000000",
                output_dir=tmp_path / "out",
                config_path=None,
                no_arch=False,
                no_tests=True,
                no_deps=True,
                no_diagrams=True,
                no_pdf=True,
                no_summary=True,
                test_timeout=1,
                no_score=True,
                max_resolve_rounds=None,
                no_llm=True,
                diagram_mode="hierarchical",
                exclude_tests=False,
                workers=1,
                quiet=True,
            )

        assert arch.call_args.kwargs["exclude_test_paths"] is False
