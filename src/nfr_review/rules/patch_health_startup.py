# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-HEALTH-003 — startup probe presence for patching safety.

Checks that workloads with multiple replicas have a startupProbe configured.

* DaemonSet resources: always GREEN — startup probes are less critical for DaemonSets
  because they do not participate in rolling-update traffic shifting the same way.
* Multi-replica workloads (replicas > 1): AMBER if startup probe missing — slow-starting
  containers without a startup probe risk being killed by liveness probes before reaching
  readiness during a rolling update.
* Singleton workloads (replicas <= 1): GREEN with informational note — lower risk.
* GREEN if startup probe is present.
* SKIPPED when no k8s-resource evidence is available.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_WORKLOAD_KINDS = {"Deployment", "StatefulSet"}


class StartupProbeMissingRule:
    """Check startup probe presence in the context of patching safety."""

    id = "PATCH-HEALTH-003"
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
            resource_kind = ev.payload.get("kind", "")
            resource_name = ev.payload.get("name", "")
            file_path = ev.payload.get("file_path", ev.locator)

            # DaemonSets are explicitly GREEN — startup probes less critical
            if resource_kind == "DaemonSet":
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(
                            f"DaemonSet '{resource_name}' — startup probe check"
                            " not applicable for DaemonSets."
                        ),
                        recommendation=(
                            "No action required — DaemonSets do not participate"
                            " in replica-based rolling updates."
                        ),
                        evidence_locator=f"{file_path}:{resource_name}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="patch-health-startup",
                    )
                )
                continue

            if resource_kind not in _WORKLOAD_KINDS:
                continue

            replicas = ev.payload.get("replicas")
            is_multi_replica = replicas is not None and replicas > 1

            for container in ev.payload.get("containers", []):
                container_name = container.get("name", "")
                has_startup_probe = container.get("startup_probe") is not None
                locator = f"{file_path}:{resource_name}:{container_name}"

                if has_startup_probe:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="green",
                            severity="info",
                            summary=(
                                f"Container '{container_name}' in"
                                f" {resource_kind} '{resource_name}'"
                                " has a startupProbe configured."
                            ),
                            recommendation=("No action required — startup probe is present."),
                            evidence_locator=locator,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.95,
                            pattern_tag="patch-health-startup",
                        )
                    )
                elif is_multi_replica:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="high",
                            summary=(
                                f"Container '{container_name}' in"
                                f" {resource_kind} '{resource_name}'"
                                f" ({replicas} replicas) has no startupProbe."
                                " Slow-starting containers risk being killed by"
                                " liveness probes before reaching readiness"
                                " during rolling updates."
                            ),
                            recommendation=(
                                "Add a startupProbe to protect slow-starting"
                                " containers from premature liveness-probe"
                                " termination. The kubelet will not run liveness"
                                " or readiness checks until the startup probe"
                                " succeeds, giving the container time to"
                                " initialise safely during rolling updates."
                            ),
                            evidence_locator=locator,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="patch-health-startup",
                        )
                    )
                else:
                    # Singleton workload — lower risk, informational green
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="green",
                            severity="info",
                            summary=(
                                f"Container '{container_name}' in"
                                f" {resource_kind} '{resource_name}'"
                                " (singleton) has no startupProbe. Lower risk"
                                " for single-replica workloads."
                            ),
                            recommendation=(
                                "Consider adding a startupProbe if the container"
                                " has a slow initialisation phase, to prevent"
                                " premature liveness-probe termination."
                            ),
                            evidence_locator=locator,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.80,
                            pattern_tag="patch-health-startup",
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
                        "No Deployment/StatefulSet/DaemonSet workloads to check"
                        " for startup probes."
                    ),
                    recommendation="No action required.",
                    evidence_locator="all-workloads",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.90,
                    pattern_tag="patch-health-startup",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "PATCH-HEALTH-003" not in rule_registry:
        rule_registry.register("PATCH-HEALTH-003", StartupProbeMissingRule())


_register()

__all__ = ["StartupProbeMissingRule"]
