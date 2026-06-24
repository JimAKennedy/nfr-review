# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: helm-chart-metadata — flags incomplete Chart.yaml metadata."""

from __future__ import annotations

import re
from collections.abc import Iterable

from nfr_review.collectors.payloads.helm import HelmAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


class HelmChartMetadataRule(FieldRule[HelmAnalysisPayload]):
    """Flag Helm charts with incomplete Chart.yaml metadata."""

    id = "helm-chart-metadata"
    collector_name = "helm"
    evidence_kind = "helm-analysis"
    payload_type = HelmAnalysisPayload
    pattern_tag = "helm-chart-metadata"
    required_tech = ["helm"]
    default_confidence = 0.9
    all_clear_summary = "All Helm charts have complete Chart.yaml metadata."
    all_clear_recommendation = "No action required."

    def check(self, payload: HelmAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        chart_path = payload.chart_path

        if not payload.description:
            yield Hit(
                rag="amber",
                severity="medium",
                summary="Helm chart is missing a description in Chart.yaml.",
                recommendation="Add a meaningful 'description' field to Chart.yaml.",
                locator=f"{chart_path}/Chart.yaml",
            )

        if not payload.app_version:
            yield Hit(
                rag="amber",
                severity="medium",
                summary="Helm chart is missing 'appVersion' in Chart.yaml.",
                recommendation=(
                    "Add an 'appVersion' field to Chart.yaml to track"
                    " the application version deployed by this chart."
                ),
                locator=f"{chart_path}/Chart.yaml",
            )

        chart_version = payload.chart_version
        if chart_version and not _SEMVER_RE.match(str(chart_version)):
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(f"Helm chart version '{chart_version}' does not follow SemVer."),
                recommendation=(
                    "Use Semantic Versioning (e.g. 1.2.3) for the"
                    " chart 'version' field in Chart.yaml."
                ),
                locator=f"{chart_path}/Chart.yaml",
            )

        maintainers = payload.maintainers
        if not maintainers:
            yield Hit(
                rag="amber",
                severity="low",
                summary="Helm chart has no maintainers listed in Chart.yaml.",
                recommendation=(
                    "Add a 'maintainers' section to Chart.yaml with at least one contact."
                ),
                locator=f"{chart_path}/Chart.yaml",
                confidence=0.8,
            )


__all__ = ["HelmChartMetadataRule"]
