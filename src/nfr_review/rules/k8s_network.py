# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: network-policy-missing -- checks repo for presence of NetworkPolicy resources."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.k8s import K8sManifestSummaryPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class NetworkPolicyMissingRule(FieldRule[K8sManifestSummaryPayload]):
    """Flag when no NetworkPolicy resource exists in the repository."""

    id = "network-policy-missing"
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-manifest-summary"
    payload_type = K8sManifestSummaryPayload
    pattern_tag = "k8s-network-policy"
    required_tech: list[str] = ["kubernetes"]
    default_confidence = 0.9
    all_clear_summary = "NetworkPolicy resource found in repository."
    all_clear_recommendation = "No action required -- network policies are defined."

    def check(self, payload: K8sManifestSummaryPayload, ev: Evidence) -> Iterable[Hit]:
        if not payload.has_network_policy:
            yield Hit(
                rag="amber",
                summary="No NetworkPolicy resource found in the repository.",
                recommendation=(
                    "Define NetworkPolicy resources to restrict pod-to-pod"
                    " traffic and enforce least-privilege network access."
                ),
                locator=ev.locator,
            )


__all__ = ["NetworkPolicyMissingRule"]
