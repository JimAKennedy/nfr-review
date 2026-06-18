# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""MetricExtractor implementation for ADR change detection signals."""

from __future__ import annotations

from nfr_review.design_change.extractors import extractor_registry
from nfr_review.design_change.models import MetricCategory, NumericMetric, SetMetric
from nfr_review.models import Evidence

_SUPERSEDED_STATUSES = frozenset({"superseded", "deprecated", "replaced"})


class AdrMetricsExtractor:
    """Extracts ADR count, titles, and superseded ADR titles from adr-document evidence."""

    @property
    def category(self) -> str:
        return "adrs"

    def extract(self, evidence: list[Evidence]) -> MetricCategory:
        adr_evidence = [e for e in evidence if e.kind == "adr-document"]
        if not adr_evidence:
            return MetricCategory(category=self.category)

        titles: set[str] = set()
        superseded: set[str] = set()

        for ev in adr_evidence:
            payload = ev.payload
            title = getattr(payload, "title", None) or ""
            if not title:
                title = getattr(payload, "file_path", "") or ""
            if not title:
                continue

            titles.add(title)

            status = (getattr(payload, "status", None) or "").lower().strip()
            superseded_by = getattr(payload, "superseded_by", None) or ""

            if status in _SUPERSEDED_STATUSES or superseded_by:
                superseded.add(title)

        return MetricCategory(
            category=self.category,
            numeric_metrics={
                "adr_count": NumericMetric(name="adr_count", value=float(len(titles))),
            },
            set_metrics={
                "adr_titles": SetMetric(name="adr_titles", items=sorted(titles)),
                "superseded_adrs": SetMetric(name="superseded_adrs", items=sorted(superseded)),
            },
        )


def _register() -> None:
    ext = AdrMetricsExtractor()
    if ext.category not in extractor_registry:
        extractor_registry.register(ext.category, ext)


_register()

__all__ = ["AdrMetricsExtractor"]
