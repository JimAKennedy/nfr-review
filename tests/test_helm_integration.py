"""Helm integration tests — full Engine pipeline with HelmCollector + 3 Helm rules."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from nfr_review.collectors.helm import HelmCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.helm_chart_metadata import HelmChartMetadataRule
from nfr_review.rules.helm_secret_leakage import HelmSecretLeakageRule
from nfr_review.rules.helm_values_validation import HelmValuesValidationRule
from nfr_review.rules.sample import ReadmeExistsRule

FIXTURES = Path(__file__).parent / "fixtures"
HELM_SAMPLE = FIXTURES / "helm-sample-repo"
HELM_GOOD = FIXTURES / "helm-good-chart"

HELM_RULE_IDS = {
    "helm-chart-metadata",
    "helm-values-validation",
    "helm-secret-leakage",
}


def _helm_registries() -> tuple[Registry, Registry]:
    """Build registries with HelmCollector + 3 Helm rules (plus baseline)."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("helm", HelmCollector())

    rregistry.register("sample-readme-exists", ReadmeExistsRule())
    rregistry.register("helm-chart-metadata", HelmChartMetadataRule())
    rregistry.register("helm-values-validation", HelmValuesValidationRule())
    rregistry.register("helm-secret-leakage", HelmSecretLeakageRule())

    return cregistry, rregistry


class TestHelmPipelineFindings:
    """Full collector→evidence→rules→findings pipeline against helm-sample-repo."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _helm_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"helm": True})
        return engine.run(target=HELM_SAMPLE, config=cfg)

    def test_chart_metadata_rule_fires(self, result: RunResult) -> None:
        meta_findings = [f for f in result.findings if f.rule_id == "helm-chart-metadata"]
        assert len(meta_findings) >= 1
        assert any("maintainer" in f.summary.lower() for f in meta_findings)

    def test_values_validation_rule_fires(self, result: RunResult) -> None:
        val_findings = [f for f in result.findings if f.rule_id == "helm-values-validation"]
        assert len(val_findings) >= 1
        assert any("resource" in f.summary.lower() for f in val_findings)

    def test_secret_leakage_rule_fires(self, result: RunResult) -> None:
        secret_findings = [f for f in result.findings if f.rule_id == "helm-secret-leakage"]
        assert len(secret_findings) >= 1
        assert any(
            "secret" in f.summary.lower() or "password" in f.summary.lower()
            for f in secret_findings
        )

    def test_all_three_helm_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert HELM_RULE_IDS <= run_set

    def test_run_metadata_has_helm_collector_version(self, result: RunResult) -> None:
        assert "helm" in result.run_metadata.collector_versions
        assert result.run_metadata.collector_versions["helm"] == "0.1.0"


class TestHelmTechGating:
    """Helm rules are skipped when tech={"helm": False}."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _helm_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"helm": False})
        return engine.run(target=HELM_SAMPLE, config=cfg)

    def test_all_helm_rules_skipped(self, result: RunResult) -> None:
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in HELM_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: helm" in skipped[rule_id]

    def test_no_helm_findings_produced(self, result: RunResult) -> None:
        helm_findings = [f for f in result.findings if f.rule_id in HELM_RULE_IDS]
        assert len(helm_findings) == 0

    def test_non_helm_rules_still_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert "sample-readme-exists" in run_set


class TestHelmGracefulDegradation:
    """No crash when helm binary is absent; rules still run on static evidence."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _helm_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"helm": True})
        with patch("nfr_review.collectors.helm.shutil.which", return_value=None):
            return engine.run(target=HELM_SAMPLE, config=cfg)

    def test_no_crash(self, result: RunResult) -> None:
        assert result is not None
        assert result.run_metadata is not None

    def test_helm_rules_still_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert HELM_RULE_IDS <= run_set

    def test_values_findings_still_produced(self, result: RunResult) -> None:
        val_findings = [f for f in result.findings if f.rule_id == "helm-values-validation"]
        assert len(val_findings) >= 1

    def test_secret_findings_still_produced(self, result: RunResult) -> None:
        secret_findings = [f for f in result.findings if f.rule_id == "helm-secret-leakage"]
        assert len(secret_findings) >= 1

    def test_helm_available_flag_false_in_evidence(self, result: RunResult) -> None:
        helm_results = [
            rr for rr in result.rule_results if rr.rule_id in HELM_RULE_IDS and not rr.skipped
        ]
        assert len(helm_results) == 3


class TestHelmGoodChart:
    """Good chart produces green/clean findings."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _helm_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"helm": True})
        return engine.run(target=HELM_GOOD, config=cfg)

    def test_all_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert HELM_RULE_IDS <= run_set

    def test_all_findings_green(self, result: RunResult) -> None:
        helm_findings = [f for f in result.findings if f.rule_id in HELM_RULE_IDS]
        assert len(helm_findings) >= 3
        assert all(f.rag == "green" for f in helm_findings)

    def test_no_amber_or_red_findings(self, result: RunResult) -> None:
        bad_findings = [
            f
            for f in result.findings
            if f.rule_id in HELM_RULE_IDS and f.rag in ("amber", "red")
        ]
        assert len(bad_findings) == 0


class TestHelmEmptyTechSkipsAll:
    """With empty tech dict, all Helm rules are tech-skipped."""

    def test_helm_rules_skipped_with_empty_tech(self) -> None:
        cregistry, rregistry = _helm_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        result = engine.run(target=HELM_SAMPLE, config=cfg)

        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in HELM_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: helm" in skipped[rule_id]
