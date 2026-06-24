# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-ARCH-002 -- checks K8s workloads for graceful shutdown configuration."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.k8s import K8sResourcePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_MIN_GRACE_PERIOD = 30


class GracefulShutdownMissingRule(FieldRule[K8sResourcePayload]):
    """Flag workloads missing preStop hooks or insufficient grace period."""

    id = "PATCH-ARCH-002"
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-resource"
    payload_type = K8sResourcePayload
    pattern_tag = "graceful-shutdown"
    default_confidence = 0.9
    all_clear_summary = (
        "All containers have preStop hooks and"
        f" terminationGracePeriodSeconds >= {_MIN_GRACE_PERIOD}."
    )
    all_clear_recommendation = "No action required -- graceful shutdown is configured."

    def check(self, payload: K8sResourcePayload, ev: Evidence) -> Iterable[Hit]:
        # Check each container for preStop lifecycle hook
        for container in payload.containers:
            if container.pre_stop is None:
                yield Hit(
                    rag="amber",
                    summary=(
                        f"Container '{container.name}' in"
                        f" {payload.name} is missing a"
                        f" preStop lifecycle hook."
                    ),
                    recommendation=(
                        "Define a preStop lifecycle hook (e.g. an exec"
                        " command or HTTP GET) to allow in-flight"
                        " requests to drain before SIGTERM is sent."
                    ),
                    locator=f"{payload.file_path}:{payload.name}:{container.name}",
                )

        # Check terminationGracePeriodSeconds at the workload level
        grace_period = payload.termination_grace_period
        if grace_period is None or grace_period < _MIN_GRACE_PERIOD:
            period_display = (
                "not set (defaults to 30s)" if grace_period is None else f"{grace_period}s"
            )
            yield Hit(
                rag="amber",
                summary=(
                    f"Workload {payload.name} has"
                    f" terminationGracePeriodSeconds {period_display},"
                    f" which may be insufficient for graceful shutdown."
                ),
                recommendation=(
                    "Set terminationGracePeriodSeconds to at least"
                    f" {_MIN_GRACE_PERIOD} to give running requests"
                    " time to complete before the pod is killed."
                ),
                locator=f"{payload.file_path}:{payload.name}",
                confidence=0.85,
            )


__all__ = ["GracefulShutdownMissingRule"]
