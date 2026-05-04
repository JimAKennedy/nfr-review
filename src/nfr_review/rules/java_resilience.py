"""Rule: resilience-annotation-missing.

Flags classes using HTTP clients that lack resilience annotations.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_HTTP_CLIENT_PATTERNS = frozenset({"RestTemplate", "WebClient", "FeignClient"})

_RESILIENCE_ANNOTATIONS = frozenset({
    "CircuitBreaker",
    "Retry",
    "Bulkhead",
    "RateLimiter",
})

_TEST_PATH_SEGMENTS = ("/src/test/", "/test/", "Test.java", "Tests.java", "IT.java")


class ResilienceAnnotationMissingRule:
    """Flag classes that import HTTP clients but lack resilience annotations."""

    id = "resilience-annotation-missing"
    band: Band = 1
    required_collectors: list[str] = ["java-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_evidence = [
            e
            for e in evidence
            if e.collector_name == "java-ast" and e.kind == "java-ast-file"
        ]
        if not java_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no java-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in java_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            if any(seg in file_path for seg in _TEST_PATH_SEGMENTS):
                continue
            imports = ev.payload.get("imports", [])
            uses_http_client = any(
                any(pattern in imp for imp in imports)
                for pattern in _HTTP_CLIENT_PATTERNS
            )
            if not uses_http_client:
                continue

            for cls in ev.payload.get("classes", []):
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
                            evidence_locator=(
                                f"{file_path}:{cls['name']}"
                            ),
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.8,
                            pattern_tag="resilience-pattern",
                        )
                    )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        "All HTTP-client classes have resilience"
                        " annotations, or no HTTP clients found."
                    ),
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=java_evidence[0].collector_name,
                    collector_version=java_evidence[0].collector_version,
                    confidence=0.8,
                    pattern_tag="resilience-pattern",
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
