"""S02 integration tests — Engine orchestrates all collectors and rules end-to-end."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.java_ast import JavaAstCollector
from nfr_review.collectors.k8s_manifest import K8sManifestCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.models import Evidence, RuleResult
from nfr_review.registry import Registry, collector_registry, rule_registry
from nfr_review.rules.java_exception import ExceptionHandlingAntipatternRule
from nfr_review.rules.java_health import HealthEndpointMissingRule
from nfr_review.rules.java_resilience import ResilienceAnnotationMissingRule
from nfr_review.rules.java_thread_pool import ThreadPoolMisconfigurationRule
from nfr_review.rules.k8s_network import NetworkPolicyMissingRule
from nfr_review.rules.k8s_probes import ProbesMissingRule
from nfr_review.rules.k8s_resources import ResourceLimitsMissingRule
from nfr_review.rules.k8s_security import NonRootContainerViolationRule
from nfr_review.rules.sample import ReadmeExistsRule

FIXTURE = Path(__file__).parent / "fixtures" / "java-sample-repo"

ALL_RULE_IDS = {
    "sample-readme-exists",
    "health-endpoint-missing",
    "exception-handling-antipattern",
    "resilience-annotation-missing",
    "thread-pool-misconfiguration",
    "resource-limits-missing",
    "probes-missing",
    "non-root-container-violation",
    "network-policy-missing",
}

ALL_COLLECTOR_NAMES = {"repo-structure", "java-ast", "k8s-manifest"}


def _fresh_registries() -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("java-ast", JavaAstCollector())
    cregistry.register("k8s-manifest", K8sManifestCollector())

    rregistry.register("sample-readme-exists", ReadmeExistsRule())
    rregistry.register("health-endpoint-missing", HealthEndpointMissingRule())
    rregistry.register(
        "exception-handling-antipattern", ExceptionHandlingAntipatternRule()
    )
    rregistry.register(
        "resilience-annotation-missing", ResilienceAnnotationMissingRule()
    )
    rregistry.register(
        "thread-pool-misconfiguration", ThreadPoolMisconfigurationRule()
    )
    rregistry.register("resource-limits-missing", ResourceLimitsMissingRule())
    rregistry.register("probes-missing", ProbesMissingRule())
    rregistry.register(
        "non-root-container-violation", NonRootContainerViolationRule()
    )
    rregistry.register("network-policy-missing", NetworkPolicyMissingRule())

    return cregistry, rregistry


# ---------------------------------------------------------------------------
# Engine integration — full pipeline against java-sample-repo fixture
# ---------------------------------------------------------------------------


class TestEngineIntegration:
    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _fresh_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        return engine.run(target=FIXTURE, config=Config())

    def test_evidence_from_all_collectors(self, result: RunResult) -> None:
        collector_names = {e.collector_name for e in self._all_evidence(result)}
        assert ALL_COLLECTOR_NAMES <= collector_names

    def test_java_rule_findings_present(self, result: RunResult) -> None:
        java_rule_ids = {
            "health-endpoint-missing",
            "exception-handling-antipattern",
            "resilience-annotation-missing",
            "thread-pool-misconfiguration",
        }
        finding_rule_ids = {f.rule_id for f in result.findings}
        assert java_rule_ids <= finding_rule_ids

    def test_k8s_rule_findings_present(self, result: RunResult) -> None:
        k8s_rule_ids = {
            "resource-limits-missing",
            "probes-missing",
            "non-root-container-violation",
            "network-policy-missing",
        }
        finding_rule_ids = {f.rule_id for f in result.findings}
        assert k8s_rule_ids <= finding_rule_ids

    def test_no_warnings(self, result: RunResult) -> None:
        assert result.warnings == []

    def test_run_metadata_rules_run(self, result: RunResult) -> None:
        assert set(result.run_metadata.rules_run) == ALL_RULE_IDS

    def test_run_metadata_collector_versions(self, result: RunResult) -> None:
        assert set(result.run_metadata.collector_versions.keys()) == ALL_COLLECTOR_NAMES
        for v in result.run_metadata.collector_versions.values():
            assert v == "0.1.0"

    def test_run_metadata_no_rules_skipped(self, result: RunResult) -> None:
        assert result.run_metadata.rules_skipped == []

    def _all_evidence(self, result: RunResult) -> list[Evidence]:
        """Collect evidence by re-running collectors (RunResult doesn't store raw evidence)."""
        cregistry, _ = _fresh_registries()
        evidence: list[Evidence] = []
        for c in cregistry.all():
            evidence.extend(c.collect(FIXTURE, Config()))
        return evidence


# ---------------------------------------------------------------------------
# Fault isolation — a failing collector doesn't crash the run
# ---------------------------------------------------------------------------


class _FailingCollector:
    name = "failing-collector"
    version = "0.0.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        raise RuntimeError("intentional boom")


class TestFaultIsolation:
    def test_failing_collector_reported_in_warnings(self) -> None:
        cregistry, rregistry = _fresh_registries()
        cregistry.register("failing-collector", _FailingCollector())
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=FIXTURE, config=Config())

        assert any("failing-collector" in w for w in result.warnings)
        assert set(result.run_metadata.rules_run) == ALL_RULE_IDS
        assert result.run_metadata.rules_skipped == []

    def test_rule_requiring_failed_collector_is_skipped(self) -> None:
        cregistry, rregistry = _fresh_registries()
        cregistry.register("failing-collector", _FailingCollector())

        class _NeedsFailingRule:
            id = "needs-failing"
            band = 1
            required_collectors = ["failing-collector"]

            def evaluate(
                self, evidence: list[Evidence], context: Any
            ) -> RuleResult:
                return RuleResult(rule_id=self.id)

        rregistry.register("needs-failing", _NeedsFailingRule())
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=FIXTURE, config=Config())

        skipped_ids = {e["rule_id"] for e in result.run_metadata.rules_skipped}
        assert "needs-failing" in skipped_ids
        assert "needs-failing" not in result.run_metadata.rules_run


# ---------------------------------------------------------------------------
# Auto-registration — importing packages populates global singletons
# ---------------------------------------------------------------------------


class TestAutoRegistration:
    def test_collector_registry_has_3_entries(self) -> None:
        import importlib

        import nfr_review.collectors

        importlib.reload(nfr_review.collectors.repo_structure)
        importlib.reload(nfr_review.collectors.java_ast)
        importlib.reload(nfr_review.collectors.k8s_manifest)

        assert len(collector_registry) >= 3
        assert ALL_COLLECTOR_NAMES <= set(collector_registry.ids())

    def test_rule_registry_has_9_entries(self) -> None:
        import importlib

        import nfr_review.rules

        importlib.reload(nfr_review.rules.sample)
        importlib.reload(nfr_review.rules.java_health)
        importlib.reload(nfr_review.rules.java_exception)
        importlib.reload(nfr_review.rules.java_resilience)
        importlib.reload(nfr_review.rules.java_thread_pool)
        importlib.reload(nfr_review.rules.k8s_resources)
        importlib.reload(nfr_review.rules.k8s_probes)
        importlib.reload(nfr_review.rules.k8s_security)
        importlib.reload(nfr_review.rules.k8s_network)

        assert len(rule_registry) >= 9
        assert ALL_RULE_IDS <= set(rule_registry.ids())
