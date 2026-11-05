"""Dockerfile integration tests — collector + rules through Engine with tech-gating."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from nfr_review.collectors.dockerfile import DockerfileCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.dockerfile_base_pinning import DockerfileBasePinningRule
from nfr_review.rules.dockerfile_multistage import DockerfileMultistageRule
from nfr_review.rules.dockerfile_secret_leakage import DockerfileSecretLeakageRule
from nfr_review.rules.dockerfile_user_directive import DockerfileUserDirectiveRule
from nfr_review.rules.sample import ReadmeExistsRule

FIXTURES = Path(__file__).parent / "fixtures"
DOCKERFILE_REPO = FIXTURES / "dockerfile-sample-repo"

DOCKERFILE_RULE_IDS = {
    "dockerfile-base-pinning",
    "dockerfile-user-directive",
    "dockerfile-secret-leakage",
    "dockerfile-multistage",
}


def _dockerfile_registries() -> tuple[Registry, Registry]:
    """Build registries with Dockerfile collector/rules + ReadmeExists."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("dockerfile", DockerfileCollector())
    cregistry.register("repo-structure", RepoStructureCollector())

    rregistry.register("dockerfile-base-pinning", DockerfileBasePinningRule())
    rregistry.register("dockerfile-user-directive", DockerfileUserDirectiveRule())
    rregistry.register("dockerfile-secret-leakage", DockerfileSecretLeakageRule())
    rregistry.register("dockerfile-multistage", DockerfileMultistageRule())
    rregistry.register("sample-readme-exists", ReadmeExistsRule())

    return cregistry, rregistry


class TestDockerfileRulesFire:
    """Dockerfile rules fire and produce expected findings when tech=dockerfile declared."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _dockerfile_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"dockerfile": True})
        return engine.run(target=DOCKERFILE_REPO, config=cfg)

    def test_all_four_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert DOCKERFILE_RULE_IDS <= run_set

    def test_base_pinning_fires_amber(self, result: RunResult) -> None:
        amber_pinning = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-base-pinning" and f.rag == "amber"
        ]
        assert len(amber_pinning) >= 1
        assert any("python" in f.summary.lower() for f in amber_pinning)

    def test_user_directive_fires_amber(self, result: RunResult) -> None:
        amber_user = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-user-directive" and f.rag == "amber"
        ]
        assert len(amber_user) >= 1

    def test_secret_leakage_fires_red(self, result: RunResult) -> None:
        red_secrets = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-secret-leakage" and f.rag == "red"
        ]
        assert len(red_secrets) >= 1

    def test_multistage_fires_amber(self, result: RunResult) -> None:
        amber_multi = [
            f
            for f in result.findings
            if f.rule_id == "dockerfile-multistage" and f.rag == "amber"
        ]
        assert len(amber_multi) >= 1

    def test_finding_rule_ids_cover_all_four(self, result: RunResult) -> None:
        finding_rule_ids = {f.rule_id for f in result.findings}
        assert DOCKERFILE_RULE_IDS <= finding_rule_ids


class TestDockerfileTechGating:
    """Dockerfile rules skipped when dockerfile tech not declared."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _dockerfile_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        return engine.run(target=DOCKERFILE_REPO, config=cfg)

    def test_all_dockerfile_rules_skipped(self, result: RunResult) -> None:
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in DOCKERFILE_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: dockerfile" in skipped[rule_id]

    def test_readme_rule_still_runs(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert "sample-readme-exists" in run_set


class TestGreenFindingsOnGoodDockerfile:
    """Rules produce mostly green findings on a repo with a well-written Dockerfile.

    The good fixture (services/good/Dockerfile) uses a digest-pinned first stage
    and USER nonroot, but the second stage (gcr.io/distroless/static:nonroot) has
    a non-version tag, so base-pinning correctly flags it as amber.
    """

    @pytest.fixture()
    def good_repo(self, tmp_path: Path) -> Path:
        src = DOCKERFILE_REPO / "services" / "good" / "Dockerfile"
        dest = tmp_path / "Dockerfile"
        shutil.copy2(src, dest)
        return tmp_path

    @pytest.fixture()
    def result(self, good_repo: Path) -> RunResult:
        cregistry, rregistry = _dockerfile_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"dockerfile": True})
        return engine.run(target=good_repo, config=cfg)

    def test_all_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert DOCKERFILE_RULE_IDS <= run_set

    def test_user_directive_green(self, result: RunResult) -> None:
        user_findings = [
            f for f in result.findings if f.rule_id == "dockerfile-user-directive"
        ]
        assert all(f.rag == "green" for f in user_findings)

    def test_secret_leakage_green(self, result: RunResult) -> None:
        secret_findings = [
            f for f in result.findings if f.rule_id == "dockerfile-secret-leakage"
        ]
        assert all(f.rag == "green" for f in secret_findings)

    def test_multistage_green(self, result: RunResult) -> None:
        multi_findings = [f for f in result.findings if f.rule_id == "dockerfile-multistage"]
        assert all(f.rag == "green" for f in multi_findings)

    def test_base_pinning_flags_nonversion_tag(self, result: RunResult) -> None:
        pinning_findings = [
            f for f in result.findings if f.rule_id == "dockerfile-base-pinning"
        ]
        amber = [f for f in pinning_findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "distroless" in amber[0].summary
