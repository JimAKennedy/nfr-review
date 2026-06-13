# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: helm-chart-metadata — flags incomplete Chart.yaml metadata."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


class HelmChartMetadataRule:
    """Flag Helm charts with incomplete Chart.yaml metadata."""

    id = "helm-chart-metadata"
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

            if not ev.payload.get("description"):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary="Helm chart is missing a description in Chart.yaml.",
                        recommendation="Add a meaningful 'description' field to Chart.yaml.",
                        evidence_locator=f"{chart_path}/Chart.yaml",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="helm-chart-metadata",
                    )
                )

            if not ev.payload.get("app_version"):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary="Helm chart is missing 'appVersion' in Chart.yaml.",
                        recommendation=(
                            "Add an 'appVersion' field to Chart.yaml to track"
                            " the application version deployed by this chart."
                        ),
                        evidence_locator=f"{chart_path}/Chart.yaml",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="helm-chart-metadata",
                    )
                )

            chart_version = ev.payload.get("chart_version")
            if chart_version and not _SEMVER_RE.match(str(chart_version)):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Helm chart version '{chart_version}' does not follow SemVer."
                        ),
                        recommendation=(
                            "Use Semantic Versioning (e.g. 1.2.3) for the"
                            " chart 'version' field in Chart.yaml."
                        ),
                        evidence_locator=f"{chart_path}/Chart.yaml",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="helm-chart-metadata",
                    )
                )

            maintainers = ev.payload.get("maintainers")
            if not maintainers:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="low",
                        summary="Helm chart has no maintainers listed in Chart.yaml.",
                        recommendation=(
                            "Add a 'maintainers' section to Chart.yaml with"
                            " at least one contact."
                        ),
                        evidence_locator=f"{chart_path}/Chart.yaml",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="helm-chart-metadata",
                    )
                )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "helm-chart-metadata",
                    helm_evidence[0],
                    summary="All Helm charts have complete Chart.yaml metadata.",
                    confidence=0.9,
                    evidence_locator="all-helm-charts",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "helm-chart-metadata" not in rule_registry:
        rule_registry.register("helm-chart-metadata", HelmChartMetadataRule())


_register()

__all__ = ["HelmChartMetadataRule"]
