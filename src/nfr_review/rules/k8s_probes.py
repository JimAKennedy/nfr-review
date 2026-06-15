# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: probes-missing — checks K8s workload containers for liveness/readiness probes."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class ProbesMissingRule:
    """Flag containers missing livenessProbe or readinessProbe."""

    id = "probes-missing"
    band: Band = 1
    required_tech: list[str] = ["kubernetes"]
    required_collectors: list[str] = ["k8s-manifest"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        k8s_resources = filter_evidence(evidence, "k8s-manifest", "k8s-resource")
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
                has_liveness = container.get("liveness_probe") is not None
                has_readiness = container.get("readiness_probe") is not None

                if not has_liveness or not has_readiness:
                    missing = []
                    if not has_liveness:
                        missing.append("livenessProbe")
                    if not has_readiness:
                        missing.append("readinessProbe")
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="high",
                            summary=(
                                f"Container '{container_name}' in"
                                f" {resource_name} is missing"
                                f" {', '.join(missing)}."
                            ),
                            recommendation=(
                                "Define both livenessProbe and readinessProbe"
                                " to enable Kubernetes health management and"
                                " zero-downtime deployments."
                            ),
                            evidence_locator=(f"{file_path}:{resource_name}:{container_name}"),
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.95,
                            pattern_tag="k8s-probes",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "k8s-probes",
                    k8s_resources[0],
                    summary="All containers have liveness and readiness probes.",
                    recommendation="No action required — probes are configured.",
                    confidence=0.95,
                    evidence_locator="all-workloads",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "probes-missing" not in rule_registry:
        rule_registry.register("probes-missing", ProbesMissingRule())


_register()

__all__ = ["ProbesMissingRule"]
