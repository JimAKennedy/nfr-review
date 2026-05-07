"""Terraform integration tests — full Engine pipeline with TerraformCollector."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.collectors.terraform import TerraformCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.sample import ReadmeExistsRule
from nfr_review.rules.terraform_iam_policy import TerraformIamPolicyRule
from nfr_review.rules.terraform_provider_pinning import TerraformProviderPinningRule
from nfr_review.rules.terraform_state_backend import TerraformStateBackendRule

FIXTURES = Path(__file__).parent / "fixtures"
TERRAFORM_SAMPLE = FIXTURES / "terraform-sample-repo"
TERRAFORM_GOOD = FIXTURES / "terraform-good-repo"

TERRAFORM_RULE_IDS = {
    "terraform-state-backend",
    "terraform-iam-policy",
    "terraform-provider-pinning",
}


def _terraform_registries() -> tuple[Registry, Registry]:
    """Build registries with TerraformCollector + 3 Terraform rules (plus baseline)."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("terraform", TerraformCollector())

    rregistry.register("sample-readme-exists", ReadmeExistsRule())
    rregistry.register("terraform-state-backend", TerraformStateBackendRule())
    rregistry.register("terraform-iam-policy", TerraformIamPolicyRule())
    rregistry.register("terraform-provider-pinning", TerraformProviderPinningRule())

    return cregistry, rregistry


class TestTerraformPipelineFindings:
    """Full collector→evidence→rules→findings pipeline against terraform-sample-repo."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _terraform_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"terraform": True})
        return engine.run(target=TERRAFORM_SAMPLE, config=cfg)

    def test_state_backend_rule_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "terraform-state-backend"]
        assert len(findings) >= 1
        assert any(
            "backend" in f.summary.lower() or "state" in f.summary.lower() for f in findings
        )

    def test_iam_policy_rule_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "terraform-iam-policy"]
        assert len(findings) >= 1
        assert any("wildcard" in f.summary.lower() or "*" in f.summary for f in findings)

    def test_provider_pinning_rule_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "terraform-provider-pinning"]
        assert len(findings) >= 1
        assert any(
            "provider" in f.summary.lower() or "version" in f.summary.lower() for f in findings
        )

    def test_all_three_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert TERRAFORM_RULE_IDS <= run_set

    def test_run_metadata_has_terraform_collector_version(self, result: RunResult) -> None:
        assert "terraform" in result.run_metadata.collector_versions
        assert result.run_metadata.collector_versions["terraform"] == "0.1.0"


class TestTerraformTechGating:
    """Terraform rules are skipped when tech={"terraform": False}."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _terraform_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"terraform": False})
        return engine.run(target=TERRAFORM_SAMPLE, config=cfg)

    def test_all_terraform_rules_skipped(self, result: RunResult) -> None:
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in TERRAFORM_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: terraform" in skipped[rule_id]

    def test_no_terraform_findings_produced(self, result: RunResult) -> None:
        tf_findings = [f for f in result.findings if f.rule_id in TERRAFORM_RULE_IDS]
        assert len(tf_findings) == 0

    def test_non_terraform_rules_still_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert "sample-readme-exists" in run_set


class TestTerraformGoodRepo:
    """Good repo produces green/clean findings."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _terraform_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"terraform": True})
        return engine.run(target=TERRAFORM_GOOD, config=cfg)

    def test_all_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert TERRAFORM_RULE_IDS <= run_set

    def test_all_findings_green(self, result: RunResult) -> None:
        tf_findings = [f for f in result.findings if f.rule_id in TERRAFORM_RULE_IDS]
        assert len(tf_findings) >= 3
        assert all(f.rag == "green" for f in tf_findings)

    def test_no_amber_or_red_findings(self, result: RunResult) -> None:
        bad_findings = [
            f
            for f in result.findings
            if f.rule_id in TERRAFORM_RULE_IDS and f.rag in ("amber", "red")
        ]
        assert len(bad_findings) == 0


class TestTerraformEmptyTechSkipsAll:
    """With empty tech dict, all Terraform rules are tech-skipped."""

    def test_terraform_rules_skipped_with_empty_tech(self) -> None:
        cregistry, rregistry = _terraform_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        result = engine.run(target=TERRAFORM_SAMPLE, config=cfg)

        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in TERRAFORM_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: terraform" in skipped[rule_id]
