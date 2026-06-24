# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: helm-values-validation — flags missing best-practice values in Helm charts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from nfr_review.collectors.payloads.helm import HelmAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


def _get_nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for k in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(k)
    return current


class HelmValuesValidationRule(FieldRule[HelmAnalysisPayload]):
    """Flag Helm charts with missing resource limits, replica counts,
    or image best practices."""

    id = "helm-values-validation"
    collector_name = "helm"
    evidence_kind = "helm-analysis"
    payload_type = HelmAnalysisPayload
    pattern_tag = "helm-values-validation"
    required_tech = ["helm"]
    default_confidence = 0.9
    all_clear_summary = "All Helm charts follow values.yaml best practices."
    all_clear_recommendation = "No action required."

    def check(self, payload: HelmAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        chart_path = payload.chart_path
        values = payload.chart_values

        resources = values.get("resources")
        if not resources or (
            isinstance(resources, dict)
            and not resources.get("limits")
            and not resources.get("requests")
        ):
            yield Hit(
                rag="amber",
                severity="high",
                summary=(
                    f"Chart '{chart_path}' has no resource limits/requests"
                    " defined in values.yaml."
                ),
                recommendation=(
                    "Define 'resources.limits' and 'resources.requests'"
                    " in values.yaml to prevent unbounded resource"
                    " consumption in the cluster."
                ),
                locator=f"{chart_path}/values.yaml",
            )

        image_tag = _get_nested(values, "image", "tag")
        if isinstance(image_tag, str) and image_tag.lower() == "latest":
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(f"Chart '{chart_path}' uses 'latest' image tag in values.yaml."),
                recommendation=(
                    "Pin the image tag to a specific version for reproducible deployments."
                ),
                locator=f"{chart_path}/values.yaml",
            )
        elif _get_nested(values, "image") is not None and image_tag is None:
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(f"Chart '{chart_path}' has no image tag specified in values.yaml."),
                recommendation=(
                    "Specify an explicit image tag in values.yaml"
                    " instead of relying on 'latest' default."
                ),
                locator=f"{chart_path}/values.yaml",
                confidence=0.8,
            )

        if values.get("replicaCount") is None:
            yield Hit(
                rag="amber",
                severity="low",
                summary=(f"Chart '{chart_path}' has no 'replicaCount' in values.yaml."),
                recommendation=(
                    "Set an explicit 'replicaCount' in values.yaml"
                    " to document the expected replica baseline."
                ),
                locator=f"{chart_path}/values.yaml",
                confidence=0.8,
            )


__all__ = ["HelmValuesValidationRule"]
