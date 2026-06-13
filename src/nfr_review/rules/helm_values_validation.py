# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: helm-values-validation — flags missing best-practice values in Helm charts."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


def _get_nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for k in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(k)
    return current


class HelmValuesValidationRule:
    """Flag Helm charts with missing resource limits, replica counts,
    or image best practices."""

    id = "helm-values-validation"
    band: Band = 1
    required_collectors: list[str] = ["helm"]
    required_tech: list[str] = ["helm"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        helm_evidence = filter_evidence(evidence, "helm", "helm-analysis")
        if not helm_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no helm-analysis evidence available",
            )

        findings: list[Finding] = []
        for ev in helm_evidence:
            chart_path = ev.payload.get("chart_path", ev.locator)
            values = ev.payload.get("chart_values", {})

            resources = values.get("resources")
            if not resources or (
                isinstance(resources, dict)
                and not resources.get("limits")
                and not resources.get("requests")
            ):
                findings.append(
                    Finding(
                        rule_id=self.id,
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
                        evidence_locator=f"{chart_path}/values.yaml",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="helm-values-validation",
                    )
                )

            image_tag = _get_nested(values, "image", "tag")
            if isinstance(image_tag, str) and image_tag.lower() == "latest":
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Chart '{chart_path}' uses 'latest' image tag in values.yaml."
                        ),
                        recommendation=(
                            "Pin the image tag to a specific version for"
                            " reproducible deployments."
                        ),
                        evidence_locator=f"{chart_path}/values.yaml",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="helm-values-validation",
                    )
                )
            elif _get_nested(values, "image") is not None and image_tag is None:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Chart '{chart_path}' has no image tag specified in values.yaml."
                        ),
                        recommendation=(
                            "Specify an explicit image tag in values.yaml"
                            " instead of relying on 'latest' default."
                        ),
                        evidence_locator=f"{chart_path}/values.yaml",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="helm-values-validation",
                    )
                )

            if values.get("replicaCount") is None:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="low",
                        summary=(
                            f"Chart '{chart_path}' has no 'replicaCount' in values.yaml."
                        ),
                        recommendation=(
                            "Set an explicit 'replicaCount' in values.yaml"
                            " to document the expected replica baseline."
                        ),
                        evidence_locator=f"{chart_path}/values.yaml",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="helm-values-validation",
                    )
                )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "helm-values-validation",
                    helm_evidence[0],
                    summary="All Helm charts follow values.yaml best practices.",
                    confidence=0.9,
                    evidence_locator="all-helm-charts",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "helm-values-validation" not in rule_registry:
        rule_registry.register("helm-values-validation", HelmValuesValidationRule())


_register()

__all__ = ["HelmValuesValidationRule"]
