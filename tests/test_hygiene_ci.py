"""Tests for CI-automation collector and HYG-CI-001 through HYG-CI-007 rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nfr_review.hygiene import hygiene_collector_registry, hygiene_rule_registry
from nfr_review.hygiene.collectors.ci_automation import CiAutomationCollector
from nfr_review.hygiene.rules.ci_coverage_gate import CiCoverageGateRule
from nfr_review.hygiene.rules.ci_has_ci import CiPresenceRule
from nfr_review.hygiene.rules.ci_has_lint import CiHasLintRule
from nfr_review.hygiene.rules.ci_has_sast import CiHasSastRule
from nfr_review.hygiene.rules.ci_has_tests import CiHasTestsRule
from nfr_review.hygiene.rules.ci_pin_actions import CiPinActionsRule
from nfr_review.hygiene.rules.ci_release_publish import CiReleasePublishRule
from nfr_review.models import Evidence

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(payload: dict[str, Any]) -> list[Evidence]:
    return [
        Evidence(
            collector_name="ci-automation",
            collector_version="0.1.0",
            locator=".",
            kind="ci-automation-analysis",
            payload=payload,
        )
    ]


def _ci_payload(
    *,
    ci_systems: list[str] | None = None,
    configs: list[dict[str, Any]] | None = None,
    has_ci: bool = True,
) -> dict[str, Any]:
    return {
        "ci_systems": ci_systems or [],
        "configs": configs or [],
        "has_ci": has_ci,
    }


def _gha_config(
    steps: list[str] | None = None,
    jobs: list[str] | None = None,
    path: str = ".github/workflows/ci.yml",
) -> dict[str, Any]:
    return {
        "path": path,
        "provider": "github-actions",
        "raw_content_length": 100,
        "jobs": jobs or ["build"],
        "steps": steps or [],
    }


def _gitlab_config(
    steps: list[str] | None = None,
    path: str = ".gitlab-ci.yml",
) -> dict[str, Any]:
    return {
        "path": path,
        "provider": "gitlab-ci",
        "raw_content_length": 100,
        "jobs": [],
        "steps": steps or [],
        "has_content": True,
    }


_SAMPLE_GHA_WORKFLOW = """\
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm install
      - run: npm test
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm run lint
"""

_SAMPLE_GHA_WITH_SAST = """\
name: Security
on: [push]
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
      - uses: github/codeql-action/analyze@v3
"""

_SAMPLE_GHA_PINNED = """\
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11
      - run: npm test
"""

_SAMPLE_GITLAB_CI = """\
stages:
  - test
  - lint

test:
  stage: test
  script:
    - pytest tests/

lint:
  stage: lint
  script:
    - ruff check .
"""

_MALFORMED_YAML = """\
name: CI
on: [push
  invalid: yaml: here: {
"""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_collector_registered(self) -> None:
        assert "ci-automation" in hygiene_collector_registry

    def test_all_rules_registered(self) -> None:
        for rule_id in [
            "HYG-CI-001",
            "HYG-CI-002",
            "HYG-CI-003",
            "HYG-CI-004",
            "HYG-CI-005",
            "HYG-CI-006",
            "HYG-CI-007",
        ]:
            assert rule_id in hygiene_rule_registry, f"{rule_id} not registered"

    def test_rule_categories(self) -> None:
        for rule_id in [
            "HYG-CI-001",
            "HYG-CI-002",
            "HYG-CI-003",
            "HYG-CI-004",
            "HYG-CI-005",
            "HYG-CI-006",
            "HYG-CI-007",
        ]:
            rule = hygiene_rule_registry.get(rule_id)
            assert rule.category == "ci-automation"


# ---------------------------------------------------------------------------
# Collector tests
# ---------------------------------------------------------------------------


class TestCiAutomationCollector:
    def test_detects_github_actions(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(_SAMPLE_GHA_WORKFLOW)

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)

        assert len(result) == 1
        payload = result[0].payload
        assert payload["has_ci"] is True
        assert "github-actions" in payload["ci_systems"]
        assert len(payload["configs"]) == 1
        cfg = payload["configs"][0]
        assert cfg["provider"] == "github-actions"
        assert "build" in cfg["jobs"]
        assert "lint" in cfg["jobs"]
        assert any("npm test" in s for s in cfg["steps"])

    def test_detects_gitlab_ci(self, tmp_path: Path) -> None:
        (tmp_path / ".gitlab-ci.yml").write_text(_SAMPLE_GITLAB_CI)

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)

        payload = result[0].payload
        assert payload["has_ci"] is True
        assert "gitlab-ci" in payload["ci_systems"]
        cfg = payload["configs"][0]
        assert cfg["provider"] == "gitlab-ci"
        assert any("pytest" in s for s in cfg.get("steps", []))

    def test_detects_multiple_ci_systems(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(_SAMPLE_GHA_WORKFLOW)
        (tmp_path / ".gitlab-ci.yml").write_text(_SAMPLE_GITLAB_CI)

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)

        payload = result[0].payload
        assert "github-actions" in payload["ci_systems"]
        assert "gitlab-ci" in payload["ci_systems"]
        assert len(payload["configs"]) == 2

    def test_no_ci(self, tmp_path: Path) -> None:
        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)

        payload = result[0].payload
        assert payload["has_ci"] is False
        assert payload["ci_systems"] == []
        assert payload["configs"] == []

    def test_empty_workflows_dir(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)

        payload = result[0].payload
        assert payload["has_ci"] is False

    def test_malformed_yaml_skipped_gracefully(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "bad.yml").write_text(_MALFORMED_YAML)

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)

        payload = result[0].payload
        assert payload["has_ci"] is True
        assert "github-actions" in payload["ci_systems"]
        cfg = payload["configs"][0]
        assert cfg["jobs"] == []
        assert cfg["steps"] == []

    def test_jenkinsfile_detected(self, tmp_path: Path) -> None:
        (tmp_path / "Jenkinsfile").write_text("pipeline { agent any }")

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)

        payload = result[0].payload
        assert payload["has_ci"] is True
        assert "jenkins" in payload["ci_systems"]

    def test_circleci_detected(self, tmp_path: Path) -> None:
        ci_dir = tmp_path / ".circleci"
        ci_dir.mkdir()
        (ci_dir / "config.yml").write_text(
            "version: 2.1\njobs:\n  build:\n    steps:\n      - run: echo hi\n"
        )

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)

        payload = result[0].payload
        assert payload["has_ci"] is True
        assert "circleci" in payload["ci_systems"]

    def test_azure_pipelines_detected(self, tmp_path: Path) -> None:
        (tmp_path / "azure-pipelines.yml").write_text("trigger:\n  - main\n")

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)

        payload = result[0].payload
        assert payload["has_ci"] is True
        assert "azure-devops" in payload["ci_systems"]

    def test_multiple_gha_workflows(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(_SAMPLE_GHA_WORKFLOW)
        (wf_dir / "security.yml").write_text(_SAMPLE_GHA_WITH_SAST)

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)

        payload = result[0].payload
        assert len(payload["configs"]) == 2
        assert payload["ci_systems"].count("github-actions") == 1

    def test_yaml_extension_variants(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yaml").write_text(_SAMPLE_GHA_WORKFLOW)

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)

        payload = result[0].payload
        assert payload["has_ci"] is True


# ---------------------------------------------------------------------------
# HYG-CI-001: CI presence
# ---------------------------------------------------------------------------


class TestCiPresenceRule:
    def test_red_no_ci(self) -> None:
        rule = CiPresenceRule()
        result = rule.evaluate(_make_evidence(_ci_payload(has_ci=False)), None)
        assert result.findings[0].rag == "red"

    def test_green_has_ci(self) -> None:
        rule = CiPresenceRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config()],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_skip_no_evidence(self) -> None:
        rule = CiPresenceRule()
        result = rule.evaluate([], None)
        assert result.skipped is True


# ---------------------------------------------------------------------------
# HYG-CI-002: CI test steps
# ---------------------------------------------------------------------------


class TestCiHasTestsRule:
    def test_red_no_test_steps(self) -> None:
        rule = CiHasTestsRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["npm install", "npm run build"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "red"

    def test_green_pytest(self) -> None:
        rule = CiHasTestsRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["pytest tests/"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_npm_test(self) -> None:
        rule = CiHasTestsRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["npm test"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_cargo_test(self) -> None:
        rule = CiHasTestsRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["cargo test --release"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_go_test(self) -> None:
        rule = CiHasTestsRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["go test ./..."])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_amber_tests_in_one_of_many(self) -> None:
        rule = CiHasTestsRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[
                        _gha_config(steps=["pytest tests/"], path=".github/workflows/ci.yml"),
                        _gha_config(
                            steps=["echo deploy"], path=".github/workflows/deploy.yml"
                        ),
                    ],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "amber"

    def test_skip_no_ci(self) -> None:
        rule = CiHasTestsRule()
        result = rule.evaluate(_make_evidence(_ci_payload(has_ci=False)), None)
        assert result.skipped is True

    def test_skip_no_evidence(self) -> None:
        rule = CiHasTestsRule()
        result = rule.evaluate([], None)
        assert result.skipped is True


# ---------------------------------------------------------------------------
# HYG-CI-003: CI lint steps
# ---------------------------------------------------------------------------


class TestCiHasLintRule:
    def test_amber_no_lint(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["npm test"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "amber"

    def test_green_ruff(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["ruff check ."])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_eslint(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["eslint src/"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_prettier(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["prettier --check ."])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_golangci_lint(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["golangci-lint run"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_checkstyle(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["mvn checkstyle:check"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_spotbugs(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["mvn spotbugs:check"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_pmd(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["./gradlew pmd"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_ktlint(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["./gradlew ktlintCheck"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_detekt(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["./gradlew detekt"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_errorprone(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["./gradlew errorprone"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_error_prone_hyphenated(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["mvn error-prone:check"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_spotless(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["./gradlew spotlessCheck"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_dotnet_format(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["dotnet-format --verify-no-changes"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_roslyn(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["dotnet build /p:roslyn analyzers"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_npm_run_format(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["npm run format"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_gradle_spotbugs_main(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["gradle spotbugsMain"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_gradlew_pmd_main(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["./gradlew pmdMain"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_ktlint_format(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["ktlint --format"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_detekt_input_src(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["detekt --input src"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_dotnet_format_space(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["dotnet format --verify-no-changes"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_spotless_check_run_prefix(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["run: spotlessCheck"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_super_linter_action(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["uses: github/super-linter@v5"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_skip_no_ci(self) -> None:
        rule = CiHasLintRule()
        result = rule.evaluate(_make_evidence(_ci_payload(has_ci=False)), None)
        assert result.skipped is True


# ---------------------------------------------------------------------------
# HYG-CI-004: CI SAST steps
# ---------------------------------------------------------------------------


class TestCiHasSastRule:
    def test_amber_no_sast(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["npm test", "npm run lint"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "amber"

    def test_green_codeql(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["github/codeql-action/init@v3"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_semgrep(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["semgrep scan --config auto"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_trivy(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["trivy fs ."])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_bandit(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["bandit -r src/"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_gitleaks(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["gitleaks detect"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_pip_audit(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["pip-audit --strict"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_npm_audit(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["npm audit --audit-level=high"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_cargo_audit(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["cargo audit"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_govulncheck(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["govulncheck ./..."])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_ossf_scorecard(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["ossf/scorecard-action@v2"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_osv_scanner(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["osv-scanner --lockfile=package-lock.json"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_skip_no_ci(self) -> None:
        rule = CiHasSastRule()
        result = rule.evaluate(_make_evidence(_ci_payload(has_ci=False)), None)
        assert result.skipped is True


# ---------------------------------------------------------------------------
# HYG-CI-005: GitHub Actions SHA pinning
# ---------------------------------------------------------------------------


class TestCiPinActionsRule:
    def test_amber_tag_pins(self) -> None:
        rule = CiPinActionsRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[
                        _gha_config(
                            steps=[
                                "actions/checkout@v4",
                                "actions/setup-node@v4",
                            ]
                        )
                    ],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "amber"
        assert "2 of 2" in result.findings[0].summary

    def test_green_sha_pins(self) -> None:
        rule = CiPinActionsRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[
                        _gha_config(
                            steps=[
                                "actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11",
                                "actions/setup-node@1a4442cacd436585916f99f10081a059d5ff2f0f",
                            ]
                        )
                    ],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_non_gha(self) -> None:
        rule = CiPinActionsRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["gitlab-ci"],
                    configs=[_gitlab_config(steps=["pytest tests/"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"
        assert "not applicable" in result.findings[0].summary.lower()

    def test_mixed_pinned_and_unpinned(self) -> None:
        rule = CiPinActionsRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[
                        _gha_config(
                            steps=[
                                "actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11",
                                "actions/setup-node@v4",
                            ]
                        )
                    ],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "amber"
        assert "1 of 2" in result.findings[0].summary

    def test_green_no_uses(self) -> None:
        rule = CiPinActionsRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["npm test", "npm run build"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_skip_no_ci(self) -> None:
        rule = CiPinActionsRule()
        result = rule.evaluate(_make_evidence(_ci_payload(has_ci=False)), None)
        assert result.skipped is True

    def test_skip_no_evidence(self) -> None:
        rule = CiPinActionsRule()
        result = rule.evaluate([], None)
        assert result.skipped is True


# ---------------------------------------------------------------------------
# HYG-CI-006: CI coverage gate
# ---------------------------------------------------------------------------


class TestCiCoverageGateRule:
    def test_amber_no_coverage_tool(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["npm test", "npm run lint"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "amber"
        assert "No test coverage tooling" in result.findings[0].summary

    def test_amber_tool_no_threshold(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["pytest --cov=src tests/"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "amber"
        assert "no threshold" in result.findings[0].summary.lower()

    def test_green_pytest_cov_with_fail_under(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[
                        _gha_config(steps=["pytest --cov=src --cov-fail-under=80 tests/"])
                    ],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_coverage_report_fail_under(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[
                        _gha_config(
                            steps=[
                                "coverage run -m pytest tests/",
                                "coverage report --fail-under=90",
                            ]
                        )
                    ],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_nyc_check_coverage(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["nyc --check-coverage --lines 80 npm test"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_jacoco_threshold(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[
                        _gha_config(
                            steps=[
                                "./gradlew jacocoTestReport",
                                "./gradlew jacocoTestCoverageVerification"
                                " minimumCoveragePercentage=80",
                            ]
                        )
                    ],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_go_cover(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[
                        _gha_config(
                            steps=[
                                "go test -coverprofile=coverage.out ./...",
                                "COVERAGE_THRESHOLD=80 && coverage=$("
                                "go tool cover -func=coverage.out)",
                            ]
                        )
                    ],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_codecov_action(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[
                        _gha_config(
                            steps=[
                                "codecov/codecov-action@v4",
                                "minimum_coverage=75",
                            ]
                        )
                    ],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_istanbul_c8(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[
                        _gha_config(steps=["c8 --check-coverage --lines 80 node test.js"])
                    ],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_gitlab_coverage(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["gitlab-ci"],
                    configs=[
                        _gitlab_config(
                            steps=[
                                "pytest --cov=src tests/",
                                "coverage report --fail-under=85",
                            ]
                        )
                    ],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_skip_no_ci(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(_make_evidence(_ci_payload(has_ci=False)), None)
        assert result.skipped is True

    def test_skip_no_evidence(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate([], None)
        assert result.skipped is True

    def test_amber_only_codecov_no_threshold(self) -> None:
        rule = CiCoverageGateRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["codecov/codecov-action@v4"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "amber"
        assert "no threshold" in result.findings[0].summary.lower()


# ---------------------------------------------------------------------------
# HYG-CI-007: Release/publish automation
# ---------------------------------------------------------------------------


class TestCiReleasePublishRule:
    def test_amber_no_release_automation(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["npm test", "npm run lint"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "amber"
        assert "No release" in result.findings[0].summary

    def test_green_twine_upload(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["twine upload dist/*"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_poetry_publish(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["poetry publish --build"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_flit_publish(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["flit publish"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_npm_publish(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["npm publish"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_semantic_release(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["npx semantic-release"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_mvn_deploy(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["mvn deploy -DskipTests"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_goreleaser(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["goreleaser release --rm-dist"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_gh_release_action(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["softprops/action-gh-release@v1"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_pypi_publish_action(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["pypa/gh-action-pypi-publish@release/v1"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_cargo_publish(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["cargo publish --token $CARGO_TOKEN"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_docker_push(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["docker push myrepo/app:latest"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_gh_release_create(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["gh release create v1.0.0 --generate-notes"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_gradle_publish(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["./gradlew publish"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_gitlab_release(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["gitlab-ci"],
                    configs=[_gitlab_config(steps=["twine upload dist/*"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_green_changesets_action(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(
            _make_evidence(
                _ci_payload(
                    has_ci=True,
                    ci_systems=["github-actions"],
                    configs=[_gha_config(steps=["changesets/action@v1"])],
                )
            ),
            None,
        )
        assert result.findings[0].rag == "green"

    def test_skip_no_ci(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate(_make_evidence(_ci_payload(has_ci=False)), None)
        assert result.skipped is True

    def test_skip_no_evidence(self) -> None:
        rule = CiReleasePublishRule()
        result = rule.evaluate([], None)
        assert result.skipped is True


# ---------------------------------------------------------------------------
# Integration: collector → rules end-to-end
# ---------------------------------------------------------------------------


class TestCollectorToRuleIntegration:
    def test_full_pipeline_gha(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(_SAMPLE_GHA_WORKFLOW)

        collector = CiAutomationCollector()
        evidence = collector.collect(tmp_path, None)

        ci_rule = CiPresenceRule()
        result = ci_rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

        test_rule = CiHasTestsRule()
        result = test_rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

        lint_rule = CiHasLintRule()
        result = lint_rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_full_pipeline_no_ci(self, tmp_path: Path) -> None:
        collector = CiAutomationCollector()
        evidence = collector.collect(tmp_path, None)

        ci_rule = CiPresenceRule()
        result = ci_rule.evaluate(evidence, None)
        assert result.findings[0].rag == "red"

    def test_full_pipeline_sast(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "security.yml").write_text(_SAMPLE_GHA_WITH_SAST)

        collector = CiAutomationCollector()
        evidence = collector.collect(tmp_path, None)

        sast_rule = CiHasSastRule()
        result = sast_rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_full_pipeline_pinned(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(_SAMPLE_GHA_PINNED)

        collector = CiAutomationCollector()
        evidence = collector.collect(tmp_path, None)

        pin_rule = CiPinActionsRule()
        result = pin_rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_gitlab_ci_integration(self, tmp_path: Path) -> None:
        (tmp_path / ".gitlab-ci.yml").write_text(_SAMPLE_GITLAB_CI)

        collector = CiAutomationCollector()
        evidence = collector.collect(tmp_path, None)

        ci_rule = CiPresenceRule()
        result = ci_rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

        test_rule = CiHasTestsRule()
        result = test_rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

        lint_rule = CiHasLintRule()
        result = lint_rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# Negative tests
# ---------------------------------------------------------------------------


class TestNegativeCases:
    def test_malformed_yaml_collector_no_crash(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "bad.yml").write_text(_MALFORMED_YAML)

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)
        assert len(result) == 1
        assert result[0].payload["has_ci"] is True

    def test_empty_workflows_dir_red(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)

        collector = CiAutomationCollector()
        evidence = collector.collect(tmp_path, None)

        rule = CiPresenceRule()
        result = rule.evaluate(evidence, None)
        assert result.findings[0].rag == "red"

    def test_ci_with_no_test_lint_sast(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "deploy.yml").write_text(
            "name: Deploy\non: [push]\njobs:\n  deploy:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: actions/checkout@v4\n      - run: echo deploy\n"
        )

        collector = CiAutomationCollector()
        evidence = collector.collect(tmp_path, None)

        test_rule = CiHasTestsRule()
        assert test_rule.evaluate(evidence, None).findings[0].rag == "red"

        lint_rule = CiHasLintRule()
        assert lint_rule.evaluate(evidence, None).findings[0].rag == "amber"

        sast_rule = CiHasSastRule()
        assert sast_rule.evaluate(evidence, None).findings[0].rag == "amber"

    def test_malformed_gitlab_yaml(self, tmp_path: Path) -> None:
        (tmp_path / ".gitlab-ci.yml").write_text("invalid: yaml: {{{")

        collector = CiAutomationCollector()
        result = collector.collect(tmp_path, None)
        assert result[0].payload["has_ci"] is True
        assert "gitlab-ci" in result[0].payload["ci_systems"]
