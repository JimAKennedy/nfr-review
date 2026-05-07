"""Istio integration tests — full Engine pipeline with IstioCollector."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.istio import IstioCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.istio_circuit_breaker import IstioCircuitBreakerRule
from nfr_review.rules.istio_mtls_strict import IstioMtlsStrictRule
from nfr_review.rules.istio_traffic_policy import IstioTrafficPolicyRule
from nfr_review.rules.sample import ReadmeExistsRule

FIXTURES = Path(__file__).parent / "fixtures"
ISTIO_SAMPLE = FIXTURES / "istio-sample-repo"
ISTIO_GOOD = FIXTURES / "istio-good-repo"

ISTIO_RULE_IDS = {
    "istio-mtls-strict",
    "istio-traffic-policy",
    "istio-circuit-breaker",
}


def _istio_registries() -> tuple[Registry, Registry]:
    """Build registries with IstioCollector + 3 Istio rules (plus baseline)."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("istio", IstioCollector())

    rregistry.register("sample-readme-exists", ReadmeExistsRule())
    rregistry.register("istio-mtls-strict", IstioMtlsStrictRule())
    rregistry.register("istio-traffic-policy", IstioTrafficPolicyRule())
    rregistry.register("istio-circuit-breaker", IstioCircuitBreakerRule())

    return cregistry, rregistry


class TestIstioPipelineFindings:
    """Full collector->evidence->rules->findings pipeline against istio-sample-repo."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _istio_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"istio": True})
        return engine.run(target=ISTIO_SAMPLE, config=cfg)

    def test_mtls_rule_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "istio-mtls-strict"]
        assert len(findings) >= 1
        assert any(
            "mtls" in f.summary.lower() or "strict" in f.summary.lower() for f in findings
        )

    def test_traffic_policy_rule_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "istio-traffic-policy"]
        assert len(findings) >= 1
        assert any(
            "traffic" in f.summary.lower() or "policy" in f.summary.lower() for f in findings
        )

    def test_circuit_breaker_rule_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "istio-circuit-breaker"]
        assert len(findings) >= 1
        assert any(
            "circuit" in f.summary.lower() or "outlier" in f.summary.lower() for f in findings
        )

    def test_all_three_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert ISTIO_RULE_IDS <= run_set

    def test_run_metadata_has_istio_collector_version(self, result: RunResult) -> None:
        assert "istio" in result.run_metadata.collector_versions
        assert result.run_metadata.collector_versions["istio"] == "0.1.0"


class TestIstioTechGating:
    """Istio rules are skipped when tech={"istio": False}."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _istio_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"istio": False})
        return engine.run(target=ISTIO_SAMPLE, config=cfg)

    def test_all_istio_rules_skipped(self, result: RunResult) -> None:
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in ISTIO_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: istio" in skipped[rule_id]

    def test_no_istio_findings_produced(self, result: RunResult) -> None:
        istio_findings = [f for f in result.findings if f.rule_id in ISTIO_RULE_IDS]
        assert len(istio_findings) == 0

    def test_non_istio_rules_still_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert "sample-readme-exists" in run_set


class TestIstioGoodRepo:
    """Good repo produces green/clean findings."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _istio_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"istio": True})
        return engine.run(target=ISTIO_GOOD, config=cfg)

    def test_all_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert ISTIO_RULE_IDS <= run_set

    def test_all_findings_green(self, result: RunResult) -> None:
        istio_findings = [f for f in result.findings if f.rule_id in ISTIO_RULE_IDS]
        assert len(istio_findings) >= 3
        assert all(f.rag == "green" for f in istio_findings)

    def test_no_amber_or_red_findings(self, result: RunResult) -> None:
        bad_findings = [
            f
            for f in result.findings
            if f.rule_id in ISTIO_RULE_IDS and f.rag in ("amber", "red")
        ]
        assert len(bad_findings) == 0


class TestIstioEmptyTechSkipsAll:
    """With empty tech dict, all Istio rules are tech-skipped."""

    def test_istio_rules_skipped_with_empty_tech(self) -> None:
        cregistry, rregistry = _istio_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        result = engine.run(target=ISTIO_SAMPLE, config=cfg)

        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in ISTIO_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: istio" in skipped[rule_id]
