# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: health-endpoint-missing — checks for health endpoint in Spring controllers."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_HEALTH_PATHS = frozenset({"/health", "/actuator/health"})


class HealthEndpointMissingRule:
    """Flag when no @RestController exposes a health-check endpoint."""

    id = "health-endpoint-missing"
    band: Band = 1
    required_collectors: list[str] = ["java-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_evidence = [
            e for e in evidence if e.collector_name == "java-ast" and e.kind == "java-ast-file"
        ]
        if not java_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no java-ast evidence available",
            )

        for ev in java_evidence:
            for cls in ev.payload.get("classes", []):
                if "RestController" not in cls.get("annotations", []):
                    continue
                for method in cls.get("methods", []):
                    for path in method.get("mapping_paths", []):
                        if path in _HEALTH_PATHS:
                            file_ref = ev.payload.get("file_path", ev.locator)
                            locator = f"{file_ref}:{cls['name']}"
                            return RuleResult(
                                rule_id=self.id,
                                findings=[
                                    Finding(
                                        rule_id=self.id,
                                        rag="green",
                                        severity="info",
                                        summary=(
                                            f"Health endpoint found: {path} in {cls['name']}"
                                        ),
                                        recommendation=(
                                            "No action required — health endpoint is present."
                                        ),
                                        evidence_locator=locator,
                                        collector_name=ev.collector_name,
                                        collector_version=ev.collector_version,
                                        confidence=0.9,
                                        pattern_tag="health-endpoint",
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
                        "No health endpoint (/health or"
                        " /actuator/health) detected in any"
                        " @RestController."
                    ),
                    recommendation=(
                        "Add a health-check endpoint (e.g. Spring"
                        " Boot Actuator /actuator/health) to enable"
                        " liveness/readiness probes."
                    ),
                    evidence_locator="project-wide",
                    collector_name=java_evidence[0].collector_name,
                    collector_version=java_evidence[0].collector_version,
                    confidence=0.9,
                    pattern_tag="health-endpoint",
                )
            ],
        )


def _register() -> None:
    if "health-endpoint-missing" not in rule_registry:
        rule_registry.register("health-endpoint-missing", HealthEndpointMissingRule())


_register()

__all__ = ["HealthEndpointMissingRule"]
