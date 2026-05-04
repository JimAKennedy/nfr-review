"""S04 integration tests — Band 2 registration, graceful degradation, LLM mocking."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

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
from nfr_review.llm_client import ClaudeClient, LlmUnavailableError
from nfr_review.registry import Registry, rule_registry
from nfr_review.rules.adr_drift import ArchitecturalDriftFromAdrRule
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
from nfr_review.rules.pii_logging import PiiInLogStatementsRule
from nfr_review.rules.sample import ReadmeExistsRule
from nfr_review.rules.spring_actuator import ActuatorExposureRiskRule
from nfr_review.rules.spring_logging import LoggingConfigMissingRule
from nfr_review.rules.spring_profile import SpringProfileMisconfigurationRule

FIXTURES = Path(__file__).parent / "fixtures"
JAVA_REPO = FIXTURES / "java-sample-repo"
ADR_REPO = FIXTURES / "adr-sample-repo"

BAND2_RULE_IDS = {"pii-in-log-statements", "architectural-drift-from-adr"}


def _unavailable_client() -> ClaudeClient:
    client = MagicMock(spec=ClaudeClient)
    client.available = False
    client.analyze.side_effect = LlmUnavailableError("no key")
    return client


def _confirming_pii_client(verdicts: list[dict]) -> ClaudeClient:
    client = MagicMock(spec=ClaudeClient)
    client.available = True
    client.analyze.return_value = json.dumps(verdicts)
    return client


def _confirming_adr_client(drifts: list[dict], summary: str = "test") -> ClaudeClient:
    client = MagicMock(spec=ClaudeClient)
    client.available = True
    client.analyze.return_value = json.dumps({"drifts": drifts, "summary": summary})
    return client


def _full_registries(
    *,
    pii_llm: ClaudeClient | None = None,
    adr_drift_llm: ClaudeClient | None = None,
) -> tuple[Registry, Registry]:
    """Build registries with all 7 collectors and 20 rules."""
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
    rregistry.register(
        "pii-in-log-statements",
        PiiInLogStatementsRule(llm_client=pii_llm or _unavailable_client()),
    )
    rregistry.register(
        "architectural-drift-from-adr",
        ArchitecturalDriftFromAdrRule(
            llm_client=adr_drift_llm or _unavailable_client(),
        ),
    )

    return cregistry, rregistry


class TestTwentyRulesRegistered:
    """Verify all 20 rules (18 Band 1 + 2 Band 2) are registered."""

    def _ensure_all_registered(self) -> None:
        import importlib

        import nfr_review.rules.adr_drift
        import nfr_review.rules.adr_lifecycle
        import nfr_review.rules.apim_auth
        import nfr_review.rules.apim_backend_url
        import nfr_review.rules.apim_rate_limit
        import nfr_review.rules.ci_security_scan
        import nfr_review.rules.ci_test_stage
        import nfr_review.rules.pii_logging
        import nfr_review.rules.spring_actuator
        import nfr_review.rules.spring_logging
        import nfr_review.rules.spring_profile

        importlib.reload(nfr_review.rules.adr_drift)
        importlib.reload(nfr_review.rules.adr_lifecycle)
        importlib.reload(nfr_review.rules.apim_auth)
        importlib.reload(nfr_review.rules.apim_backend_url)
        importlib.reload(nfr_review.rules.apim_rate_limit)
        importlib.reload(nfr_review.rules.ci_security_scan)
        importlib.reload(nfr_review.rules.ci_test_stage)
        importlib.reload(nfr_review.rules.pii_logging)
        importlib.reload(nfr_review.rules.spring_actuator)
        importlib.reload(nfr_review.rules.spring_logging)
        importlib.reload(nfr_review.rules.spring_profile)

    def test_registry_has_20_rules(self) -> None:
        self._ensure_all_registered()
        assert len(rule_registry) >= 20

    def test_band2_ids_in_registry(self) -> None:
        self._ensure_all_registered()
        registered = set(rule_registry.ids())
        assert registered >= BAND2_RULE_IDS


class TestListRulesShowsTwenty:
    def test_list_rules_shows_twenty(self) -> None:
        venv_bin = Path(sys.executable).parent
        result = subprocess.run(
            [str(venv_bin / "nfr-review"), "list-rules"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
        assert len(lines) == 20


class TestBand2SkipWithoutApiKey:
    """Band 2 rules skip gracefully when ANTHROPIC_API_KEY is missing."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _full_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        return engine.run(target=JAVA_REPO, config=cfg)

    def test_both_band2_rules_in_skipped(self, result: RunResult) -> None:
        skipped_ids = {e["rule_id"] for e in result.run_metadata.rules_skipped}
        assert skipped_ids >= BAND2_RULE_IDS

    def test_band2_skip_reasons_informative(self, result: RunResult) -> None:
        skipped = {
            e["rule_id"]: e["reason"]
            for e in result.run_metadata.rules_skipped
            if e["rule_id"] in BAND2_RULE_IDS
        }
        for rule_id, reason in skipped.items():
            assert reason, f"skip reason empty for {rule_id}"
            assert len(reason) > 10, f"skip reason too short for {rule_id}"


class TestBand2PiiRuleWithMock:
    """PII rule produces findings when LLM is mocked."""

    @pytest.fixture()
    def result(self) -> RunResult:
        pii_llm = _confirming_pii_client(
            [{"index": 0, "is_pii": True, "reason": "SSN logged"}]
        )
        cregistry: Registry = Registry("collector")
        rregistry: Registry = Registry("rule")
        cregistry.register("java-ast", JavaAstCollector())
        rregistry.register(
            "pii-in-log-statements",
            PiiInLogStatementsRule(llm_client=pii_llm),
        )

        pii_fixture = FIXTURES / "java-pii-sample"
        pii_fixture.mkdir(exist_ok=True)
        src_dir = pii_fixture / "src" / "main" / "java" / "com" / "example"
        src_dir.mkdir(parents=True, exist_ok=True)
        java_file = src_dir / "UserService.java"
        java_file.write_text(
            "package com.example;\n"
            "import org.slf4j.Logger;\n"
            "import org.slf4j.LoggerFactory;\n"
            "public class UserService {\n"
            "    private static final Logger logger ="
            " LoggerFactory.getLogger(UserService.class);\n"
            "    public void processUser(String ssn) {\n"
            '        logger.info("Processing SSN: 123-45-6789", ssn);\n'
            "    }\n"
            "}\n"
        )

        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        return engine.run(target=pii_fixture, config=cfg)

    def test_pii_findings_produced(self, result: RunResult) -> None:
        pii_findings = [f for f in result.findings if f.rule_id == "pii-in-log-statements"]
        assert len(pii_findings) >= 1

    def test_pii_finding_has_high_confidence(self, result: RunResult) -> None:
        pii_findings = [f for f in result.findings if f.rule_id == "pii-in-log-statements"]
        assert any(f.confidence == 0.85 for f in pii_findings)


class TestBand2AdrDriftRuleWithMock:
    """ADR drift rule produces findings when LLM is mocked."""

    @pytest.fixture()
    def result(self) -> RunResult:
        adr_drift_llm = _confirming_adr_client(
            drifts=[
                {
                    "adr_title": "Use Spring Boot",
                    "violation": "Non-Spring framework detected",
                    "severity": "high",
                }
            ],
            summary="Drift detected",
        )
        cregistry: Registry = Registry("collector")
        rregistry: Registry = Registry("rule")
        cregistry.register("adr", AdrCollector())
        cregistry.register("java-ast", JavaAstCollector())
        rregistry.register(
            "architectural-drift-from-adr",
            ArchitecturalDriftFromAdrRule(llm_client=adr_drift_llm),
        )

        combined = FIXTURES / "adr-java-combined"
        combined.mkdir(exist_ok=True)

        adr_dir = combined / "docs" / "adr"
        adr_dir.mkdir(parents=True, exist_ok=True)
        (adr_dir / "0001-use-spring-boot.md").write_text(
            "---\ntitle: Use Spring Boot\nstatus: accepted\ndate: 2024-01-01\n---\n"
            "# Use Spring Boot\n\nWe will use Spring Boot as our framework.\n"
        )

        src_dir = combined / "src" / "main" / "java" / "com" / "example"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "App.java").write_text(
            "package com.example;\n"
            "import org.springframework.boot.SpringApplication;\n"
            "public class App {\n"
            "    public static void main(String[] args) {\n"
            "        SpringApplication.run(App.class, args);\n"
            "    }\n"
            "}\n"
        )

        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        return engine.run(target=combined, config=cfg)

    def test_drift_findings_produced(self, result: RunResult) -> None:
        drift_findings = [
            f for f in result.findings if f.rule_id == "architectural-drift-from-adr"
        ]
        assert len(drift_findings) >= 1

    def test_drift_finding_is_red(self, result: RunResult) -> None:
        drift_findings = [
            f for f in result.findings if f.rule_id == "architectural-drift-from-adr"
        ]
        assert any(f.rag == "red" for f in drift_findings)


class TestEngineFaultIsolationLlmError:
    """Engine catches LLM errors; Band 2 rule appears skipped, other rules still run."""

    def test_llm_exception_becomes_skipped(self) -> None:
        failing_llm = MagicMock(spec=ClaudeClient)
        failing_llm.available = True
        failing_llm.analyze.side_effect = RuntimeError("API exploded")

        cregistry: Registry = Registry("collector")
        rregistry: Registry = Registry("rule")
        cregistry.register("repo-structure", RepoStructureCollector())
        cregistry.register("adr", AdrCollector())
        cregistry.register("java-ast", JavaAstCollector())
        rregistry.register("sample-readme-exists", ReadmeExistsRule())
        rregistry.register(
            "architectural-drift-from-adr",
            ArchitecturalDriftFromAdrRule(llm_client=failing_llm),
        )

        combined = FIXTURES / "adr-java-combined"
        combined.mkdir(exist_ok=True)
        adr_dir = combined / "docs" / "adr"
        adr_dir.mkdir(parents=True, exist_ok=True)
        (adr_dir / "0001-use-spring-boot.md").write_text(
            "---\ntitle: Use Spring Boot\nstatus: accepted\ndate: 2024-01-01\n---\n"
            "# Use Spring Boot\n\nWe will use Spring Boot.\n"
        )
        src_dir = combined / "src" / "main" / "java" / "com" / "example"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "App.java").write_text("package com.example;\npublic class App {}\n")

        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        result = engine.run(target=combined, config=cfg)

        skipped_ids = {e["rule_id"] for e in result.run_metadata.rules_skipped}
        assert "architectural-drift-from-adr" in skipped_ids

        run_set = set(result.run_metadata.rules_run)
        assert "sample-readme-exists" in run_set


class TestRunMetadataBand2SkipReasons:
    """Verify JSONL run_metadata shows Band 2 skip reasons distinctly."""

    def test_skip_reasons_distinct_for_band2(self) -> None:
        cregistry, rregistry = _full_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(tech={})
        result = engine.run(target=JAVA_REPO, config=cfg)

        band2_skips = [
            e for e in result.run_metadata.rules_skipped if e["rule_id"] in BAND2_RULE_IDS
        ]
        assert len(band2_skips) == 2
        reasons = {e["reason"] for e in band2_skips}
        assert len(reasons) >= 1
        for reason in reasons:
            assert reason != ""
            assert "tech not declared" not in reason
