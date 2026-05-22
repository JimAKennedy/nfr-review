# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: resource-limits-missing — checks K8s workload containers for resource limits."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class ResourceLimitsMissingRule:
    """Flag containers that do not define resources.limits."""

    id = "resource-limits-missing"
    band: Band = 1
    required_tech: list[str] = ["kubernetes"]
    required_collectors: list[str] = ["k8s-manifest"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        k8s_resources = [
            e
            for e in evidence
            if e.collector_name == "k8s-manifest" and e.kind == "k8s-resource"
        ]
        if not k8s_resources:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no k8s-manifest evidence available",
            )

        findings: list[Finding] = []
        for ev in k8s_resources:
            resource_name = ev.payload.get("name", "")
            file_path = ev.payload.get("file_path", ev.locator)
            for container in ev.payload.get("containers", []):
                container_name = container.get("name", "")
                resources = container.get("resources")
                has_limits = isinstance(resources, dict) and bool(resources.get("limits"))
                if not has_limits:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="high",
                            summary=(
                                f"Container '{container_name}' in"
                                f" {resource_name} has no resource limits."
                            ),
                            recommendation=(
                                "Define resources.limits (cpu and memory)"
                                " to prevent unbounded resource consumption"
                                " and ensure fair scheduling."
                            ),
                            evidence_locator=(f"{file_path}:{resource_name}:{container_name}"),
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.95,
                            pattern_tag="k8s-resource-limits",
                        )
                    )

        if not findings:
            first = k8s_resources[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="All containers have resource limits defined.",
                    recommendation="No action required — resource limits are present.",
                    evidence_locator="all-workloads",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.95,
                    pattern_tag="k8s-resource-limits",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "resource-limits-missing" not in rule_registry:
        rule_registry.register("resource-limits-missing", ResourceLimitsMissingRule())


_register()

__all__ = ["ResourceLimitsMissingRule"]
