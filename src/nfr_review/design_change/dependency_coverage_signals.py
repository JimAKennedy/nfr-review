# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""MetricExtractor implementations for dependency count and test coverage signals."""

from __future__ import annotations

from nfr_review.design_change.extractors import extractor_registry
from nfr_review.design_change.models import MetricCategory, NumericMetric, SetMetric
from nfr_review.models import Evidence

_DEPS_KINDS = frozenset(
    {
        "java-deps",
        "python-deps",
        "go-deps",
        "nodejs-deps",
        "csharp-deps",
    }
)


class DependencyMetricsExtractor:
    """Extracts dependency_count and dependency_names from *-deps evidence."""

    @property
    def category(self) -> str:
        return "dependencies"

    def extract(self, evidence: list[Evidence]) -> MetricCategory:
        deps_evidence = [e for e in evidence if e.kind in _DEPS_KINDS]
        if not deps_evidence:
            return MetricCategory(category=self.category)

        all_names: set[str] = set()
        for ev in deps_evidence:
            for dep in ev.payload.dependencies:
                if dep.indirect:
                    continue
                all_names.add(dep.name)

        return MetricCategory(
            category=self.category,
            numeric_metrics={
                "dependency_count": NumericMetric(
                    name="dependency_count", value=float(len(all_names))
                ),
            },
            set_metrics={
                "dependency_names": SetMetric(
                    name="dependency_names", items=sorted(all_names)
                ),
            },
        )


class CoverageMetricsExtractor:
    """Extracts test_coverage (line coverage %) from jacoco-report evidence."""

    @property
    def category(self) -> str:
        return "coverage"

    def extract(self, evidence: list[Evidence]) -> MetricCategory:
        jacoco_evidence = [e for e in evidence if e.kind == "jacoco-report"]
        if not jacoco_evidence:
            return MetricCategory(category=self.category)

        total_covered = 0
        total_missed = 0
        for ev in jacoco_evidence:
            total_covered += ev.payload.overall.line_covered
            total_missed += ev.payload.overall.line_missed

        total = total_covered + total_missed
        line_pct = (total_covered / total * 100.0) if total > 0 else 0.0

        return MetricCategory(
            category=self.category,
            numeric_metrics={
                "test_coverage": NumericMetric(name="test_coverage", value=line_pct),
            },
        )


def _register() -> None:
    instances: list[DependencyMetricsExtractor | CoverageMetricsExtractor] = [
        DependencyMetricsExtractor(),
        CoverageMetricsExtractor(),
    ]
    for ext in instances:
        if ext.category not in extractor_registry:
            extractor_registry.register(ext.category, ext)


_register()

__all__ = ["CoverageMetricsExtractor", "DependencyMetricsExtractor"]
