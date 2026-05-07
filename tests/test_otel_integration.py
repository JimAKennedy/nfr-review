"""OTel integration tests — full Engine pipeline with OTelCollector."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.otel import OTelCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.otel_exporter import OTelExporterConfigRule
from nfr_review.rules.otel_pipeline import OTelPipelineCompletenessRule
from nfr_review.rules.otel_sampling import OTelSamplingRule
from nfr_review.rules.sample import ReadmeExistsRule

FIXTURES = Path(__file__).parent / "fixtures"
OTEL_SAMPLE = FIXTURES / "otel-sample-repo"
OTEL_GOOD = FIXTURES / "otel-good-repo"

OTEL_RULE_IDS = {
    "otel-exporter-config",
    "otel-pipeline-completeness",
    "otel-sampling",
}


def _otel_registries() -> tuple[Registry, Registry]:
    """Build registries with OTelCollector + 3 OTel rules (plus baseline)."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("otel", OTelCollector())

    rregistry.register("sample-readme-exists", ReadmeExistsRule())
    rregistry.register("otel-exporter-config", OTelExporterConfigRule())
    rregistry.register("otel-pipeline-completeness", OTelPipelineCompletenessRule())
    rregistry.register("otel-sampling", OTelSamplingRule())

    return cregistry, rregistry


class TestOTelPipelineFindings:
    """Full collector->evidence->rules->findings pipeline against otel-sample-repo."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _otel_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"otel": True})
        return engine.run(target=OTEL_SAMPLE, config=cfg)

    def test_exporter_rule_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "otel-exporter-config"]
        assert len(findings) >= 1
        assert any(
            "exporter" in f.summary.lower() or "logging" in f.summary.lower() for f in findings
        )

    def test_pipeline_rule_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "otel-pipeline-completeness"]
        assert len(findings) >= 1
        assert any(
            "pipeline" in f.summary.lower() or "signal" in f.summary.lower() for f in findings
        )

    def test_sampling_rule_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "otel-sampling"]
        assert len(findings) >= 1
        assert any(
            "sampling" in f.summary.lower() or "rate" in f.summary.lower() for f in findings
        )

    def test_all_three_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert OTEL_RULE_IDS <= run_set

    def test_finding_metadata_complete(self, result: RunResult) -> None:
        otel_findings = [f for f in result.findings if f.rule_id in OTEL_RULE_IDS]
        for f in otel_findings:
            assert f.rule_id, "missing rule_id"
            assert f.rag, "missing rag"
            assert f.severity, "missing severity"
            assert f.evidence_locator, "missing evidence_locator"
            assert f.recommendation, "missing recommendation"

    def test_run_metadata_has_otel_collector_version(self, result: RunResult) -> None:
        assert "otel" in result.run_metadata.collector_versions
        assert result.run_metadata.collector_versions["otel"] == "0.1.0"


class TestOTelTechGating:
    """OTel rules are skipped when tech={"otel": False}."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _otel_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"otel": False})
        return engine.run(target=OTEL_SAMPLE, config=cfg)

    def test_all_otel_rules_skipped(self, result: RunResult) -> None:
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in OTEL_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: otel" in skipped[rule_id]

    def test_no_otel_findings_produced(self, result: RunResult) -> None:
        otel_findings = [f for f in result.findings if f.rule_id in OTEL_RULE_IDS]
        assert len(otel_findings) == 0

    def test_non_otel_rules_still_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert "sample-readme-exists" in run_set


class TestOTelGoodRepo:
    """Good repo produces green/clean findings."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _otel_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"otel": True})
        return engine.run(target=OTEL_GOOD, config=cfg)

    def test_all_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert OTEL_RULE_IDS <= run_set

    def test_all_findings_green(self, result: RunResult) -> None:
        otel_findings = [f for f in result.findings if f.rule_id in OTEL_RULE_IDS]
        assert len(otel_findings) >= 3
        assert all(f.rag == "green" for f in otel_findings)

    def test_no_amber_or_red_findings(self, result: RunResult) -> None:
        bad_findings = [
            f
            for f in result.findings
            if f.rule_id in OTEL_RULE_IDS and f.rag in ("amber", "red")
        ]
        assert len(bad_findings) == 0


class TestOTelEmptyTechSkipsAll:
    """With empty tech dict, all OTel rules are tech-skipped."""

    def test_otel_rules_skipped_with_empty_tech(self) -> None:
        cregistry, rregistry = _otel_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        result = engine.run(target=OTEL_SAMPLE, config=cfg)

        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in OTEL_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: otel" in skipped[rule_id]
