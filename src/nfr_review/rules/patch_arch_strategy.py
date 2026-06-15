# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-ARCH-003 — checks K8s workloads for safe update strategy."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_SKIP_KINDS = {"DaemonSet"}


def _parse_max_unavailable(value: Any) -> tuple[bool, str]:
    """Return (is_safe, description) for a maxUnavailable value.

    Safe means <=25% or <=1 (absolute).
    """
    if value is None:
        # K8s default is 25% which is safe.
        return True, "not set (defaults to 25%)"

    if isinstance(value, int):
        return value <= 1, f"{value}"

    if isinstance(value, str):
        match = re.match(r"^(\d+)%$", value)
        if match:
            pct = int(match.group(1))
            return pct <= 25, value
        # Try parsing as integer string.
        try:
            int_val = int(value)
            return int_val <= 1, value
        except ValueError:
            return False, value

    return False, str(value)


class UpdateStrategyRule:
    """Flag workloads with missing or unsafe update/rollout strategy."""

    id = "PATCH-ARCH-003"
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

            # DaemonSets have their own update patterns — skip.
            if resource_kind in _SKIP_KINDS:
                continue

            if resource_kind == "Deployment":
                self._check_deployment(ev, resource_name, file_path, findings)
            elif resource_kind == "StatefulSet":
                self._check_statefulset(ev, resource_name, file_path, findings)

        if not findings:
            first = k8s_resources[0]
            findings.append(
                make_green_finding(
                    self.id,
                    "update-strategy",
                    first,
                    summary="No Deployment/StatefulSet update strategy issues found.",
                    confidence=0.90,
                    evidence_locator="all-workloads",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)

    # ------------------------------------------------------------------
    # Deployment checks
    # ------------------------------------------------------------------

    def _check_deployment(
        self,
        ev: Evidence,
        resource_name: str,
        file_path: str,
        findings: list[Finding],
    ) -> None:
        strategy = ev.payload.get("strategy")

        if strategy is None:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"Deployment '{resource_name}' has no explicit strategy"
                        " (defaults to RollingUpdate)."
                    ),
                    recommendation=(
                        "Explicitly set spec.strategy.type to RollingUpdate with"
                        " appropriate maxUnavailable / maxSurge values."
                    ),
                    evidence_locator=f"{file_path}:{resource_name}",
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.85,
                    pattern_tag="update-strategy",
                )
            )
            return

        strategy_type = strategy.get("type") if isinstance(strategy, dict) else strategy

        if strategy_type == "Recreate":
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"Deployment '{resource_name}' uses Recreate strategy,"
                        " which causes downtime during updates."
                    ),
                    recommendation=(
                        "Switch to RollingUpdate strategy to avoid downtime"
                        " during deployments unless Recreate is intentional"
                        " (e.g. for exclusive resource access)."
                    ),
                    evidence_locator=f"{file_path}:{resource_name}",
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.90,
                    pattern_tag="update-strategy",
                )
            )
            return

        if strategy_type == "RollingUpdate":
            rolling = strategy.get("rollingUpdate", {}) if isinstance(strategy, dict) else {}
            max_unavailable = rolling.get("maxUnavailable") if rolling else None
            is_safe, desc = _parse_max_unavailable(max_unavailable)

            if is_safe:
                findings.append(
                    make_green_finding(
                        self.id,
                        "update-strategy",
                        ev,
                        summary=(
                            f"Deployment '{resource_name}' uses RollingUpdate"
                            f" with maxUnavailable={desc}."
                        ),
                        recommendation="No action required — update strategy is safe.",
                        confidence=0.90,
                        evidence_locator=f"{file_path}:{resource_name}",
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Deployment '{resource_name}' uses RollingUpdate"
                            f" but maxUnavailable={desc} is high."
                        ),
                        recommendation=(
                            "Reduce maxUnavailable to 25% or 1 to limit"
                            " disruption during rolling updates."
                        ),
                        evidence_locator=f"{file_path}:{resource_name}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="update-strategy",
                    )
                )

    # ------------------------------------------------------------------
    # StatefulSet checks
    # ------------------------------------------------------------------

    def _check_statefulset(
        self,
        ev: Evidence,
        resource_name: str,
        file_path: str,
        findings: list[Finding],
    ) -> None:
        update_strategy = ev.payload.get("updateStrategy") or ev.payload.get("update_strategy")

        if update_strategy is None:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"StatefulSet '{resource_name}' has no explicit"
                        " updateStrategy (defaults to RollingUpdate)."
                    ),
                    recommendation=(
                        "Explicitly set spec.updateStrategy.type to RollingUpdate"
                        " for clarity and to avoid unexpected OnDelete behaviour"
                        " in older API versions."
                    ),
                    evidence_locator=f"{file_path}:{resource_name}",
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.80,
                    pattern_tag="update-strategy",
                )
            )
            return

        strategy_type = (
            update_strategy.get("type")
            if isinstance(update_strategy, dict)
            else update_strategy
        )

        if strategy_type == "OnDelete":
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"StatefulSet '{resource_name}' uses OnDelete strategy,"
                        " requiring manual pod deletion to apply updates."
                    ),
                    recommendation=(
                        "Switch to RollingUpdate strategy for automated, ordinal"
                        " rolling updates unless OnDelete is intentional for"
                        " manual rollout control."
                    ),
                    evidence_locator=f"{file_path}:{resource_name}",
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.85,
                    pattern_tag="update-strategy",
                )
            )
        elif strategy_type == "RollingUpdate":
            findings.append(
                make_green_finding(
                    self.id,
                    "update-strategy",
                    ev,
                    summary=(f"StatefulSet '{resource_name}' uses RollingUpdate strategy."),
                    recommendation="No action required — update strategy is safe.",
                    confidence=0.90,
                    evidence_locator=f"{file_path}:{resource_name}",
                )
            )


def _register() -> None:
    if "PATCH-ARCH-003" not in rule_registry:
        rule_registry.register("PATCH-ARCH-003", UpdateStrategyRule())


_register()

__all__ = ["UpdateStrategyRule"]
