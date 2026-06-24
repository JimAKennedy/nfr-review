# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-fault-injection-tests: flags repos with resilience patterns but no fault tests."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.java_ast import JavaAstFilePayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding

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


class OTelFaultInjectionTestsRule(FieldRule[JavaAstFilePayload]):
    """Flag repos with resilience patterns but no fault-injection tests."""

    id = "otel-fault-injection-tests"
    collector_name = "java-ast"
    evidence_kind = "java-ast-file"
    payload_type = JavaAstFilePayload
    pattern_tag = "otel-fault-injection-tests"
    required_tech: list[str] = []
    required_collectors: list[str] = ["repo-structure"]
    default_confidence = 0.75
    all_clear_summary = (
        "Resilience patterns detected with corresponding fault-injection tests."
    )
    all_clear_recommendation = "No action required."

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_ast_evidence = [
            e for e in evidence if e.collector_name == "java-ast" and e.kind == "java-ast-file"
        ]
        spring_evidence = [
            e
            for e in evidence
            if e.collector_name == "spring-config" and e.kind == "spring-config-file"
        ]

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
                    make_finding(
                        rule_id=self.id,
                        ev=first,
                        pattern_tag=self.pattern_tag,
                        default_confidence=0.75,
                        hit=Hit(
                            rag="green",
                            summary=(
                                "Resilience patterns detected with corresponding "
                                "fault-injection tests."
                            ),
                            recommendation="No action required.",
                            locator=first.locator,
                            confidence=0.75,
                        ),
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_finding(
                    rule_id=self.id,
                    ev=first,
                    pattern_tag=self.pattern_tag,
                    default_confidence=0.7,
                    hit=Hit(
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
                        locator=first.locator,
                        confidence=0.7,
                    ),
                )
            ],
        )

    @staticmethod
    def _check_spring_resilience(spring_evidence: list[Evidence]) -> bool:
        for ev in spring_evidence:
            raw_keys = ev.payload.raw_keys
            if isinstance(raw_keys, list):
                for key in raw_keys:
                    if isinstance(key, str) and key.lower() in _RESILIENCE_CONFIG_KEYS:
                        return True
        return False

    @staticmethod
    def _check_ast_resilience(java_evidence: list[Evidence]) -> bool:
        for ev in java_evidence:
            file_path = ev.payload.file_path
            if "/test/" in file_path:
                continue
            classes = ev.payload.classes
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
            file_path = ev.payload.file_path
            if "/test/" not in file_path:
                continue
            path_lower = file_path.lower()
            if any(pat in path_lower for pat in _FAULT_TEST_PATTERNS):
                return True
            imports = ev.payload.imports
            if isinstance(imports, list):
                imports_lower = " ".join(str(i).lower() for i in imports)
                if any(pat in imports_lower for pat in _FAULT_TEST_PATTERNS):
                    return True
        return False


__all__ = ["OTelFaultInjectionTestsRule"]
