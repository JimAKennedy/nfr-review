# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-HEALTH-002 -- detects trivial or fragile readiness probe configurations."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.k8s import K8sResourcePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class TrivialProbeRule(FieldRule[K8sResourcePayload]):
    """Flag readiness probes that are likely trivial or overly fragile during patching.

    Detects three anti-patterns:
    (a) tcpSocket-only readiness probe without httpGet -- checks port open, not app health.
    (b) Very short initialDelaySeconds (<5) combined with very short periodSeconds (<5).
    (c) failureThreshold == 1 -- single failure kills pod during patch.
    """

    id = "PATCH-HEALTH-002"
    band = 2
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-resource"
    payload_type = K8sResourcePayload
    pattern_tag = "trivial-probe"
    default_confidence = 0.85
    all_clear_summary = "All readiness probes pass trivial-probe quality checks."
    all_clear_recommendation = "No action required -- probes are well-configured."

    def check(self, payload: K8sResourcePayload, ev: Evidence) -> Iterable[Hit]:
        for container in payload.containers:
            readiness_probe = container.readiness_probe
            if readiness_probe is None:
                # No readiness probe configured -- probes-missing rule covers this.
                continue

            locator = f"{payload.file_path}:{payload.name}:{container.name}"

            # (a) tcpSocket-only readiness probe without httpGet
            has_tcp_socket = readiness_probe.get("tcpSocket") is not None
            has_http_get = readiness_probe.get("httpGet") is not None
            if has_tcp_socket and not has_http_get:
                yield Hit(
                    rag="amber",
                    summary=(
                        f"Container '{container.name}' in {payload.name}"
                        " uses a tcpSocket-only readiness probe. This only"
                        " confirms the port is open, not that the application"
                        " is ready to serve traffic."
                    ),
                    recommendation=(
                        "Replace the tcpSocket readiness probe with an"
                        " httpGet probe that exercises the application's"
                        " health endpoint (e.g. /healthz or /readyz) to"
                        " verify genuine readiness before receiving traffic"
                        " during rolling updates."
                    ),
                    locator=locator,
                )

            # (b) Very short initialDelaySeconds (<5) + periodSeconds (<5)
            initial_delay = readiness_probe.get("initialDelaySeconds", 0)
            period = readiness_probe.get("periodSeconds", 10)  # K8s default is 10
            if initial_delay < 5 and period < 5:
                yield Hit(
                    rag="amber",
                    summary=(
                        f"Container '{container.name}' in {payload.name}"
                        f" has aggressive probe timing"
                        f" (initialDelaySeconds={initial_delay},"
                        f" periodSeconds={period}). This may cause premature"
                        " readiness or excessive load during startup."
                    ),
                    recommendation=(
                        "Increase initialDelaySeconds to at least 5 and"
                        " periodSeconds to at least 5 to give the application"
                        " time to initialise and avoid overwhelming it with"
                        " health checks during rolling updates."
                    ),
                    locator=locator,
                    confidence=0.80,
                )

            # (c) failureThreshold == 1 -- single failure kills pod during patch
            failure_threshold = readiness_probe.get("failureThreshold", 3)  # K8s default is 3
            if failure_threshold == 1:
                yield Hit(
                    rag="amber",
                    summary=(
                        f"Container '{container.name}' in {payload.name}"
                        " has failureThreshold=1 on the readiness probe."
                        " A single transient failure will remove the pod"
                        " from service endpoints."
                    ),
                    recommendation=(
                        "Set failureThreshold to at least 2 (preferably 3)"
                        " so that a brief network hiccup or garbage-collection"
                        " pause does not immediately pull the pod out of"
                        " the load balancer during a rolling update."
                    ),
                    locator=locator,
                )


__all__ = ["TrivialProbeRule"]
