"""S03 integration tests — tech filtering, Spring/APIM/ADR/CI collectors+rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.adr import AdrCollector
from nfr_review.collectors.apim_policy import ApimPolicyCollector
from nfr_review.collectors.ci_artifact import CiArtifactCollector
from nfr_review.collectors.java_ast import JavaAstCollector
from nfr_review.collectors.k8s_manifest import K8sManifestCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.collectors.spring_config import SpringConfigCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry, rule_registry
from nfr_review.rules.adr_lifecycle import AdrLifecycleGapRule
from nfr_review.rules.apim_auth import ApimAuthPolicyMissingRule
from nfr_review.rules.apim_backend_url import ApimHardcodedBackendUrlRule
from nfr_review.rules.apim_rate_limit import ApimRateLimitMissingRule
from nfr_review.rules.ci_security_scan import CiSecurityScanMissingRule
from nfr_review.rules.ci_test_stage import CiTestStageMissingRule
from nfr_review.rules.java_exception import ExceptionHandlingAntipatternRule
from nfr_review.rules.java_health import HealthEndpointMissingRule
from nfr_review.rules.java_resilience import ResilienceAnnotationMissingRule
from nfr_review.rules.java_thread_pool import ThreadPoolMisconfigurationRule
from nfr_review.rules.k8s_network import NetworkPolicyMissingRule
from nfr_review.rules.k8s_probes import ProbesMissingRule
from nfr_review.rules.k8s_resources import ResourceLimitsMissingRule
from nfr_review.rules.k8s_security import NonRootContainerViolationRule
from nfr_review.rules.sample import ReadmeExistsRule
from nfr_review.rules.spring_actuator import ActuatorExposureRiskRule
from nfr_review.rules.spring_logging import LoggingConfigMissingRule
from nfr_review.rules.spring_profile import SpringProfileMisconfigurationRule

FIXTURES = Path(__file__).parent / "fixtures"
JAVA_REPO = FIXTURES / "java-sample-repo"
APIM_REPO = FIXTURES / "apim-sample-repo"
ADR_REPO = FIXTURES / "adr-sample-repo"
CI_REPO = FIXTURES / "ci-sample-repo"

SPRING_RULE_IDS = {
    "actuator-exposure-risk",
    "logging-config-missing",
    "spring-profile-misconfiguration",
}
APIM_RULE_IDS = {
    "apim-rate-limit-missing",
    "apim-auth-policy-missing",
    "apim-hardcoded-backend-url",
}
ADR_CI_RULE_IDS = {
    "adr-lifecycle-gap",
    "ci-security-scan-missing",
    "ci-test-stage-missing",
}

ALL_S03_RULE_IDS = SPRING_RULE_IDS | APIM_RULE_IDS | ADR_CI_RULE_IDS


def _full_registries() -> tuple[Registry, Registry]:
    """Build registries with all 7 collectors and 18 rules."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("java-ast", JavaAstCollector())
    cregistry.register("k8s-manifest", K8sManifestCollector())
    cregistry.register("spring-config", SpringConfigCollector())
    cregistry.register("apim-policy", ApimPolicyCollector())
    cregistry.register("adr", AdrCollector())
    cregistry.register("ci-artifact", CiArtifactCollector())

    rregistry.register("sample-readme-exists", ReadmeExistsRule())
    rregistry.register("health-endpoint-missing", HealthEndpointMissingRule())
    rregistry.register("exception-handling-antipattern", ExceptionHandlingAntipatternRule())
    rregistry.register("resilience-annotation-missing", ResilienceAnnotationMissingRule())
    rregistry.register("thread-pool-misconfiguration", ThreadPoolMisconfigurationRule())
    rregistry.register("resource-limits-missing", ResourceLimitsMissingRule())
    rregistry.register("probes-missing", ProbesMissingRule())
    rregistry.register("non-root-container-violation", NonRootContainerViolationRule())
    rregistry.register("network-policy-missing", NetworkPolicyMissingRule())
    rregistry.register("actuator-exposure-risk", ActuatorExposureRiskRule())
    rregistry.register("logging-config-missing", LoggingConfigMissingRule())
    rregistry.register("spring-profile-misconfiguration", SpringProfileMisconfigurationRule())
    rregistry.register("apim-rate-limit-missing", ApimRateLimitMissingRule())
    rregistry.register("apim-auth-policy-missing", ApimAuthPolicyMissingRule())
    rregistry.register("apim-hardcoded-backend-url", ApimHardcodedBackendUrlRule())
    rregistry.register("adr-lifecycle-gap", AdrLifecycleGapRule())
    rregistry.register("ci-security-scan-missing", CiSecurityScanMissingRule())
    rregistry.register("ci-test-stage-missing", CiTestStageMissingRule())

    return cregistry, rregistry


class TestSpringTechFiltering:
    """Spring rules fire when spring_boot declared, APIM rules skipped."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _full_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"spring_boot": True, "apim": False})
        return engine.run(target=JAVA_REPO, config=cfg)

    def test_spring_rules_fire(self, result: RunResult) -> None:
        finding_rule_ids = {f.rule_id for f in result.findings}
        assert SPRING_RULE_IDS <= finding_rule_ids

    def test_apim_rules_skipped_with_reason(self, result: RunResult) -> None:
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in APIM_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: apim" in skipped[rule_id]

    def test_adr_ci_rules_not_tech_skipped(self, result: RunResult) -> None:
        tech_skipped = {
            e["rule_id"]
            for e in result.run_metadata.rules_skipped
            if "tech not declared" in e["reason"]
        }
        for rule_id in ADR_CI_RULE_IDS:
            assert rule_id not in tech_skipped


class TestApimTechFiltering:
    """APIM rules fire when apim declared."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _full_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"apim": True})
        return engine.run(target=APIM_REPO, config=cfg)

    def test_apim_rules_fire(self, result: RunResult) -> None:
        finding_rule_ids = {f.rule_id for f in result.findings}
        assert APIM_RULE_IDS <= finding_rule_ids

    def test_spring_rules_skipped(self, result: RunResult) -> None:
        skipped_ids = {e["rule_id"] for e in result.run_metadata.rules_skipped}
        assert SPRING_RULE_IDS <= skipped_ids


class TestEmptyTechSkipsAll:
    """With empty tech dict, all tech-gated rules are skipped."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _full_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        return engine.run(target=JAVA_REPO, config=cfg)

    def test_all_spring_rules_skipped(self, result: RunResult) -> None:
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in SPRING_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: spring_boot" in skipped[rule_id]

    def test_all_apim_rules_skipped(self, result: RunResult) -> None:
        skipped = {e["rule_id"]: e["reason"] for e in result.run_metadata.rules_skipped}
        for rule_id in APIM_RULE_IDS:
            assert rule_id in skipped
            assert "tech not declared: apim" in skipped[rule_id]

    def test_non_tech_gated_rules_still_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert "sample-readme-exists" in run_set


class TestRuleRegistryCount:
    """Verify all 18 rules are importable and registered."""

    def test_registry_has_18_rules(self) -> None:
        import importlib

        import nfr_review.rules.adr_lifecycle
        import nfr_review.rules.apim_auth
        import nfr_review.rules.apim_backend_url
        import nfr_review.rules.apim_rate_limit
        import nfr_review.rules.ci_security_scan
        import nfr_review.rules.ci_test_stage
        import nfr_review.rules.spring_actuator
        import nfr_review.rules.spring_logging
        import nfr_review.rules.spring_profile

        importlib.reload(nfr_review.rules.adr_lifecycle)
        importlib.reload(nfr_review.rules.apim_auth)
        importlib.reload(nfr_review.rules.apim_backend_url)
        importlib.reload(nfr_review.rules.apim_rate_limit)
        importlib.reload(nfr_review.rules.ci_security_scan)
        importlib.reload(nfr_review.rules.ci_test_stage)
        importlib.reload(nfr_review.rules.spring_actuator)
        importlib.reload(nfr_review.rules.spring_logging)
        importlib.reload(nfr_review.rules.spring_profile)

        assert len(rule_registry) >= 18

    def test_all_s03_rule_ids_registered(self) -> None:
        registered = set(rule_registry.ids())
        assert ALL_S03_RULE_IDS <= registered


class TestTechSkipReasonsInMetadata:
    """Verify tech-skip reasons appear in RunMetadata.rules_skipped."""

    def test_skip_reasons_have_correct_format(self) -> None:
        cregistry, rregistry = _full_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={"spring_boot": True})
        result = engine.run(target=JAVA_REPO, config=cfg)

        apim_skipped = [
            e for e in result.run_metadata.rules_skipped if e["rule_id"] in APIM_RULE_IDS
        ]
        assert len(apim_skipped) == 3
        for entry in apim_skipped:
            assert entry["reason"] == "tech not declared: apim"


class TestAdrCiRulesNoTechGating:
    """ADR/CI rules run regardless of tech config (no required_tech)."""

    def test_adr_rules_run_on_adr_repo(self) -> None:
        cregistry, rregistry = _full_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        result = engine.run(target=ADR_REPO, config=cfg)

        run_set = set(result.run_metadata.rules_run)
        assert "adr-lifecycle-gap" in run_set

    def test_ci_rules_run_on_ci_repo(self) -> None:
        cregistry, rregistry = _full_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        result = engine.run(target=CI_REPO, config=cfg)

        run_set = set(result.run_metadata.rules_run)
        assert "ci-security-scan-missing" in run_set
        assert "ci-test-stage-missing" in run_set
