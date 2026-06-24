# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-HEALTH-004 -- checks terminationGracePeriodSeconds for patching safety."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.k8s import K8sResourcePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_DEFAULT_GRACE_PERIOD = 30


class TerminationGracePeriodRule(FieldRule[K8sResourcePayload]):
    """Flag workloads with insufficient termination grace period for safe patching.

    Checks:
    (a) Amber if terminationGracePeriodSeconds < 30 -- insufficient time for connection
        draining during patch.
    (b) Amber if grace period is default (30) but no preStop hook exists on any
        container -- no orderly shutdown signal.
    (c) No hit if grace period >= 30 and at least one container has preStop configured
        (base class handles all-clear).
    """

    id = "PATCH-HEALTH-004"
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-resource"
    payload_type = K8sResourcePayload
    pattern_tag = "patch-health-termination"
    default_confidence = 0.90
    all_clear_summary = "All workloads pass termination grace period checks."
    all_clear_recommendation = "No action required."

    def check(self, payload: K8sResourcePayload, ev: Evidence) -> Iterable[Hit]:
        # termination_grace_period is at the pod level; treat None as default
        raw_grace = payload.termination_grace_period
        grace_period = raw_grace if raw_grace is not None else _DEFAULT_GRACE_PERIOD

        # Check if any container has a preStop hook
        has_pre_stop = any(c.pre_stop is not None for c in payload.containers)

        locator = f"{payload.file_path}:{payload.name}"

        if grace_period < _DEFAULT_GRACE_PERIOD:
            # (a) Grace period too low for safe connection draining
            yield Hit(
                rag="amber",
                summary=(
                    f"Resource '{payload.name}' has"
                    f" terminationGracePeriodSeconds={grace_period} which is"
                    f" below the recommended minimum of {_DEFAULT_GRACE_PERIOD}."
                    " Connections may not drain fully during a rolling update."
                ),
                recommendation=(
                    "Increase terminationGracePeriodSeconds to at least 30"
                    " to allow in-flight requests to complete before the pod"
                    " is forcibly terminated during patching."
                ),
                locator=locator,
            )
        elif grace_period == _DEFAULT_GRACE_PERIOD and not has_pre_stop:
            # (b) Default grace period but no preStop -- no orderly shutdown signal
            yield Hit(
                rag="amber",
                summary=(
                    f"Resource '{payload.name}' uses the default"
                    f" terminationGracePeriodSeconds ({_DEFAULT_GRACE_PERIOD})"
                    " but no container defines a preStop hook. Without"
                    " preStop, the application receives only SIGTERM and may"
                    " not drain connections gracefully during patching."
                ),
                recommendation=(
                    "Add a preStop lifecycle hook (e.g. a short sleep or"
                    " endpoint call) to at least one container so that"
                    " in-flight requests complete before the pod is removed"
                    " from service endpoints."
                ),
                locator=locator,
                confidence=0.85,
            )


__all__ = ["TerminationGracePeriodRule"]
