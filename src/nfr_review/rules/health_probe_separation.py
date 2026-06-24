# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: health-probe-separation -- flags K8s containers where liveness and readiness
probes are configured identically, defeating the purpose of having two separate probes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from nfr_review.collectors.payloads.k8s import K8sResourcePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


def _probes_identical(liveness: dict[str, Any], readiness: dict[str, Any]) -> bool:
    """Return True if the two probe dicts are structurally identical."""
    return liveness == readiness


class HealthProbeSeparationRule(FieldRule[K8sResourcePayload]):
    """Flag containers whose liveness and readiness probes are configured identically."""

    id = "health-probe-separation"
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-resource"
    payload_type = K8sResourcePayload
    pattern_tag = "k8s-probe-separation"
    required_tech: list[str] = ["kubernetes"]
    default_confidence = 0.9
    all_clear_summary = (
        "All containers have distinct liveness and readiness probes"
        " (or only one probe type is defined)."
    )
    all_clear_recommendation = "No action required."

    def check(self, payload: K8sResourcePayload, ev: Evidence) -> Iterable[Hit]:
        for container in payload.containers:
            liveness = container.liveness_probe
            readiness = container.readiness_probe

            # Only flag when BOTH probes exist AND they are identical.
            if liveness is None or readiness is None:
                continue

            if _probes_identical(liveness, readiness):
                yield Hit(
                    rag="amber",
                    summary=(
                        f"Container '{container.name}' in {payload.name}"
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
                    locator=f"{payload.file_path}:{payload.name}:{container.name}",
                )


__all__ = ["HealthProbeSeparationRule"]
