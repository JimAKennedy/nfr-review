# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-HEALTH-001 -- readiness probe presence for patching safety.

Different from the generic 'probes-missing' rule: this rule evaluates probe
presence specifically in the context of safe patching/rolling-update behaviour.

* Multi-replica workloads (replicas > 1): RED if readiness probe missing --
  rolling updates will route traffic to unready pods.
* Singleton workloads (replicas <= 1 or unset): AMBER if readiness probe missing --
  lower blast radius but still a risk during restarts.
* No hit if probes are present (base class handles all-clear).
* SKIPPED when no k8s-resource evidence is available.
"""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.k8s import K8sResourcePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_WORKLOAD_KINDS = {"Deployment", "StatefulSet"}


class PatchingProbePresenceRule(FieldRule[K8sResourcePayload]):
    """Check readiness/liveness probes in the context of patching safety."""

    id = "PATCH-HEALTH-001"
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-resource"
    payload_type = K8sResourcePayload
    pattern_tag = "patch-health-probes"
    default_confidence = 0.95
    all_clear_summary = "All containers have readiness probes for patching safety."
    all_clear_recommendation = "No action required -- probes are configured."

    def check(self, payload: K8sResourcePayload, ev: Evidence) -> Iterable[Hit]:
        if payload.kind not in _WORKLOAD_KINDS:
            return

        is_multi_replica = payload.replicas is not None and payload.replicas > 1

        for container in payload.containers:
            has_readiness = container.readiness_probe is not None

            if not has_readiness:
                if is_multi_replica:
                    yield Hit(
                        rag="red",
                        severity="critical",
                        summary=(
                            f"Container '{container.name}' in"
                            f" {payload.kind} '{payload.name}'"
                            f" ({payload.replicas} replicas) has no readinessProbe."
                            " Rolling updates will send traffic to unready pods."
                        ),
                        recommendation=(
                            "Add a readinessProbe so that the kubelet"
                            " only routes traffic to pods that are ready"
                            " to serve. This is critical for safe rolling"
                            " updates across multiple replicas."
                        ),
                        locator=f"{payload.file_path}:{payload.name}:{container.name}",
                    )
                else:
                    yield Hit(
                        rag="amber",
                        severity="high",
                        summary=(
                            f"Container '{container.name}' in"
                            f" {payload.kind} '{payload.name}'"
                            " (singleton) has no readinessProbe."
                        ),
                        recommendation=(
                            "Add a readinessProbe to prevent traffic"
                            " being routed to the pod before it is ready"
                            " after a restart or patch."
                        ),
                        locator=f"{payload.file_path}:{payload.name}:{container.name}",
                        confidence=0.90,
                    )


__all__ = ["PatchingProbePresenceRule"]
