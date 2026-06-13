# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-ARCH-001 — detects singleton deployments (replicas==1 or None)."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_WORKLOAD_KINDS = {"Deployment", "StatefulSet"}
_SKIP_KINDS = {"DaemonSet"}


class SingletonDeploymentRule:
    """Flag Deployment/StatefulSet resources running with a single replica."""

    id = "PATCH-ARCH-001"
    band: Band = 1
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
            resource_kind = ev.payload.get("kind", "")
            resource_name = ev.payload.get("name", "")
            file_path = ev.payload.get("file_path", ev.locator)
            replicas = ev.payload.get("replicas")

            # DaemonSets run on every node — replica count is not applicable.
            if resource_kind in _SKIP_KINDS:
                continue

            # Only evaluate workload kinds that have a replica concept.
            if resource_kind not in _WORKLOAD_KINDS:
                continue

            if replicas is None or replicas == 1:
                reason = (
                    "replicas is not set (defaults to 1)"
                    if replicas is None
                    else "replicas is explicitly set to 1"
                )
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="critical",
                        summary=(
                            f"{resource_kind} '{resource_name}' is a singleton — {reason}."
                        ),
                        recommendation=(
                            "Set spec.replicas >= 2 to avoid a single point of"
                            " failure and enable rolling updates."
                        ),
                        evidence_locator=f"{file_path}:{resource_name}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="singleton-deployment",
                    )
                )
            else:
                findings.append(
                    make_green_finding(
                        self.id,
                        "singleton-deployment",
                        ev,
                        summary=(
                            f"{resource_kind} '{resource_name}' has {replicas} replicas."
                        ),
                        recommendation="No action required — replicas > 1.",
                        confidence=0.95,
                        evidence_locator=f"{file_path}:{resource_name}",
                    )
                )

        if not findings:
            # All resources were DaemonSets or non-workload kinds.
            first = k8s_resources[0]
            findings.append(
                make_green_finding(
                    self.id,
                    "singleton-deployment",
                    first,
                    summary="No Deployment/StatefulSet resources to check.",
                    confidence=0.90,
                    evidence_locator="all-workloads",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "PATCH-ARCH-001" not in rule_registry:
        rule_registry.register("PATCH-ARCH-001", SingletonDeploymentRule())


_register()

__all__ = ["SingletonDeploymentRule"]
