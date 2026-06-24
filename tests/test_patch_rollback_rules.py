"""Tests for PATCH-ROLL-001, PATCH-ROLL-002, and PATCH-ROLL-003 rollback rules."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.rules.patch_forward_migration import ForwardOnlyMigrationRule
from nfr_review.rules.patch_rollback_ci import CiRollbackStageMissingRule
from nfr_review.rules.patch_rollback_docs import RollbackDocsMissingRule


def _k8s_workload_ev() -> Evidence:
    """Minimal k8s-resource evidence to signal this repo has K8s workloads."""
    return Evidence(
        collector_name="k8s-manifest",
        collector_version="0.1.0",
        locator="deployment.yaml:web",
        kind="k8s-resource",
        payload={"kind": "Deployment", "name": "web", "namespace": "default"},
    )


def _repo_ev(
    top_level_files: list[str] | None = None,
    top_level_dirs: list[str] | None = None,
) -> Evidence:
    return Evidence(
        collector_name="repo-structure",
        collector_version="0.1.0",
        locator=".",
        kind="repo-structure-summary",
        payload={
            "top_level_files": top_level_files or [],
            "top_level_dirs": top_level_dirs or [],
            "has_readme": True,
            "readme_name": "README.md",
            "has_git_dir": True,
            "has_pyproject": True,
        },
    )


def _ci_ev(
    job_names: list[str] | None = None,
    step_names: list[str] | None = None,
    file_path: str = ".github/workflows/deploy.yml",
) -> Evidence:
    return Evidence(
        collector_name="ci-artifact",
        collector_version="0.1.0",
        locator=file_path,
        kind="ci-pipeline",
        payload={
            "file_path": file_path,
            "ci_system": "github-actions",
            "job_names": job_names or [],
            "step_names": step_names or [],
        },
    )


# ---------------------------------------------------------------------------
# PATCH-ROLL-001 — rollback documentation presence
# ---------------------------------------------------------------------------


class TestRollbackDocsMissing:
    def setup_method(self) -> None:
        self.rule = RollbackDocsMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no repo-structure-summary evidence available"

    def test_no_k8s_workloads_info(self) -> None:
        ev = _repo_ev(top_level_files=["README.md"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "not applicable" in result.findings[0].summary.lower()

    def test_no_rollback_docs_amber(self) -> None:
        ev = _repo_ev(
            top_level_files=["README.md", "setup.py"],
            top_level_dirs=["src", "tests"],
        )
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "No rollback documentation" in result.findings[0].summary

    def test_rollback_md_green(self) -> None:
        ev = _repo_ev(top_level_files=["ROLLBACK.md"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "ROLLBACK.md" in result.findings[0].summary

    def test_disaster_recovery_md_green(self) -> None:
        ev = _repo_ev(top_level_files=["disaster-recovery.md"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_runbooks_dir_green(self) -> None:
        ev = _repo_ev(top_level_dirs=["runbooks"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert "runbooks" in result.findings[0].summary

    def test_rollback_dir_green(self) -> None:
        ev = _repo_ev(top_level_dirs=["rollback"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_case_insensitive_file(self) -> None:
        ev = _repo_ev(top_level_files=["rollback.md"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_case_insensitive_dir(self) -> None:
        ev = _repo_ev(top_level_dirs=["Runbooks"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_multiple_matches_multiple_findings(self) -> None:
        ev = _repo_ev(
            top_level_files=["ROLLBACK.md"],
            top_level_dirs=["runbooks"],
        )
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert len(result.findings) == 2
        assert all(f.rag == "green" for f in result.findings)

    def test_rule_id_and_band(self) -> None:
        assert self.rule.id == "PATCH-ROLL-001"
        assert self.rule.band == 1
        assert self.rule.required_collectors == ["repo-structure"]


# ---------------------------------------------------------------------------
# PATCH-ROLL-002 — CI rollback stage presence
# ---------------------------------------------------------------------------


class TestCiRollbackStageMissing:
    def setup_method(self) -> None:
        self.rule = CiRollbackStageMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no ci-pipeline evidence available"

    def test_no_k8s_workloads_info(self) -> None:
        ev = _ci_ev(job_names=["build", "test", "deploy"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_no_rollback_jobs_amber(self) -> None:
        ev = _ci_ev(job_names=["build", "test", "deploy"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "No CI rollback stage" in result.findings[0].summary

    def test_rollback_job_green(self) -> None:
        ev = _ci_ev(job_names=["build", "test", "rollback"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_revert_step_green(self) -> None:
        ev = _ci_ev(step_names=["Build", "Revert on failure"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_canary_rollback_job_green(self) -> None:
        ev = _ci_ev(job_names=["canary-rollback"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_roll_back_hyphenated_green(self) -> None:
        ev = _ci_ev(job_names=["roll-back-prod"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_case_insensitive_match(self) -> None:
        ev = _ci_ev(job_names=["ROLLBACK"])
        result = self.rule.evaluate([ev, _k8s_workload_ev()], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_multiple_pipelines_one_with_rollback(self) -> None:
        ev1 = _ci_ev(job_names=["build", "deploy"], file_path="deploy.yml")
        ev2 = _ci_ev(job_names=["rollback"], file_path="rollback.yml")
        result = self.rule.evaluate([ev1, ev2, _k8s_workload_ev()], None)
        assert not result.skipped
        # ev1 -> amber (no rollback), ev2 -> no hit (has rollback)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_multiple_pipelines_none_with_rollback(self) -> None:
        ev1 = _ci_ev(job_names=["build"], file_path="build.yml")
        ev2 = _ci_ev(job_names=["deploy"], file_path="deploy.yml")
        result = self.rule.evaluate([ev1, ev2, _k8s_workload_ev()], None)
        assert not result.skipped
        # FieldRule evaluates per-pipeline: both produce amber
        assert len(result.findings) == 2
        assert all(f.rag == "amber" for f in result.findings)

    def test_rule_id_and_band(self) -> None:
        assert self.rule.id == "PATCH-ROLL-002"
        assert self.rule.band == 1
        assert self.rule.required_collectors == ["ci-artifact"]


# ---------------------------------------------------------------------------
# PATCH-ROLL-003 — forward-only migration detection
# ---------------------------------------------------------------------------


class TestForwardOnlyMigration:
    def setup_method(self) -> None:
        self.rule = ForwardOnlyMigrationRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no repo-structure-summary evidence available"

    def test_no_migration_dirs_green(self) -> None:
        ev = _repo_ev(top_level_dirs=["src", "docs", "tests"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "No migration directories" in result.findings[0].summary

    def test_migration_dir_no_rollback_amber(self) -> None:
        ev = _repo_ev(
            top_level_dirs=["src", "migrations", "tests"],
            top_level_files=["README.md", "setup.py"],
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "migrations" in result.findings[0].summary

    def test_alembic_dir_no_rollback_amber(self) -> None:
        ev = _repo_ev(top_level_dirs=["src", "alembic"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"
        assert "alembic" in result.findings[0].summary

    def test_migration_dir_with_rollback_dir_green(self) -> None:
        ev = _repo_ev(
            top_level_dirs=["migrations", "rollback"],
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert "dir:rollback" in result.findings[0].summary

    def test_migration_dir_with_rollback_file_green(self) -> None:
        ev = _repo_ev(
            top_level_dirs=["flyway"],
            top_level_files=["rollback.sql"],
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
        assert "file:rollback.sql" in result.findings[0].summary

    def test_migration_dir_with_keyword_file_green(self) -> None:
        ev = _repo_ev(
            top_level_dirs=["migrations"],
            top_level_files=["apply_and_revert.sh"],
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_case_insensitive_migration_dir(self) -> None:
        ev = _repo_ev(top_level_dirs=["Migrations"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"

    def test_multiple_migration_dirs_amber(self) -> None:
        ev = _repo_ev(top_level_dirs=["migrations", "liquibase"])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"
        assert "migrations" in result.findings[0].evidence_locator
        assert "liquibase" in result.findings[0].evidence_locator

    def test_rule_id_and_band(self) -> None:
        assert self.rule.id == "PATCH-ROLL-003"
        assert self.rule.band == 2
        assert self.rule.required_collectors == ["repo-structure"]
