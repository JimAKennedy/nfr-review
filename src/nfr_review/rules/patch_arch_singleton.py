# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-ARCH-001 -- detects singleton deployments (replicas==1 or None)."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.k8s import K8sResourcePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_WORKLOAD_KINDS = {"Deployment", "StatefulSet"}
_SKIP_KINDS = {"DaemonSet"}


class SingletonDeploymentRule(FieldRule[K8sResourcePayload]):
    """Flag Deployment/StatefulSet resources running with a single replica."""

    id = "PATCH-ARCH-001"
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-resource"
    payload_type = K8sResourcePayload
    pattern_tag = "singleton-deployment"
    default_confidence = 0.95
    all_clear_summary = "No singleton Deployment/StatefulSet resources found."
    all_clear_recommendation = "No action required -- replicas > 1."

    def check(self, payload: K8sResourcePayload, ev: Evidence) -> Iterable[Hit]:
        # DaemonSets run on every node -- replica count is not applicable.
        if payload.kind in _SKIP_KINDS:
            return

        # Only evaluate workload kinds that have a replica concept.
        if payload.kind not in _WORKLOAD_KINDS:
            return

        if payload.replicas is None or payload.replicas == 1:
            reason = (
                "replicas is not set (defaults to 1)"
                if payload.replicas is None
                else "replicas is explicitly set to 1"
            )
            yield Hit(
                rag="red",
                severity="critical",
                summary=(f"{payload.kind} '{payload.name}' is a singleton -- {reason}."),
                recommendation=(
                    "Set spec.replicas >= 2 to avoid a single point of"
                    " failure and enable rolling updates."
                ),
                locator=f"{payload.file_path}:{payload.name}",
            )


__all__ = ["SingletonDeploymentRule"]
