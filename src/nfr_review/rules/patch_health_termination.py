"""Rule: PATCH-HEALTH-004 — checks terminationGracePeriodSeconds for patching safety."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_DEFAULT_GRACE_PERIOD = 30


class TerminationGracePeriodRule:
    """Flag workloads with insufficient termination grace period for safe patching.

    Checks:
    (a) Amber if terminationGracePeriodSeconds < 30 — insufficient time for connection
        draining during patch.
    (b) Amber if grace period is default (30) but no preStop hook exists on any
        container — no orderly shutdown signal.
    (c) Green if grace period >= 30 and at least one container has preStop configured.
    """

    id = "PATCH-HEALTH-004"
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
            containers = ev.payload.get("containers", [])

            # termination_grace_period is at the pod level
            grace_period = ev.payload.get("termination_grace_period", _DEFAULT_GRACE_PERIOD)

            # Check if any container has a preStop hook
            has_pre_stop = any(
                container.get("pre_stop") is not None for container in containers
            )

            locator = f"{file_path}:{resource_name}"

            if grace_period < _DEFAULT_GRACE_PERIOD:
                # (a) Grace period too low for safe connection draining
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Resource '{resource_name}' has"
                            f" terminationGracePeriodSeconds={grace_period} which is"
                            f" below the recommended minimum of {_DEFAULT_GRACE_PERIOD}."
                            " Connections may not drain fully during a rolling update."
                        ),
                        recommendation=(
                            "Increase terminationGracePeriodSeconds to at least 30"
                            " to allow in-flight requests to complete before the pod"
                            " is forcibly terminated during patching."
                        ),
                        evidence_locator=locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.90,
                        pattern_tag="patch-health-termination",
                    )
                )
            elif grace_period == _DEFAULT_GRACE_PERIOD and not has_pre_stop:
                # (b) Default grace period but no preStop — no orderly shutdown signal
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Resource '{resource_name}' uses the default"
                            f" terminationGracePeriodSeconds ({_DEFAULT_GRACE_PERIOD})"
                            " but no container defines a preStop hook. Without"
                            " preStop, the application receives only SIGTERM and may"
                            " not drain connections gracefully during patching."
                        ),
                        recommendation=(
                            "Add a preStop lifecycle hook (e.g. a short sleep or"
                            " endpoint call) to at least one container so that"
                            " in-flight requests complete before the pod is removed"
                            " from service endpoints."
                        ),
                        evidence_locator=locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="patch-health-termination",
                    )
                )
            elif grace_period >= _DEFAULT_GRACE_PERIOD and has_pre_stop:
                # (c) Good configuration — grace period sufficient and preStop present
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(
                            f"Resource '{resource_name}' has"
                            f" terminationGracePeriodSeconds={grace_period} and a"
                            " preStop hook configured — adequate for graceful shutdown"
                            " during patching."
                        ),
                        recommendation="No action required.",
                        evidence_locator=locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.90,
                        pattern_tag="patch-health-termination",
                    )
                )

        if not findings:
            # Edge case: resources found but none matched any condition
            first = k8s_resources[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=("All workloads pass termination grace period checks."),
                    recommendation="No action required.",
                    evidence_locator="all-workloads",
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.85,
                    pattern_tag="patch-health-termination",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "PATCH-HEALTH-004" not in rule_registry:
        rule_registry.register("PATCH-HEALTH-004", TerminationGracePeriodRule())


_register()

__all__ = ["TerminationGracePeriodRule"]
