# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: health-probe-separation — flags K8s containers where liveness and readiness
probes are configured identically, defeating the purpose of having two separate probes.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


def _probes_identical(liveness: dict[str, Any], readiness: dict[str, Any]) -> bool:
    """Return True if the two probe dicts are structurally identical."""
    return liveness == readiness


class HealthProbeSeparationRule:
    """Flag containers whose liveness and readiness probes are configured identically."""

    id = "health-probe-separation"
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
            resource_name = ev.payload.name
            file_path = ev.payload.file_path

            for container in ev.payload.containers:
                container_name = container.get("name", "")
                liveness = container.get("liveness_probe")
                readiness = container.get("readiness_probe")

                # Only flag when BOTH probes exist AND they are identical.
                if liveness is None or readiness is None:
                    continue

                if _probes_identical(liveness, readiness):
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Container '{container_name}' in {resource_name}"
                                " has identical liveness and readiness probes."
                                " Traffic may be dropped during slow startup."
                            ),
                            recommendation=(
                                "Use a dedicated readinessProbe path/command that"
                                " confirms the service is ready to handle traffic"
                                " (e.g., /readyz), and a livenessProbe that checks"
                                " only that the process is alive (e.g., /livez)."
                                " Identical probes prevent Kubernetes from"
                                " distinguishing restart-worthy crashes from"
                                " temporarily-unready instances."
                            ),
                            evidence_locator=(f"{file_path}:{resource_name}:{container_name}"),
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="k8s-probe-separation",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "k8s-probe-separation",
                    k8s_resources[0],
                    summary=(
                        "All containers have distinct liveness and readiness probes"
                        " (or only one probe type is defined)."
                    ),
                    confidence=0.9,
                    evidence_locator="all-workloads",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "health-probe-separation" not in rule_registry:
        rule_registry.register("health-probe-separation", HealthProbeSeparationRule())


_register()

__all__ = ["HealthProbeSeparationRule"]
