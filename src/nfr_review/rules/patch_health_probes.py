# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-HEALTH-001 — readiness probe presence for patching safety.

Different from the generic 'probes-missing' rule: this rule evaluates probe
presence specifically in the context of safe patching/rolling-update behaviour.

* Multi-replica workloads (replicas > 1): RED if readiness probe missing —
  rolling updates will route traffic to unready pods.
* Singleton workloads (replicas <= 1 or unset): AMBER if readiness probe missing —
  lower blast radius but still a risk during restarts.
* GREEN if both probes present on a container.
* SKIPPED when no k8s-resource evidence is available.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_WORKLOAD_KINDS = {"Deployment", "StatefulSet"}


class PatchingProbePresenceRule:
    """Check readiness/liveness probes in the context of patching safety."""

    id = "PATCH-HEALTH-001"
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
            resource_kind = ev.payload.kind
            if resource_kind not in _WORKLOAD_KINDS:
                continue

            replicas = ev.payload.replicas
            is_multi_replica = replicas is not None and replicas > 1

            resource_name = ev.payload.name
            file_path = ev.payload.file_path

            for container in ev.payload.containers:
                container_name = container.get("name", "")
                has_liveness = container.get("liveness_probe") is not None
                has_readiness = container.get("readiness_probe") is not None

                if not has_readiness:
                    if is_multi_replica:
                        findings.append(
                            Finding(
                                rule_id=self.id,
                                rag="red",
                                severity="critical",
                                summary=(
                                    f"Container '{container_name}' in"
                                    f" {resource_kind} '{resource_name}'"
                                    f" ({replicas} replicas) has no readinessProbe."
                                    " Rolling updates will send traffic to unready pods."
                                ),
                                recommendation=(
                                    "Add a readinessProbe so that the kubelet"
                                    " only routes traffic to pods that are ready"
                                    " to serve. This is critical for safe rolling"
                                    " updates across multiple replicas."
                                ),
                                evidence_locator=(
                                    f"{file_path}:{resource_name}:{container_name}"
                                ),
                                collector_name=ev.collector_name,
                                collector_version=ev.collector_version,
                                confidence=0.95,
                                pattern_tag="patch-health-probes",
                            )
                        )
                    else:
                        findings.append(
                            Finding(
                                rule_id=self.id,
                                rag="amber",
                                severity="high",
                                summary=(
                                    f"Container '{container_name}' in"
                                    f" {resource_kind} '{resource_name}'"
                                    " (singleton) has no readinessProbe."
                                ),
                                recommendation=(
                                    "Add a readinessProbe to prevent traffic"
                                    " being routed to the pod before it is ready"
                                    " after a restart or patch."
                                ),
                                evidence_locator=(
                                    f"{file_path}:{resource_name}:{container_name}"
                                ),
                                collector_name=ev.collector_name,
                                collector_version=ev.collector_version,
                                confidence=0.90,
                                pattern_tag="patch-health-probes",
                            )
                        )
                elif has_readiness and has_liveness:
                    findings.append(
                        make_green_finding(
                            self.id,
                            "patch-health-probes",
                            ev,
                            summary=(
                                f"Container '{container_name}' in"
                                f" {resource_kind} '{resource_name}'"
                                " has both liveness and readiness probes."
                            ),
                            recommendation="No action required — probes are configured.",
                            confidence=0.95,
                            evidence_locator=f"{file_path}:{resource_name}:{container_name}",
                        )
                    )
                else:
                    # has_readiness but not has_liveness — readiness is the
                    # patching-critical probe, so still green from patching
                    # perspective (generic probes-missing rule covers the
                    # liveness gap).
                    findings.append(
                        make_green_finding(
                            self.id,
                            "patch-health-probes",
                            ev,
                            summary=(
                                f"Container '{container_name}' in"
                                f" {resource_kind} '{resource_name}'"
                                " has a readinessProbe (patching-safe)."
                            ),
                            recommendation=(
                                "Readiness probe is present — patching is safe."
                                " Consider adding a livenessProbe for full"
                                " health coverage."
                            ),
                            confidence=0.90,
                            evidence_locator=f"{file_path}:{resource_name}:{container_name}",
                        )
                    )

        if not findings:
            first = k8s_resources[0]
            findings.append(
                make_green_finding(
                    self.id,
                    "patch-health-probes",
                    first,
                    summary=(
                        "No Deployment/StatefulSet workloads to check for patching probes."
                    ),
                    confidence=0.90,
                    evidence_locator="all-workloads",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "PATCH-HEALTH-001" not in rule_registry:
        rule_registry.register("PATCH-HEALTH-001", PatchingProbePresenceRule())


_register()

__all__ = ["PatchingProbePresenceRule"]
