# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""PATCH-TRAFFIC rules — traffic management readiness for safe patching.

PATCH-TRAFFIC-001: Progressive traffic shifting detection.
    GREEN  if VirtualService weighted routing or Rollout canary steps present.
    AMBER  if service-mesh evidence exists but no progressive shifting detected.
    SKIPPED when no service-mesh evidence available.

PATCH-TRAFFIC-002: Failover documentation detection.
    GREEN  if failover/DR documentation found in repo root.
    AMBER  if none detected.
    SKIPPED when no repo-structure-summary evidence available.

PATCH-TRAFFIC-003: Connection draining configuration.
    GREEN  if DestinationRule connectionPool configured.
    AMBER  if service-mesh evidence exists but no connection pool detected.
    SKIPPED when no service-mesh evidence available.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class ProgressiveTrafficShiftingRule:
    """PATCH-TRAFFIC-001: detect progressive traffic shifting config."""

    id = "PATCH-TRAFFIC-001"
    band: Band = 1
    required_collectors: list[str] = ["service-mesh"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        vs_evidence = [
            e
            for e in evidence
            if e.collector_name == "service-mesh" and e.kind == "service-mesh-virtual-service"
        ]
        rollout_evidence = [
            e
            for e in evidence
            if e.collector_name == "service-mesh" and e.kind == "service-mesh-rollout"
        ]
        summary = [
            e
            for e in evidence
            if e.collector_name == "service-mesh" and e.kind == "service-mesh-summary"
        ]

        if not summary:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no service-mesh evidence available",
            )

        findings: list[Finding] = []

        for ev in vs_evidence:
            name = ev.payload.get("name", "")
            if ev.payload.get("has_weighted_routing"):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(f"VirtualService '{name}' has weighted traffic routing"),
                        recommendation=(
                            "No action required — progressive traffic shifting is configured."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="patch-traffic-shifting",
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"VirtualService '{name}' has no weighted traffic"
                            " routing — all traffic goes to a single destination"
                        ),
                        recommendation=(
                            "Add weight-based routing to the VirtualService so"
                            " traffic can be shifted progressively during deployments."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="patch-traffic-shifting",
                    )
                )

        for ev in rollout_evidence:
            name = ev.payload.get("name", "")
            steps = ev.payload.get("canary_steps") or []
            strategy = ev.payload.get("strategy_type", "unknown")
            if strategy == "canary" and len(steps) > 0:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(
                            f"Rollout '{name}' has canary steps for progressive"
                            f" traffic shifting ({len(steps)} steps)"
                        ),
                        recommendation=(
                            "No action required — canary rollout steps are configured."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="patch-traffic-shifting",
                    )
                )
            elif strategy == "canary":
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Rollout '{name}' uses canary strategy but has no"
                            " progressive steps defined"
                        ),
                        recommendation=(
                            "Add canary steps with setWeight and pause to"
                            " enable progressive traffic shifting."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="patch-traffic-shifting",
                    )
                )

        if not findings:
            sm = summary[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        "No VirtualService or Rollout resources found"
                        " — progressive traffic shifting not applicable"
                    ),
                    recommendation="No action required.",
                    evidence_locator=".",
                    collector_name=sm.collector_name,
                    collector_version=sm.collector_version,
                    confidence=0.80,
                    pattern_tag="patch-traffic-shifting",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


_FAILOVER_FILES = {
    "failover.md",
    "disaster-recovery.md",
    "dr-runbook.md",
    "failover-runbook.md",
}
_FAILOVER_DIRS = {"failover", "disaster-recovery", "dr-runbooks"}


def _has_k8s_workloads(evidence: list[Evidence]) -> bool:
    return any(
        (e.collector_name == "k8s-manifest" and e.kind == "k8s-resource")
        or e.kind == "patch-config"
        for e in evidence
    )


class FailoverDocumentationRule:
    """PATCH-TRAFFIC-002: detect failover/DR documentation in repo root."""

    id = "PATCH-TRAFFIC-002"
    band: Band = 1
    required_collectors: list[str] = ["repo-structure"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        summaries = [
            e
            for e in evidence
            if e.collector_name == "repo-structure" and e.kind == "repo-structure-summary"
        ]
        if not summaries:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no repo-structure-summary evidence available",
            )

        if not _has_k8s_workloads(evidence):
            ev = summaries[0]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(
                            "No K8s workloads or patching config detected"
                            " — failover docs check not applicable"
                        ),
                        recommendation="No action required.",
                        evidence_locator="repo-root",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.80,
                        pattern_tag="patch-traffic-failover-docs",
                    )
                ],
            )

        ev = summaries[0]
        top_files: list[str] = ev.payload.get("top_level_files", [])
        top_dirs: list[str] = ev.payload.get("top_level_dirs", [])

        matched: list[str] = []

        for f in top_files:
            if f.lower() in _FAILOVER_FILES:
                matched.append(f)

        for d in top_dirs:
            if d.lower() in _FAILOVER_DIRS:
                matched.append(d)

        findings: list[Finding] = []

        if not matched:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary="No failover or disaster-recovery documentation detected",
                    recommendation=(
                        "Add a failover.md or disaster-recovery.md at the repo"
                        " root, or create a failover/ or dr-runbooks/ directory"
                        " with failover procedures."
                    ),
                    evidence_locator="repo-root",
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.85,
                    pattern_tag="patch-traffic-failover-docs",
                )
            )
        else:
            for name in matched:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=f"Failover documentation found: {name}",
                        recommendation=(
                            "No action required — failover documentation is present."
                        ),
                        evidence_locator=name,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.90,
                        pattern_tag="patch-traffic-failover-docs",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


class ConnectionDrainingRule:
    """PATCH-TRAFFIC-003: detect connection draining configuration."""

    id = "PATCH-TRAFFIC-003"
    band: Band = 1
    required_collectors: list[str] = ["service-mesh"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        dr_evidence = [
            e
            for e in evidence
            if e.collector_name == "service-mesh" and e.kind == "service-mesh-destination-rule"
        ]
        summary = [
            e
            for e in evidence
            if e.collector_name == "service-mesh" and e.kind == "service-mesh-summary"
        ]

        if not summary:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no service-mesh evidence available",
            )

        findings: list[Finding] = []

        for ev in dr_evidence:
            name = ev.payload.get("name", "")
            if ev.payload.get("has_connection_pool"):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(
                            f"DestinationRule '{name}' has connectionPool"
                            " configured for connection draining"
                        ),
                        recommendation=(
                            "No action required — connection pool limits are configured."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.90,
                        pattern_tag="patch-traffic-drain",
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"DestinationRule '{name}' has no connectionPool"
                            " — connection draining is not configured"
                        ),
                        recommendation=(
                            "Add a connectionPool section to the DestinationRule"
                            " trafficPolicy to control connection limits and"
                            " enable graceful draining during deployments."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="patch-traffic-drain",
                    )
                )

        if not findings:
            sm = summary[0]
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        "No DestinationRule resources found"
                        " — connection draining check not applicable"
                    ),
                    recommendation="No action required.",
                    evidence_locator=".",
                    collector_name=sm.collector_name,
                    collector_version=sm.collector_version,
                    confidence=0.80,
                    pattern_tag="patch-traffic-drain",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    for rule_cls in (
        ProgressiveTrafficShiftingRule,
        FailoverDocumentationRule,
        ConnectionDrainingRule,
    ):
        rule = rule_cls()
        if rule.id not in rule_registry:
            rule_registry.register(rule.id, rule)


_register()

__all__ = [
    "ProgressiveTrafficShiftingRule",
    "FailoverDocumentationRule",
    "ConnectionDrainingRule",
]
