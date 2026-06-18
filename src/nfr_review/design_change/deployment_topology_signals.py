# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""MetricExtractor implementation for deployment topology change detection signals."""

from __future__ import annotations

from nfr_review.design_change.extractors import extractor_registry
from nfr_review.design_change.models import MetricCategory, NumericMetric, SetMetric
from nfr_review.models import Evidence


class DeploymentTopologyExtractor:
    """Extracts deployment topology entities from Helm, K8s, and Terraform evidence.

    Entities are labelled as ``helm:{chart_name}``, ``k8s:{kind}``, or
    ``terraform:{module_name}`` so the set diff shows exactly which
    deployment components were added or removed between baselines.
    """

    @property
    def category(self) -> str:
        return "deployment_topology"

    def extract(self, evidence: list[Evidence]) -> MetricCategory:
        services: set[str] = set()

        for ev in evidence:
            if ev.kind == "helm-analysis":
                chart_name = ev.payload.chart_name
                if chart_name:
                    services.add(f"helm:{chart_name}")

            elif ev.kind == "k8s-manifest-summary":
                for kind, count in ev.payload.resource_counts.items():
                    if count > 0:
                        services.add(f"k8s:{kind}")

            elif ev.kind == "terraform-analysis":
                for mod in ev.payload.module_blocks:
                    if mod.name:
                        services.add(f"terraform:{mod.name}")

        if not services:
            return MetricCategory(category=self.category)

        return MetricCategory(
            category=self.category,
            numeric_metrics={
                "deployment_service_count": NumericMetric(
                    name="deployment_service_count",
                    value=float(len(services)),
                ),
            },
            set_metrics={
                "deployment_services": SetMetric(
                    name="deployment_services",
                    items=sorted(services),
                ),
            },
        )


def _register() -> None:
    ext = DeploymentTopologyExtractor()
    if ext.category not in extractor_registry:
        extractor_registry.register(ext.category, ext)


_register()

__all__ = ["DeploymentTopologyExtractor"]
