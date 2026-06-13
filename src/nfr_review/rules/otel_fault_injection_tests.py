# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-fault-injection-tests: flags repos with resilience patterns but no fault tests."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_RESILIENCE_CONFIG_KEYS = frozenset(
    {
        "resilience4j",
        "circuitbreaker",
        "circuit-breaker",
        "retry",
        "bulkhead",
        "ratelimiter",
        "timelimiter",
    }
)

_RESILIENCE_ANNOTATIONS = frozenset(
    {
        "CircuitBreaker",
        "Retry",
        "Bulkhead",
        "RateLimiter",
        "TimeLimiter",
        "HystrixCommand",
    }
)

_FAULT_TEST_PATTERNS = frozenset(
    {
        "fault",
        "chaos",
        "resilience",
        "wiremock",
        "testcontainers",
        "toxiproxy",
        "failsafe",
        "circuitbreaker",
    }
)


class OTelFaultInjectionTestsRule:
    """Flag repos with resilience patterns but no fault-injection tests."""

    id = "otel-fault-injection-tests"
    band: Band = 1
    required_collectors: list[str] = ["repo-structure"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_ast_evidence = filter_evidence(evidence, "java-ast", "java-ast-file")
        spring_evidence = filter_evidence(evidence, "spring-config", "spring-config-file")

        has_resilience_config = self._check_spring_resilience(spring_evidence)
        has_resilience_annotations = self._check_ast_resilience(java_ast_evidence)
        has_resilience = has_resilience_config or has_resilience_annotations

        if not has_resilience:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no resilience patterns detected in project",
            )

        first = (spring_evidence or java_ast_evidence)[0]
        has_fault_tests = self._check_fault_tests(java_ast_evidence)

        if has_fault_tests:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "otel-fault-injection-tests",
                        first,
                        summary=(
                            "Resilience patterns detected with corresponding "
                            "fault-injection tests."
                        ),
                        confidence=0.75,
                        evidence_locator=first.locator,
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        "Resilience patterns (circuit breakers, retries) detected "
                        "but no fault-injection tests found."
                    ),
                    recommendation=(
                        "Create fault-injection test classes that exercise "
                        "resilience patterns under failure conditions. Use WireMock "
                        "to simulate downstream failures, Testcontainers with "
                        "Toxiproxy for network faults, or @DirtiesContext for "
                        "state-dependent scenarios. These tests should trigger "
                        "circuit-breaker opens, retry exhaustion, and bulkhead "
                        "rejection to validate resilience behavior."
                    ),
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.7,
                    pattern_tag="otel-fault-injection-tests",
                )
            ],
        )

    @staticmethod
    def _check_spring_resilience(spring_evidence: list[Evidence]) -> bool:
        for ev in spring_evidence:
            raw_keys = ev.payload.get("raw_keys", [])
            if isinstance(raw_keys, list):
                for key in raw_keys:
                    if isinstance(key, str) and key.lower() in _RESILIENCE_CONFIG_KEYS:
                        return True
        return False

    @staticmethod
    def _check_ast_resilience(java_evidence: list[Evidence]) -> bool:
        for ev in java_evidence:
            file_path = ev.payload.get("file_path", "")
            if "/test/" in file_path:
                continue
            classes = ev.payload.get("classes", [])
            for cls in classes:
                if not isinstance(cls, dict):
                    continue
                methods = cls.get("methods", [])
                for m in methods:
                    if not isinstance(m, dict):
                        continue
                    annotations = m.get("annotations", [])
                    for a in annotations:
                        name = a.get("name", "") if isinstance(a, dict) else str(a)
                        if name in _RESILIENCE_ANNOTATIONS:
                            return True
        return False

    @staticmethod
    def _check_fault_tests(java_evidence: list[Evidence]) -> bool:
        for ev in java_evidence:
            file_path = ev.payload.get("file_path", "")
            if "/test/" not in file_path:
                continue
            path_lower = file_path.lower()
            if any(pat in path_lower for pat in _FAULT_TEST_PATTERNS):
                return True
            imports = ev.payload.get("imports", [])
            if isinstance(imports, list):
                imports_lower = " ".join(str(i).lower() for i in imports)
                if any(pat in imports_lower for pat in _FAULT_TEST_PATTERNS):
                    return True
        return False


def _register() -> None:
    if "otel-fault-injection-tests" not in rule_registry:
        rule_registry.register("otel-fault-injection-tests", OTelFaultInjectionTestsRule())


_register()

__all__ = ["OTelFaultInjectionTestsRule"]
