"""Tests for S02 OTel test-coverage observability rules."""

from __future__ import annotations

import importlib
from typing import Any

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.otel_fault_injection_tests import OTelFaultInjectionTestsRule
from nfr_review.rules.otel_integration_test_coverage import (
    OTelIntegrationTestCoverageRule,
)
from nfr_review.rules.otel_test_observability import OTelTestObservabilityRule


def _make_java_ast_evidence(
    file_path: str,
    *,
    classes: list[dict[str, Any]] | None = None,
    imports: list[str] | None = None,
) -> Evidence:
    return Evidence(
        collector_name="java-ast",
        collector_version="0.1.0",
        locator=file_path,
        kind="java-ast-file",
        payload={
            "file_path": file_path,
            "package": "com.example",
            "classes": classes or [],
            "methods": [],
            "catch_blocks": [],
            "imports": imports or [],
            "thread_pool_constructions": [],
            "log_statements": [],
        },
    )


def _make_spring_evidence(
    file_path: str = "application.yml",
    *,
    raw_keys: list[str] | None = None,
    profile: str | None = None,
) -> Evidence:
    return Evidence(
        collector_name="spring-config",
        collector_version="0.1.0",
        locator=file_path,
        kind="spring-config-file",
        payload={
            "file_path": file_path,
            "profile": profile,
            "management": {},
            "logging": {},
            "server": {},
            "spring_security": {},
            "actuator": {},
            "raw_keys": raw_keys or [],
        },
    )


def _make_ci_evidence(
    *, has_test_step: bool = True, has_security_scan: bool = False
) -> Evidence:
    return Evidence(
        collector_name="ci-artifact",
        collector_version="0.1.0",
        locator=".github/workflows/ci.yml",
        kind="ci-pipeline",
        payload={
            "file_path": ".github/workflows/ci.yml",
            "ci_system": "github-actions",
            "has_test_step": has_test_step,
            "has_security_scan": has_security_scan,
            "job_names": ["test"],
            "step_names": ["Run tests"],
        },
    )


def _make_sdk_evidence(
    *, agent_attached: bool = False, source_file: str = "docker-compose.yml"
) -> Evidence:
    return Evidence(
        collector_name="otel",
        collector_version="0.1.0",
        locator=source_file,
        kind="otel-sdk-config",
        payload={
            "agent_attached": agent_attached,
            "exporter_type": None,
            "propagators": [],
            "resource_attributes": {},
            "source_file": source_file,
        },
    )


def _controller_class(
    name: str,
    endpoints: list[str] | None = None,
    methods: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if methods is None:
        methods = []
        for ep in endpoints or ["/default"]:
            methods.append(
                {
                    "name": ep.strip("/").replace("/", "_") or "index",
                    "annotations": [{"name": "GetMapping"}],
                    "mapping_paths": [ep],
                    "return_type": "String",
                    "access": "public",
                    "is_pure_virtual": False,
                    "line": 10,
                    "parameters": [],
                }
            )
    return {
        "name": name,
        "line": 5,
        "annotations": [{"name": "RestController"}],
        "is_abstract": False,
        "is_interface": False,
        "base_classes": [],
        "fields": [],
        "methods": methods,
        "namespace": "",
        "outer_class": None,
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_integration_test_coverage_registered(self) -> None:
        import nfr_review.rules.otel_integration_test_coverage

        importlib.reload(nfr_review.rules.otel_integration_test_coverage)
        assert "otel-integration-test-coverage" in rule_registry

    def test_fault_injection_registered(self) -> None:
        import nfr_review.rules.otel_fault_injection_tests

        importlib.reload(nfr_review.rules.otel_fault_injection_tests)
        assert "otel-fault-injection-tests" in rule_registry

    def test_test_observability_registered(self) -> None:
        import nfr_review.rules.otel_test_observability

        importlib.reload(nfr_review.rules.otel_test_observability)
        assert "otel-test-observability" in rule_registry


# ---------------------------------------------------------------------------
# Rule attributes
# ---------------------------------------------------------------------------


class TestRuleAttributes:
    def test_integration_coverage_attributes(self) -> None:
        rule = OTelIntegrationTestCoverageRule()
        assert rule.id == "otel-integration-test-coverage"
        assert rule.band == 1

    def test_fault_injection_attributes(self) -> None:
        rule = OTelFaultInjectionTestsRule()
        assert rule.id == "otel-fault-injection-tests"
        assert rule.band == 1

    def test_test_observability_attributes(self) -> None:
        rule = OTelTestObservabilityRule()
        assert rule.id == "otel-test-observability"
        assert rule.band == 1


# ---------------------------------------------------------------------------
# OTelIntegrationTestCoverageRule
# ---------------------------------------------------------------------------


class TestIntegrationTestCoverage:
    def setup_method(self) -> None:
        self.rule = OTelIntegrationTestCoverageRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert "no java-ast-file evidence" in result.skip_reason

    def test_skip_no_controllers(self) -> None:
        evidence = [
            _make_java_ast_evidence(
                "src/main/java/com/example/Service.java",
                classes=[
                    {
                        "name": "Service",
                        "line": 1,
                        "annotations": [{"name": "Service"}],
                        "is_abstract": False,
                        "is_interface": False,
                        "base_classes": [],
                        "fields": [],
                        "methods": [],
                        "namespace": "",
                        "outer_class": None,
                    }
                ],
            )
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.skipped is True
        assert "no controller classes" in result.skip_reason

    def test_green_all_controllers_have_tests(self) -> None:
        evidence = [
            _make_java_ast_evidence(
                "src/main/java/com/example/GreetingController.java",
                classes=[_controller_class("GreetingController", ["/greeting"])],
            ),
            _make_java_ast_evidence(
                "src/test/java/com/example/GreetingControllerIT.java",
                classes=[],
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_amber_missing_test(self) -> None:
        evidence = [
            _make_java_ast_evidence(
                "src/main/java/com/example/GreetingController.java",
                classes=[_controller_class("GreetingController", ["/greeting"])],
            ),
            _make_java_ast_evidence(
                "src/main/java/com/example/OrderController.java",
                classes=[_controller_class("OrderController", ["/orders"])],
            ),
            _make_java_ast_evidence(
                "src/test/java/com/example/GreetingControllerIT.java",
                classes=[],
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "OrderController" in result.findings[0].summary

    def test_amber_no_tests_at_all(self) -> None:
        evidence = [
            _make_java_ast_evidence(
                "src/main/java/com/example/PaymentController.java",
                classes=[_controller_class("PaymentController", ["/payments"])],
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "PaymentController" in result.findings[0].summary

    def test_finding_fields_complete(self) -> None:
        evidence = [
            _make_java_ast_evidence(
                "src/main/java/com/example/Ctrl.java",
                classes=[_controller_class("Ctrl", ["/api"])],
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "otel-integration-test-coverage"
        assert f.collector_name == "java-ast"
        assert f.confidence >= 0.0
        assert f.pattern_tag == "otel-integration-test-coverage"


# ---------------------------------------------------------------------------
# OTelFaultInjectionTestsRule
# ---------------------------------------------------------------------------


class TestFaultInjectionTests:
    def setup_method(self) -> None:
        self.rule = OTelFaultInjectionTestsRule()

    def test_skip_no_resilience(self) -> None:
        evidence = [
            _make_java_ast_evidence(
                "src/main/java/com/example/App.java",
                classes=[],
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.skipped is True
        assert "no resilience patterns" in result.skip_reason

    def test_green_resilience_with_fault_tests(self) -> None:
        evidence = [
            _make_spring_evidence(raw_keys=["resilience4j"]),
            _make_java_ast_evidence(
                "src/test/java/com/example/OrderResilienceIT.java",
                classes=[],
                imports=["com.github.tomakehurst.wiremock.WireMockServer"],
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_amber_resilience_without_fault_tests(self) -> None:
        evidence = [
            _make_spring_evidence(raw_keys=["resilience4j"]),
            _make_java_ast_evidence(
                "src/test/java/com/example/AppTest.java",
                classes=[],
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "fault-injection" in result.findings[0].summary.lower()

    def test_detect_resilience_from_annotations(self) -> None:
        evidence = [
            _make_java_ast_evidence(
                "src/main/java/com/example/OrderService.java",
                classes=[
                    {
                        "name": "OrderService",
                        "line": 1,
                        "annotations": [],
                        "is_abstract": False,
                        "is_interface": False,
                        "base_classes": [],
                        "fields": [],
                        "methods": [
                            {
                                "name": "getOrder",
                                "annotations": [{"name": "CircuitBreaker"}],
                                "return_type": "Order",
                                "access": "public",
                                "is_pure_virtual": False,
                                "line": 10,
                                "parameters": [],
                            }
                        ],
                        "namespace": "",
                        "outer_class": None,
                    }
                ],
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"

    def test_detect_fault_test_by_filename(self) -> None:
        evidence = [
            _make_spring_evidence(raw_keys=["resilience4j"]),
            _make_java_ast_evidence(
                "src/test/java/com/example/ChaosTest.java",
                classes=[],
            ),
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_finding_fields_complete(self) -> None:
        evidence = [
            _make_spring_evidence(raw_keys=["resilience4j"]),
        ]
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "otel-fault-injection-tests"
        assert f.collector_name == "spring-config"
        assert f.confidence >= 0.0
        assert f.pattern_tag == "otel-fault-injection-tests"


# ---------------------------------------------------------------------------
# OTelTestObservabilityRule
# ---------------------------------------------------------------------------


class TestTestObservability:
    def setup_method(self) -> None:
        self.rule = OTelTestObservabilityRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True

    def test_skip_no_test_steps(self) -> None:
        evidence = [_make_ci_evidence(has_test_step=False)]
        result = self.rule.evaluate(evidence, None)
        assert result.skipped is True

    def test_green_otel_in_tests(self) -> None:
        evidence = [
            _make_ci_evidence(has_test_step=True),
            _make_sdk_evidence(agent_attached=True),
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "green"

    def test_amber_tests_without_otel(self) -> None:
        evidence = [
            _make_ci_evidence(has_test_step=True),
            _make_sdk_evidence(agent_attached=False),
        ]
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"
        assert "not wired" in result.findings[0].summary.lower()

    def test_amber_ci_tests_only_no_sdk(self) -> None:
        evidence = [_make_ci_evidence(has_test_step=True)]
        result = self.rule.evaluate(evidence, None)
        assert result.findings[0].rag == "amber"

    def test_finding_fields_complete(self) -> None:
        evidence = [
            _make_ci_evidence(has_test_step=True),
            _make_sdk_evidence(agent_attached=False),
        ]
        result = self.rule.evaluate(evidence, None)
        f = result.findings[0]
        assert f.rule_id == "otel-test-observability"
        assert f.confidence >= 0.0
        assert f.pattern_tag == "otel-test-observability"
