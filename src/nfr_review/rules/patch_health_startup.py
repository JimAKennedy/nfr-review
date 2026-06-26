# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-HEALTH-003 -- startup probe presence for patching safety.

Checks that workloads with multiple replicas have a startupProbe configured.

* DaemonSet resources: skipped -- startup probes are less critical for DaemonSets
  because they do not participate in rolling-update traffic shifting the same way.
* Multi-replica workloads (replicas > 1): AMBER if startup probe missing -- slow-starting
  containers without a startup probe risk being killed by liveness probes before reaching
  readiness during a rolling update.
* Singleton workloads (replicas <= 1): no hit -- lower risk.
* No hit if startup probe is present (base class handles all-clear).
* SKIPPED when no k8s-resource evidence is available.
"""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.k8s import K8sResourcePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_WORKLOAD_KINDS = {"Deployment", "StatefulSet"}


class StartupProbeMissingRule(FieldRule[K8sResourcePayload]):
    """Check startup probe presence in the context of patching safety."""

    id = "PATCH-HEALTH-003"
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-resource"
    payload_type = K8sResourcePayload
    pattern_tag = "patch-health-startup"
    default_confidence = 0.85
    all_clear_summary = "All containers have startup probes for patching safety."
    all_clear_recommendation = "No action required -- startup probes are present."

    def check(self, payload: K8sResourcePayload, ev: Evidence) -> Iterable[Hit]:
        # DaemonSets -- startup probes less critical; skip.
        if payload.kind == "DaemonSet":
            return

        if payload.kind not in _WORKLOAD_KINDS:
            return

        is_multi_replica = payload.replicas is not None and payload.replicas > 1

        for container in payload.containers:
            has_startup_probe = container.startup_probe is not None

            if not has_startup_probe and is_multi_replica:
                yield Hit(
                    rag="amber",
                    severity="high",
                    summary=(
                        f"Container '{container.name}' in"
                        f" {payload.kind} '{payload.name}'"
                        f" ({payload.replicas} replicas) has no startupProbe."
                        " Slow-starting containers risk being killed by"
                        " liveness probes before reaching readiness"
                        " during rolling updates."
                    ),
                    recommendation=(
                        "Add a startupProbe to protect slow-starting"
                        " containers from premature liveness-probe"
                        " termination. The kubelet will not run liveness"
                        " or readiness checks until the startup probe"
                        " succeeds, giving the container time to"
                        " initialise safely during rolling updates."
                    ),
                    locator=f"{payload.file_path}:{payload.name}:{container.name}",
                )


__all__ = ["StartupProbeMissingRule"]
