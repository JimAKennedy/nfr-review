# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: correlation-id-missing — flags Java/Spring projects lacking tracing libraries."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

# Exact artifact names and prefixes that satisfy the correlation-ID / tracing requirement.
_TRACING_EXACT: frozenset[str] = frozenset(
    {
        "org.springframework.cloud:spring-cloud-starter-sleuth",
        "io.micrometer:micrometer-tracing",
        "io.opentelemetry:opentelemetry-api",
    }
)

# Prefix match — catches micrometer-tracing-bridge-* variants.
_TRACING_PREFIXES: tuple[str, ...] = (
    "io.micrometer:micrometer-tracing-bridge-",
    "io.opentelemetry.instrumentation:",
)


def _is_tracing_dep(name: str) -> bool:
    if name in _TRACING_EXACT:
        return True
    return any(name.startswith(prefix) for prefix in _TRACING_PREFIXES)


class CorrelationIdMissingRule:
    """Flag Java projects that have no distributed tracing / correlation-ID library."""

    id = "correlation-id-missing"
    band: Band = 1
    required_collectors: list[str] = ["java-deps"]
    required_tech: list[str] = ["java"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_deps_evidence = filter_evidence(evidence, "java-deps", "java-deps")
        if not java_deps_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no java-deps evidence available",
            )

        ev = java_deps_evidence[0]
        dependencies: list[dict[str, Any]] = ev.payload.get("dependencies", [])

        has_tracing = any(_is_tracing_dep(dep.get("name", "")) for dep in dependencies)

        if has_tracing:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "correlation-id",
                        ev,
                        summary="Distributed tracing / correlation-ID library is present.",
                        recommendation=(
                            "No action required — a tracing library is on the classpath."
                        ),
                        evidence_locator=ev.locator,
                    )
                ],
            )

        manifest_files = ev.payload.get("manifest_files_found", [])
        locator = manifest_files[0] if manifest_files else ev.locator

        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        "No distributed tracing or correlation-ID library found."
                        " Requests cannot be correlated across service boundaries."
                    ),
                    recommendation=(
                        "Add one of the following to your dependencies:"
                        " io.micrometer:micrometer-tracing-bridge-brave (Spring Boot 3+),"
                        " org.springframework.cloud:spring-cloud-starter-sleuth"
                        " (Spring Boot 2),"
                        " or io.opentelemetry:opentelemetry-api with an SDK implementation."
                    ),
                    evidence_locator=locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.85,
                    pattern_tag="correlation-id",
                )
            ],
        )


def _register() -> None:
    if "correlation-id-missing" not in rule_registry:
        rule_registry.register("correlation-id-missing", CorrelationIdMissingRule())


_register()

__all__ = ["CorrelationIdMissingRule"]
