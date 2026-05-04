"""Tests for the CiArtifactCollector — YAML parsing, test step detection,
security scan detection, summary evidence, and fault isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.ci_artifact import CiArtifactCollector

FIXTURES = Path(__file__).parent / "fixtures" / "ci-sample-repo"


@pytest.fixture
def collector() -> CiArtifactCollector:
    return CiArtifactCollector()


class TestFileDiscovery:
    def test_finds_github_actions_workflows(
        self, collector: CiArtifactCollector
    ) -> None:
        results = collector.collect(FIXTURES, config=None)
        pipelines = [e for e in results if e.kind == "ci-pipeline"]
        assert len(pipelines) == 2
        systems = {e.payload["ci_system"] for e in pipelines}
        assert systems == {"github-actions"}

    def test_empty_dir_returns_no_evidence(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_detects_gitlab_ci(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        (tmp_path / ".gitlab-ci.yml").write_text(
            "test:\n  script:\n    - pytest\n"
        )
        results = collector.collect(tmp_path, config=None)
        pipelines = [e for e in results if e.kind == "ci-pipeline"]
        assert len(pipelines) == 1
        assert pipelines[0].payload["ci_system"] == "gitlab-ci"

    def test_detects_jenkinsfile_presence_only(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "Jenkinsfile").write_text(
            "pipeline {\n  agent any\n  stages { }\n}\n"
        )
        results = collector.collect(tmp_path, config=None)
        pipelines = [e for e in results if e.kind == "ci-pipeline"]
        assert len(pipelines) == 1
        assert pipelines[0].payload["ci_system"] == "jenkins"
        assert pipelines[0].payload["has_test_step"] is False


class TestTestStepDetection:
    def test_detects_mvn_test(self, collector: CiArtifactCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        ci_yml = next(
            e for e in results
            if e.kind == "ci-pipeline" and "ci.yml" in e.locator
        )
        assert ci_yml.payload["has_test_step"] is True

    def test_deploy_lacks_test_step(self, collector: CiArtifactCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        deploy = next(
            e for e in results
            if e.kind == "ci-pipeline" and "deploy.yml" in e.locator
        )
        assert deploy.payload["has_test_step"] is False

    def test_detects_pytest_in_script(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        gh_dir = tmp_path / ".github" / "workflows"
        gh_dir.mkdir(parents=True)
        (gh_dir / "test.yml").write_text(
            "name: Test\non: push\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n"
            "      - name: Run tests\n        run: pytest -q\n"
        )
        results = collector.collect(tmp_path, config=None)
        pipeline = next(e for e in results if e.kind == "ci-pipeline")
        assert pipeline.payload["has_test_step"] is True


class TestSecurityScanDetection:
    def test_detects_codeql(self, collector: CiArtifactCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        ci_yml = next(
            e for e in results
            if e.kind == "ci-pipeline" and "ci.yml" in e.locator
        )
        assert ci_yml.payload["has_security_scan"] is True

    def test_deploy_lacks_security_scan(
        self, collector: CiArtifactCollector
    ) -> None:
        results = collector.collect(FIXTURES, config=None)
        deploy = next(
            e for e in results
            if e.kind == "ci-pipeline" and "deploy.yml" in e.locator
        )
        assert deploy.payload["has_security_scan"] is False

    def test_detects_snyk_in_uses(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        gh_dir = tmp_path / ".github" / "workflows"
        gh_dir.mkdir(parents=True)
        (gh_dir / "security.yml").write_text(
            "name: Security\non: push\njobs:\n  scan:\n"
            "    runs-on: ubuntu-latest\n    steps:\n"
            "      - name: Snyk scan\n        uses: snyk/actions/node@master\n"
        )
        results = collector.collect(tmp_path, config=None)
        pipeline = next(e for e in results if e.kind == "ci-pipeline")
        assert pipeline.payload["has_security_scan"] is True


class TestJobAndStepExtraction:
    def test_extracts_job_names(self, collector: CiArtifactCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        ci_yml = next(
            e for e in results
            if e.kind == "ci-pipeline" and "ci.yml" in e.locator
        )
        assert "test" in ci_yml.payload["job_names"]

    def test_extracts_step_names(self, collector: CiArtifactCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        ci_yml = next(
            e for e in results
            if e.kind == "ci-pipeline" and "ci.yml" in e.locator
        )
        assert "Run tests" in ci_yml.payload["step_names"]
        assert "Security scan" in ci_yml.payload["step_names"]


class TestSummaryEvidence:
    def test_emits_summary_with_counts(
        self, collector: CiArtifactCollector
    ) -> None:
        results = collector.collect(FIXTURES, config=None)
        summary = next(e for e in results if e.kind == "ci-summary")
        assert summary.payload["total_pipelines"] == 2
        assert "github-actions" in summary.payload["ci_systems"]
        assert summary.payload["any_test_step"] is True
        assert summary.payload["any_security_scan"] is True

    def test_no_summary_for_empty_repo(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        results = collector.collect(tmp_path, config=None)
        assert not any(e.kind == "ci-summary" for e in results)


class TestFaultIsolation:
    def test_non_ci_yaml_handled_gracefully(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        gh_dir = tmp_path / ".github" / "workflows"
        gh_dir.mkdir(parents=True)
        # YAML that doesn't match CI structure (just a list)
        (gh_dir / "weird.yml").write_text("- item1\n- item2\n")
        (gh_dir / "good.yml").write_text(
            "name: Good\non: push\njobs:\n  build:\n"
            "    runs-on: ubuntu-latest\n    steps:\n"
            "      - name: Build\n        run: make\n"
        )
        results = collector.collect(tmp_path, config=None)
        pipelines = [e for e in results if e.kind == "ci-pipeline"]
        assert len(pipelines) == 1

    def test_malformed_yaml_skipped(
        self, collector: CiArtifactCollector, tmp_path: Path
    ) -> None:
        gh_dir = tmp_path / ".github" / "workflows"
        gh_dir.mkdir(parents=True)
        (gh_dir / "bad.yml").write_text("{{{{ not yaml at all")
        results = collector.collect(tmp_path, config=None)
        assert results == []
