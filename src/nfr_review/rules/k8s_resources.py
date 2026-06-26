# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: resource-limits-missing -- checks K8s workload containers for resource limits."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.k8s import K8sResourcePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class ResourceLimitsMissingRule(FieldRule[K8sResourcePayload]):
    """Flag containers that do not define resources.limits."""

    id = "resource-limits-missing"
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-resource"
    payload_type = K8sResourcePayload
    pattern_tag = "k8s-resource-limits"
    required_tech: list[str] = ["kubernetes"]
    default_confidence = 0.95
    all_clear_summary = "All containers have resource limits defined."
    all_clear_recommendation = "No action required -- resource limits are present."

    def check(self, payload: K8sResourcePayload, ev: Evidence) -> Iterable[Hit]:
        for container in payload.containers:
            has_limits = isinstance(container.resources, dict) and bool(
                container.resources.get("limits")
            )
            if not has_limits:
                yield Hit(
                    rag="amber",
                    severity="high",
                    summary=(
                        f"Container '{container.name}' in"
                        f" {payload.name} has no resource limits."
                    ),
                    recommendation=(
                        "Define resources.limits (cpu and memory)"
                        " to prevent unbounded resource consumption"
                        " and ensure fair scheduling."
                    ),
                    locator=f"{payload.file_path}:{payload.name}:{container.name}",
                )


__all__ = ["ResourceLimitsMissingRule"]
