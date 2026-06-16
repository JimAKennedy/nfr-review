# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: resilience-annotation-missing.

Flags classes using HTTP clients that lack resilience annotations.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_HTTP_CLIENT_PATTERNS = frozenset({"RestTemplate", "WebClient", "FeignClient"})

_RESILIENCE_ANNOTATIONS = frozenset(
    {
        "CircuitBreaker",
        "Retry",
        "Bulkhead",
        "RateLimiter",
    }
)


class ResilienceAnnotationMissingRule:
    """Flag classes that import HTTP clients but lack resilience annotations."""

    id = "resilience-annotation-missing"
    band: Band = 1
    required_collectors: list[str] = ["java-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_evidence = filter_evidence(evidence, "java-ast", "java-ast-file")
        if not java_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no java-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in java_evidence:
            file_path = ev.payload.file_path
            imports = ev.payload.imports
            uses_http_client = any(
                any(pattern in imp for imp in imports) for pattern in _HTTP_CLIENT_PATTERNS
            )
            if not uses_http_client:
                continue

            for cls in ev.payload.classes:
                class_annotations = set(cls.get("annotations", []))
                method_annotations: set[str] = set()
                for method in cls.get("methods", []):
                    method_annotations.update(method.get("annotations", []))

                all_annotations = class_annotations | method_annotations
                has_resilience = bool(all_annotations & _RESILIENCE_ANNOTATIONS)

                if not has_resilience:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="high",
                            summary=(
                                f"Class {cls['name']} uses HTTP"
                                " client but has no resilience"
                                " annotations."
                            ),
                            recommendation=(
                                "Add @CircuitBreaker, @Retry, or"
                                " @Bulkhead to service methods making"
                                " external calls."
                            ),
                            evidence_locator=(f"{file_path}:{cls['name']}"),
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.8,
                            pattern_tag="resilience-pattern",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "resilience-pattern",
                    java_evidence[0],
                    summary=(
                        "All HTTP-client classes have resilience"
                        " annotations, or no HTTP clients found."
                    ),
                    confidence=0.8,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "resilience-annotation-missing" not in rule_registry:
        rule_registry.register(
            "resilience-annotation-missing", ResilienceAnnotationMissingRule()
        )


_register()

__all__ = ["ResilienceAnnotationMissingRule"]
