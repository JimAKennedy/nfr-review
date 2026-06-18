# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from nfr_review.design_change.models import MetricCategory, StructuralBaseline
from nfr_review.models import Evidence
from nfr_review.registry import Registry

logger = logging.getLogger(__name__)


@runtime_checkable
class MetricExtractor(Protocol):
    @property
    def category(self) -> str: ...

    def extract(self, evidence: list[Evidence]) -> MetricCategory: ...


extractor_registry: Registry[MetricExtractor] = Registry("metric_extractor")


def extract_all_metrics(
    evidence: list[Evidence],
    registry: Registry[MetricExtractor] | None = None,
) -> dict[str, MetricCategory]:
    reg = registry or extractor_registry
    result: dict[str, MetricCategory] = {}
    for extractor in reg.all():
        try:
            category = extractor.extract(evidence)
            result[extractor.category] = category
        except Exception:  # noqa: BLE001
            logger.warning("extractor %s failed, skipping", extractor.category, exc_info=True)
    return result


def build_baseline(
    evidence: list[Evidence],
    repo_path: str,
    registry: Registry[MetricExtractor] | None = None,
) -> StructuralBaseline:
    metrics = extract_all_metrics(evidence, registry)
    return StructuralBaseline(
        source_repo=repo_path,
        created_at=datetime.now(UTC).isoformat(),
        metrics=metrics,
    )
