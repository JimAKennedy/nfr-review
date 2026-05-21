# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-ARCH-002 — checks K8s workloads for graceful shutdown configuration."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_MIN_GRACE_PERIOD = 30


class GracefulShutdownMissingRule:
    """Flag workloads missing preStop hooks or insufficient grace period."""

    id = "PATCH-ARCH-002"
    band: Band = 1
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

            # Check each container for preStop lifecycle hook
            for container in ev.payload.get("containers", []):
                container_name = container.get("name", "")
                has_pre_stop = container.get("pre_stop") is not None

                if not has_pre_stop:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Container '{container_name}' in"
                                f" {resource_name} is missing a"
                                f" preStop lifecycle hook."
                            ),
                            recommendation=(
                                "Define a preStop lifecycle hook (e.g. an exec"
                                " command or HTTP GET) to allow in-flight"
                                " requests to drain before SIGTERM is sent."
                            ),
                            evidence_locator=f"{file_path}:{resource_name}:{container_name}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="graceful-shutdown",
                        )
                    )

            # Check terminationGracePeriodSeconds at the workload level
            grace_period = ev.payload.get("termination_grace_period")
            if grace_period is None or grace_period < _MIN_GRACE_PERIOD:
                period_display = (
                    "not set (defaults to 30s)" if grace_period is None else f"{grace_period}s"
                )
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Workload {resource_name} has"
                            f" terminationGracePeriodSeconds {period_display},"
                            f" which may be insufficient for graceful shutdown."
                        ),
                        recommendation=(
                            "Set terminationGracePeriodSeconds to at least"
                            f" {_MIN_GRACE_PERIOD} to give running requests"
                            " time to complete before the pod is killed."
                        ),
                        evidence_locator=f"{file_path}:{resource_name}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="graceful-shutdown",
                    )
                )

        if not findings:
            first = k8s_resources[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        "All containers have preStop hooks and"
                        " terminationGracePeriodSeconds >= "
                        f"{_MIN_GRACE_PERIOD}."
                    ),
                    recommendation="No action required — graceful shutdown is configured.",
                    evidence_locator="all-workloads",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.9,
                    pattern_tag="graceful-shutdown",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "PATCH-ARCH-002" not in rule_registry:
        rule_registry.register("PATCH-ARCH-002", GracefulShutdownMissingRule())


_register()

__all__ = ["GracefulShutdownMissingRule"]
