# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-HEALTH-002 — detects trivial or fragile readiness probe configurations."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class TrivialProbeRule:
    """Flag readiness probes that are likely trivial or overly fragile during patching.

    Detects three anti-patterns:
    (a) tcpSocket-only readiness probe without httpGet — checks port open, not app health.
    (b) Very short initialDelaySeconds (<5) combined with very short periodSeconds (<5).
    (c) failureThreshold == 1 — single failure kills pod during patch.
    """

    id = "PATCH-HEALTH-002"
    band: Band = 2
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
        probes_checked = 0

        for ev in k8s_resources:
            resource_name = ev.payload.get("name", "")
            file_path = ev.payload.get("file_path", ev.locator)
            for container in ev.payload.get("containers", []):
                container_name = container.get("name", "")
                readiness_probe = container.get("readiness_probe")
                if readiness_probe is None:
                    # No readiness probe configured — probes-missing rule covers this.
                    continue

                probes_checked += 1
                locator = f"{file_path}:{resource_name}:{container_name}"

                # (a) tcpSocket-only readiness probe without httpGet
                has_tcp_socket = readiness_probe.get("tcpSocket") is not None
                has_http_get = readiness_probe.get("httpGet") is not None
                if has_tcp_socket and not has_http_get:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Container '{container_name}' in {resource_name}"
                                " uses a tcpSocket-only readiness probe. This only"
                                " confirms the port is open, not that the application"
                                " is ready to serve traffic."
                            ),
                            recommendation=(
                                "Replace the tcpSocket readiness probe with an"
                                " httpGet probe that exercises the application's"
                                " health endpoint (e.g. /healthz or /readyz) to"
                                " verify genuine readiness before receiving traffic"
                                " during rolling updates."
                            ),
                            evidence_locator=locator,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="trivial-probe",
                        )
                    )

                # (b) Very short initialDelaySeconds (<5) + periodSeconds (<5)
                initial_delay = readiness_probe.get("initialDelaySeconds", 0)
                period = readiness_probe.get("periodSeconds", 10)  # K8s default is 10
                if initial_delay < 5 and period < 5:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Container '{container_name}' in {resource_name}"
                                f" has aggressive probe timing"
                                f" (initialDelaySeconds={initial_delay},"
                                f" periodSeconds={period}). This may cause premature"
                                " readiness or excessive load during startup."
                            ),
                            recommendation=(
                                "Increase initialDelaySeconds to at least 5 and"
                                " periodSeconds to at least 5 to give the application"
                                " time to initialise and avoid overwhelming it with"
                                " health checks during rolling updates."
                            ),
                            evidence_locator=locator,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.80,
                            pattern_tag="trivial-probe",
                        )
                    )

                # (c) failureThreshold == 1 — single failure kills pod during patch
                failure_threshold = readiness_probe.get(
                    "failureThreshold", 3
                )  # K8s default is 3
                if failure_threshold == 1:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Container '{container_name}' in {resource_name}"
                                " has failureThreshold=1 on the readiness probe."
                                " A single transient failure will remove the pod"
                                " from service endpoints."
                            ),
                            recommendation=(
                                "Set failureThreshold to at least 2 (preferably 3)"
                                " so that a brief network hiccup or garbage-collection"
                                " pause does not immediately pull the pod out of"
                                " the load balancer during a rolling update."
                            ),
                            evidence_locator=locator,
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.85,
                            pattern_tag="trivial-probe",
                        )
                    )

        if probes_checked == 0:
            # All containers lack readiness probes — skip (probes-missing handles this).
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no readiness probes configured on any container",
            )

        if not findings:
            first = k8s_resources[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="All readiness probes pass trivial-probe quality checks.",
                    recommendation="No action required — probes are well-configured.",
                    evidence_locator="all-workloads",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.85,
                    pattern_tag="trivial-probe",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "PATCH-HEALTH-002" not in rule_registry:
        rule_registry.register("PATCH-HEALTH-002", TrivialProbeRule())


_register()

__all__ = ["TrivialProbeRule"]
