# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-ARCH-003 -- checks K8s workloads for safe update strategy."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from nfr_review.collectors.payloads.k8s import K8sResourcePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

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


class UpdateStrategyRule(FieldRule[K8sResourcePayload]):
    """Flag workloads with missing or unsafe update/rollout strategy."""

    id = "PATCH-ARCH-003"
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-resource"
    payload_type = K8sResourcePayload
    pattern_tag = "update-strategy"
    default_confidence = 0.90
    all_clear_summary = "No Deployment/StatefulSet update strategy issues found."
    all_clear_recommendation = "No action required -- update strategy is safe."

    def check(self, payload: K8sResourcePayload, ev: Evidence) -> Iterable[Hit]:
        # DaemonSets have their own update patterns -- skip.
        if payload.kind in _SKIP_KINDS:
            return

        if payload.kind == "Deployment":
            yield from self._check_deployment(payload)
        elif payload.kind == "StatefulSet":
            yield from self._check_statefulset(payload)

    # ------------------------------------------------------------------
    # Deployment checks
    # ------------------------------------------------------------------

    def _check_deployment(self, payload: K8sResourcePayload) -> Iterable[Hit]:
        strategy = payload.strategy

        if strategy is None:
            yield Hit(
                rag="amber",
                summary=(
                    f"Deployment '{payload.name}' has no explicit strategy"
                    " (defaults to RollingUpdate)."
                ),
                recommendation=(
                    "Explicitly set spec.strategy.type to RollingUpdate with"
                    " appropriate maxUnavailable / maxSurge values."
                ),
                locator=f"{payload.file_path}:{payload.name}",
                confidence=0.85,
            )
            return

        strategy_type = strategy.get("type") if isinstance(strategy, dict) else strategy

        if strategy_type == "Recreate":
            yield Hit(
                rag="amber",
                summary=(
                    f"Deployment '{payload.name}' uses Recreate strategy,"
                    " which causes downtime during updates."
                ),
                recommendation=(
                    "Switch to RollingUpdate strategy to avoid downtime"
                    " during deployments unless Recreate is intentional"
                    " (e.g. for exclusive resource access)."
                ),
                locator=f"{payload.file_path}:{payload.name}",
            )
            return

        if strategy_type == "RollingUpdate":
            rolling = strategy.get("rollingUpdate", {}) if isinstance(strategy, dict) else {}
            max_unavailable = rolling.get("maxUnavailable") if rolling else None
            is_safe, desc = _parse_max_unavailable(max_unavailable)

            if not is_safe:
                yield Hit(
                    rag="amber",
                    summary=(
                        f"Deployment '{payload.name}' uses RollingUpdate"
                        f" but maxUnavailable={desc} is high."
                    ),
                    recommendation=(
                        "Reduce maxUnavailable to 25% or 1 to limit"
                        " disruption during rolling updates."
                    ),
                    locator=f"{payload.file_path}:{payload.name}",
                    confidence=0.85,
                )

    # ------------------------------------------------------------------
    # StatefulSet checks
    # ------------------------------------------------------------------

    def _check_statefulset(self, payload: K8sResourcePayload) -> Iterable[Hit]:
        update_strategy = payload.strategy

        if update_strategy is None:
            yield Hit(
                rag="amber",
                summary=(
                    f"StatefulSet '{payload.name}' has no explicit"
                    " updateStrategy (defaults to RollingUpdate)."
                ),
                recommendation=(
                    "Explicitly set spec.updateStrategy.type to RollingUpdate"
                    " for clarity and to avoid unexpected OnDelete behaviour"
                    " in older API versions."
                ),
                locator=f"{payload.file_path}:{payload.name}",
                confidence=0.80,
            )
            return

        strategy_type = (
            update_strategy.get("type")
            if isinstance(update_strategy, dict)
            else update_strategy
        )

        if strategy_type == "OnDelete":
            yield Hit(
                rag="amber",
                summary=(
                    f"StatefulSet '{payload.name}' uses OnDelete strategy,"
                    " requiring manual pod deletion to apply updates."
                ),
                recommendation=(
                    "Switch to RollingUpdate strategy for automated, ordinal"
                    " rolling updates unless OnDelete is intentional for"
                    " manual rollout control."
                ),
                locator=f"{payload.file_path}:{payload.name}",
                confidence=0.85,
            )


__all__ = ["UpdateStrategyRule"]
