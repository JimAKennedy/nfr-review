# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: probes-missing -- checks K8s workload containers for liveness/readiness probes."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.k8s import K8sResourcePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class ProbesMissingRule(FieldRule[K8sResourcePayload]):
    """Flag containers missing livenessProbe or readinessProbe."""

    id = "probes-missing"
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-resource"
    payload_type = K8sResourcePayload
    pattern_tag = "k8s-probes"
    required_tech: list[str] = ["kubernetes"]
    default_confidence = 0.95
    all_clear_summary = "All containers have liveness and readiness probes."
    all_clear_recommendation = "No action required -- probes are configured."

    def check(self, payload: K8sResourcePayload, ev: Evidence) -> Iterable[Hit]:
        for container in payload.containers:
            has_liveness = container.liveness_probe is not None
            has_readiness = container.readiness_probe is not None

            if not has_liveness or not has_readiness:
                missing = []
                if not has_liveness:
                    missing.append("livenessProbe")
                if not has_readiness:
                    missing.append("readinessProbe")
                yield Hit(
                    rag="amber",
                    severity="high",
                    summary=(
                        f"Container '{container.name}' in"
                        f" {payload.name} is missing"
                        f" {', '.join(missing)}."
                    ),
                    recommendation=(
                        "Define both livenessProbe and readinessProbe"
                        " to enable Kubernetes health management and"
                        " zero-downtime deployments."
                    ),
                    locator=f"{payload.file_path}:{payload.name}:{container.name}",
                )


__all__ = ["ProbesMissingRule"]
