"""Cross-collector integration tests — all 5 M003 technologies in one scan."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.helm import HelmCollector
from nfr_review.collectors.istio import IstioCollector
from nfr_review.collectors.otel import OTelCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.collectors.skaffold import SkaffoldCollector
from nfr_review.collectors.terraform import TerraformCollector
from nfr_review.config import Config
from nfr_review.detect import detect_technologies
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.helm_chart_metadata import HelmChartMetadataRule
from nfr_review.rules.helm_values_validation import HelmValuesValidationRule
from nfr_review.rules.istio_mtls_strict import IstioMtlsStrictRule
from nfr_review.rules.otel_exporter import OTelExporterConfigRule
from nfr_review.rules.skaffold_build import SkaffoldBuildConfigRule
from nfr_review.rules.terraform_state_backend import TerraformStateBackendRule

FIXTURES = Path(__file__).parent / "fixtures"
MIXED_TECH = FIXTURES / "mixed-tech-repo"

EXPECTED_COLLECTORS = {"helm", "terraform", "istio", "otel", "skaffold"}
EXPECTED_RULE_IDS = {
    "helm-chart-metadata",
    "helm-values-validation",
    "istio-mtls-strict",
    "otel-exporter-config",
    "skaffold-build-config",
    "terraform-state-backend",
}


def _mixed_registries() -> tuple[Registry, Registry]:
    """Build registries with all 5 M003 collectors and one rule per technology."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("helm", HelmCollector())
    cregistry.register("terraform", TerraformCollector())
    cregistry.register("istio", IstioCollector())
    cregistry.register("otel", OTelCollector())
    cregistry.register("skaffold", SkaffoldCollector())

    rregistry.register("helm-chart-metadata", HelmChartMetadataRule())
    rregistry.register("helm-values-validation", HelmValuesValidationRule())
    rregistry.register("istio-mtls-strict", IstioMtlsStrictRule())
    rregistry.register("otel-exporter-config", OTelExporterConfigRule())
    rregistry.register("skaffold-build-config", SkaffoldBuildConfigRule())
    rregistry.register("terraform-state-backend", TerraformStateBackendRule())

    return cregistry, rregistry


class TestCrossCollectorIntegration:
    """Run Engine against mixed-tech fixture — all 5 collectors produce findings."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _mixed_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(
            tech={
                "helm": True,
                "terraform": True,
                "istio": True,
                "otel": True,
                "skaffold": True,
            }
        )
        return engine.run(target=MIXED_TECH, config=cfg)

    def test_all_five_collectors_produce_findings(self, result: RunResult) -> None:
        collector_names = {f.collector_name for f in result.findings}
        assert EXPECTED_COLLECTORS <= collector_names

    def test_at_least_five_distinct_rule_ids(self, result: RunResult) -> None:
        rule_ids = {f.rule_id for f in result.findings}
        assert len(rule_ids) >= 5

    def test_engine_returns_successfully(self, result: RunResult) -> None:
        assert result is not None
        assert result.run_metadata is not None
        assert len(result.warnings) == 0

    def test_each_finding_has_non_green_severity(self, result: RunResult) -> None:
        for rule_id in EXPECTED_RULE_IDS:
            tech_findings = [f for f in result.findings if f.rule_id == rule_id]
            assert len(tech_findings) >= 1, f"no findings for {rule_id}"
            assert any(f.rag != "green" for f in tech_findings), (
                f"all findings green for {rule_id}"
            )


class TestMixedTechDetection:
    """detect_technologies() identifies all 5 M003 techs from the mixed fixture."""

    def test_all_five_tech_keys_detected(self) -> None:
        tech = detect_technologies(MIXED_TECH)
        for key in ("helm", "terraform", "istio", "otel", "skaffold"):
            assert tech.get(key) is True, f"tech[{key!r}] not detected"


class TestNoCrossContamination:
    """Each rule's findings only reference evidence from its own collector."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _mixed_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(
            tech={
                "helm": True,
                "terraform": True,
                "istio": True,
                "otel": True,
                "skaffold": True,
            }
        )
        return engine.run(target=MIXED_TECH, config=cfg)

    def test_helm_findings_use_helm_collector(self, result: RunResult) -> None:
        for f in result.findings:
            if f.rule_id.startswith("helm-"):
                assert f.collector_name == "helm", (
                    f"helm rule used collector {f.collector_name}"
                )

    def test_terraform_findings_use_terraform_collector(self, result: RunResult) -> None:
        for f in result.findings:
            if f.rule_id.startswith("terraform-"):
                assert f.collector_name == "terraform", (
                    f"terraform rule used collector {f.collector_name}"
                )

    def test_istio_findings_use_istio_collector(self, result: RunResult) -> None:
        for f in result.findings:
            if f.rule_id.startswith("istio-"):
                assert f.collector_name == "istio", (
                    f"istio rule used collector {f.collector_name}"
                )

    def test_otel_findings_use_otel_collector(self, result: RunResult) -> None:
        for f in result.findings:
            if f.rule_id.startswith("otel-"):
                assert f.collector_name == "otel", (
                    f"otel rule used collector {f.collector_name}"
                )

    def test_skaffold_findings_use_skaffold_collector(self, result: RunResult) -> None:
        for f in result.findings:
            if f.rule_id.startswith("skaffold-"):
                assert f.collector_name == "skaffold", (
                    f"skaffold rule used collector {f.collector_name}"
                )
