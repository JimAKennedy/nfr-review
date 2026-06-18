# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""MetricExtractor implementation for API surface change detection signals."""

from __future__ import annotations

from nfr_review.design_change.extractors import extractor_registry
from nfr_review.design_change.models import MetricCategory, NumericMetric, SetMetric
from nfr_review.models import Evidence


class ApiSurfaceExtractor:
    """Extracts API endpoint count and names from proto-analysis and openapi-analysis evidence.

    Proto RPCs are formatted as ``Service.Method``.
    OpenAPI endpoints are formatted as ``METHOD /path``.
    """

    @property
    def category(self) -> str:
        return "api_surface"

    def extract(self, evidence: list[Evidence]) -> MetricCategory:
        endpoints: set[str] = set()

        for ev in evidence:
            if ev.kind == "proto-analysis":
                for svc in ev.payload.services:
                    for method in svc.methods:
                        endpoints.add(f"{svc.name}.{method.name}")

            elif ev.kind == "openapi-analysis":
                for ep in ev.payload.endpoints:
                    endpoints.add(f"{ep.method.upper()} {ep.path}")

        if not endpoints:
            return MetricCategory(category=self.category)

        return MetricCategory(
            category=self.category,
            numeric_metrics={
                "api_endpoint_count": NumericMetric(
                    name="api_endpoint_count",
                    value=float(len(endpoints)),
                ),
            },
            set_metrics={
                "api_endpoints": SetMetric(
                    name="api_endpoints",
                    items=sorted(endpoints),
                ),
            },
        )


def _register() -> None:
    ext = ApiSurfaceExtractor()
    if ext.category not in extractor_registry:
        extractor_registry.register(ext.category, ext)


_register()

__all__ = ["ApiSurfaceExtractor"]
