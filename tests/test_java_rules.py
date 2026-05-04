"""Tests for Java AST Band 1 rules — positive and negative fixtures."""

from __future__ import annotations

import pytest

from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.java_exception import ExceptionHandlingAntipatternRule
from nfr_review.rules.java_health import HealthEndpointMissingRule
from nfr_review.rules.java_resilience import ResilienceAnnotationMissingRule
from nfr_review.rules.java_thread_pool import ThreadPoolMisconfigurationRule


def _java_evidence(payload: dict) -> Evidence:
    return Evidence(
        collector_name="java-ast",
        collector_version="0.1.0",
        locator=payload.get("file_path", "Test.java"),
        kind="java-ast-file",
        payload=payload,
    )


# ---------------------------------------------------------------------------
# health-endpoint-missing
# ---------------------------------------------------------------------------


class TestHealthEndpointMissingRule:
    def setup_method(self) -> None:
        self.rule = HealthEndpointMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no java-ast evidence available"

    def test_health_endpoint_present_green(self) -> None:
        ev = _java_evidence({
            "file_path": "src/HealthController.java",
            "classes": [
                {
                    "name": "HealthController",
                    "annotations": ["RestController"],
                    "methods": [
                        {
                            "name": "health",
                            "annotations": ["GetMapping"],
                            "return_type": "String",
                            "mapping_paths": ["/health"],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "health-endpoint"

    def test_actuator_health_present_green(self) -> None:
        ev = _java_evidence({
            "file_path": "src/ActuatorController.java",
            "classes": [
                {
                    "name": "ActuatorController",
                    "annotations": ["RestController"],
                    "methods": [
                        {
                            "name": "actuatorHealth",
                            "annotations": ["GetMapping"],
                            "return_type": "String",
                            "mapping_paths": ["/actuator/health"],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_no_health_endpoint_amber(self) -> None:
        ev = _java_evidence({
            "file_path": "src/UserController.java",
            "classes": [
                {
                    "name": "UserController",
                    "annotations": ["RestController"],
                    "methods": [
                        {
                            "name": "getUsers",
                            "annotations": ["GetMapping"],
                            "return_type": "List",
                            "mapping_paths": ["/users"],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"

    def test_actuator_config_detected_green(self) -> None:
        """Spring Boot Actuator auto-config should satisfy the health check."""
        java_ev = _java_evidence({
            "file_path": "src/UserController.java",
            "classes": [
                {
                    "name": "UserController",
                    "annotations": ["RestController"],
                    "methods": [
                        {
                            "name": "getUsers",
                            "annotations": ["GetMapping"],
                            "return_type": "List",
                            "mapping_paths": ["/users"],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [],
        })
        spring_ev = Evidence(
            collector_name="spring-config",
            collector_version="0.1.0",
            locator="src/main/resources/application.yaml",
            kind="spring-config-file",
            payload={
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {"endpoints": {"web": {"exposure": {"include": "*"}}}},
                "logging": {},
                "server": {},
                "spring_security": {},
                "actuator": {"include": "*"},
                "raw_keys": ["management"],
            },
        )
        result = self.rule.evaluate([java_ev, spring_ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "Actuator" in result.findings[0].summary

    def test_actuator_health_excluded_amber(self) -> None:
        """If health is explicitly excluded from Actuator, should still flag."""
        java_ev = _java_evidence({
            "file_path": "src/UserController.java",
            "classes": [
                {
                    "name": "UserController",
                    "annotations": ["RestController"],
                    "methods": [
                        {
                            "name": "getUsers",
                            "annotations": ["GetMapping"],
                            "return_type": "List",
                            "mapping_paths": ["/users"],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [],
        })
        spring_ev = Evidence(
            collector_name="spring-config",
            collector_version="0.1.0",
            locator="src/main/resources/application.yaml",
            kind="spring-config-file",
            payload={
                "file_path": "src/main/resources/application.yaml",
                "profile": None,
                "management": {"endpoints": {"web": {"exposure": {"exclude": "health"}}}},
                "logging": {},
                "server": {},
                "spring_security": {},
                "actuator": {"exclude": "health"},
                "raw_keys": ["management"],
            },
        )
        result = self.rule.evaluate([java_ev, spring_ev], None)
        assert result.findings[0].rag == "amber"

    def test_non_controller_class_amber(self) -> None:
        ev = _java_evidence({
            "file_path": "src/Service.java",
            "classes": [
                {
                    "name": "MyService",
                    "annotations": ["Service"],
                    "methods": [
                        {
                            "name": "doStuff",
                            "annotations": [],
                            "return_type": "void",
                            "mapping_paths": [],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"


# ---------------------------------------------------------------------------
# exception-handling-antipattern
# ---------------------------------------------------------------------------


class TestExceptionHandlingAntipatternRule:
    def setup_method(self) -> None:
        self.rule = ExceptionHandlingAntipatternRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True

    def test_broad_catch_without_rethrow_red(self) -> None:
        ev = _java_evidence({
            "file_path": "src/BadService.java",
            "classes": [],
            "methods": [],
            "catch_blocks": [
                {"caught_type": "Exception", "rethrows": False, "line": 42},
            ],
            "imports": [],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"
        assert "42" in result.findings[0].evidence_locator

    def test_throwable_without_rethrow_red(self) -> None:
        ev = _java_evidence({
            "file_path": "src/Unsafe.java",
            "classes": [],
            "methods": [],
            "catch_blocks": [
                {"caught_type": "Throwable", "rethrows": False, "line": 10},
            ],
            "imports": [],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "red"

    def test_broad_catch_with_rethrow_green(self) -> None:
        ev = _java_evidence({
            "file_path": "src/OkService.java",
            "classes": [],
            "methods": [],
            "catch_blocks": [
                {"caught_type": "Exception", "rethrows": True, "line": 20},
            ],
            "imports": [],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_specific_catch_green(self) -> None:
        ev = _java_evidence({
            "file_path": "src/Good.java",
            "classes": [],
            "methods": [],
            "catch_blocks": [
                {"caught_type": "IOException", "rethrows": False, "line": 5},
            ],
            "imports": [],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_multiple_violations_multiple_findings(self) -> None:
        ev = _java_evidence({
            "file_path": "src/Multi.java",
            "classes": [],
            "methods": [],
            "catch_blocks": [
                {"caught_type": "Exception", "rethrows": False, "line": 10},
                {"caught_type": "Throwable", "rethrows": False, "line": 30},
            ],
            "imports": [],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        red_findings = [f for f in result.findings if f.rag == "red"]
        assert len(red_findings) == 2


# ---------------------------------------------------------------------------
# resilience-annotation-missing
# ---------------------------------------------------------------------------


class TestResilienceAnnotationMissingRule:
    def setup_method(self) -> None:
        self.rule = ResilienceAnnotationMissingRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True

    def test_http_client_without_resilience_amber(self) -> None:
        ev = _java_evidence({
            "file_path": "src/ApiClient.java",
            "classes": [
                {
                    "name": "ApiClient",
                    "annotations": ["Service"],
                    "methods": [
                        {
                            "name": "callExternal",
                            "annotations": [],
                            "return_type": "String",
                            "mapping_paths": [],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": ["org.springframework.web.client.RestTemplate"],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "ApiClient" in amber[0].summary

    def test_http_client_with_circuit_breaker_green(self) -> None:
        ev = _java_evidence({
            "file_path": "src/ResilientClient.java",
            "classes": [
                {
                    "name": "ResilientClient",
                    "annotations": ["Service"],
                    "methods": [
                        {
                            "name": "callExternal",
                            "annotations": ["CircuitBreaker"],
                            "return_type": "String",
                            "mapping_paths": [],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": ["org.springframework.web.client.RestTemplate"],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        green = [f for f in result.findings if f.rag == "green"]
        assert len(green) == 1

    def test_no_http_client_green(self) -> None:
        ev = _java_evidence({
            "file_path": "src/InternalService.java",
            "classes": [
                {
                    "name": "InternalService",
                    "annotations": ["Service"],
                    "methods": [
                        {
                            "name": "process",
                            "annotations": [],
                            "return_type": "void",
                            "mapping_paths": [],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": ["java.util.List"],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        green = [f for f in result.findings if f.rag == "green"]
        assert len(green) == 1

    def test_webclient_import_without_resilience_amber(self) -> None:
        ev = _java_evidence({
            "file_path": "src/WebService.java",
            "classes": [
                {
                    "name": "WebService",
                    "annotations": [],
                    "methods": [
                        {
                            "name": "fetch",
                            "annotations": [],
                            "return_type": "Mono",
                            "mapping_paths": [],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": ["org.springframework.web.reactive.function.client.WebClient"],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1

    def test_test_classes_excluded(self) -> None:
        """Test files should not be flagged for missing resilience annotations."""
        ev = _java_evidence({
            "file_path": "src/test/java/com/example/RestTemplateConfigTest.java",
            "classes": [
                {
                    "name": "RestTemplateConfigTest",
                    "annotations": ["SpringBootTest"],
                    "methods": [
                        {
                            "name": "testConfig",
                            "annotations": ["Test"],
                            "return_type": "void",
                            "mapping_paths": [],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": ["org.springframework.web.client.RestTemplate"],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        green = [f for f in result.findings if f.rag == "green"]
        assert len(green) == 1

    def test_class_level_retry_counts_green(self) -> None:
        ev = _java_evidence({
            "file_path": "src/RetryClient.java",
            "classes": [
                {
                    "name": "RetryClient",
                    "annotations": ["Service", "Retry"],
                    "methods": [
                        {
                            "name": "callApi",
                            "annotations": [],
                            "return_type": "String",
                            "mapping_paths": [],
                        }
                    ],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": ["org.springframework.web.client.RestTemplate"],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        green = [f for f in result.findings if f.rag == "green"]
        assert len(green) == 1


# ---------------------------------------------------------------------------
# thread-pool-misconfiguration
# ---------------------------------------------------------------------------


class TestThreadPoolMisconfigurationRule:
    def setup_method(self) -> None:
        self.rule = ThreadPoolMisconfigurationRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True

    def test_unbounded_queue_amber(self) -> None:
        ev = _java_evidence({
            "file_path": "src/Config.java",
            "classes": [],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [
                {
                    "class_name": "ThreadPoolExecutor",
                    "line": 15,
                    "has_bounded_queue": False,
                    "has_rejection_policy": True,
                }
            ],
        })
        result = self.rule.evaluate([ev], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "unbounded queue" in amber[0].summary

    def test_no_rejection_policy_amber(self) -> None:
        ev = _java_evidence({
            "file_path": "src/Config.java",
            "classes": [],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [
                {
                    "class_name": "ThreadPoolExecutor",
                    "line": 20,
                    "has_bounded_queue": True,
                    "has_rejection_policy": False,
                }
            ],
        })
        result = self.rule.evaluate([ev], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "no rejection policy" in amber[0].summary

    def test_both_missing_amber(self) -> None:
        ev = _java_evidence({
            "file_path": "src/Config.java",
            "classes": [],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [
                {
                    "class_name": "ThreadPoolExecutor",
                    "line": 25,
                    "has_bounded_queue": False,
                    "has_rejection_policy": False,
                }
            ],
        })
        result = self.rule.evaluate([ev], None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "unbounded queue" in amber[0].summary
        assert "no rejection policy" in amber[0].summary

    def test_properly_configured_green(self) -> None:
        ev = _java_evidence({
            "file_path": "src/GoodConfig.java",
            "classes": [],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [
                {
                    "class_name": "ThreadPoolExecutor",
                    "line": 30,
                    "has_bounded_queue": True,
                    "has_rejection_policy": True,
                }
            ],
        })
        result = self.rule.evaluate([ev], None)
        green = [f for f in result.findings if f.rag == "green"]
        assert len(green) == 1

    def test_no_thread_pools_green(self) -> None:
        ev = _java_evidence({
            "file_path": "src/Simple.java",
            "classes": [],
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [],
        })
        result = self.rule.evaluate([ev], None)
        green = [f for f in result.findings if f.rag == "green"]
        assert len(green) == 1


# ---------------------------------------------------------------------------
# Cross-cutting: verify all rules follow protocol
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_class",
    [
        HealthEndpointMissingRule,
        ExceptionHandlingAntipatternRule,
        ResilienceAnnotationMissingRule,
        ThreadPoolMisconfigurationRule,
    ],
)
def test_rule_protocol_compliance(rule_class: type) -> None:
    rule = rule_class()
    assert hasattr(rule, "id")
    assert hasattr(rule, "band")
    assert hasattr(rule, "required_collectors")
    assert rule.band == 1
    assert rule.required_collectors == ["java-ast"]
    result = rule.evaluate([], None)
    assert isinstance(result, RuleResult)
    assert result.skipped is True


@pytest.mark.parametrize(
    "rule_class",
    [
        HealthEndpointMissingRule,
        ExceptionHandlingAntipatternRule,
        ResilienceAnnotationMissingRule,
        ThreadPoolMisconfigurationRule,
    ],
)
def test_finding_has_all_r007_fields(rule_class: type) -> None:
    """Verify that when a rule fires, findings have all 10 R007 fields."""
    ev = _java_evidence({
        "file_path": "src/Test.java",
        "classes": [
            {
                "name": "TestController",
                "annotations": ["RestController"],
                "methods": [
                    {
                        "name": "test",
                        "annotations": ["GetMapping"],
                        "return_type": "String",
                        "mapping_paths": ["/users"],
                    }
                ],
            }
        ],
        "methods": [],
        "catch_blocks": [
            {"caught_type": "Exception", "rethrows": False, "line": 10},
        ],
        "imports": ["org.springframework.web.client.RestTemplate"],
        "thread_pool_constructions": [
            {
                "class_name": "ThreadPoolExecutor",
                "line": 50,
                "has_bounded_queue": False,
                "has_rejection_policy": False,
            }
        ],
    })
    rule = rule_class()
    result = rule.evaluate([ev], None)
    assert not result.skipped
    for finding in result.findings:
        assert finding.rule_id
        assert finding.rag in ("red", "amber", "green")
        assert finding.severity
        assert finding.summary
        assert finding.recommendation
        assert finding.evidence_locator
        assert finding.collector_name == "java-ast"
        assert finding.collector_version == "0.1.0"
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.pattern_tag
