# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import nfr_review.design_change.structural_signals as structural_signals  # noqa: F401
from nfr_review.design_change.diff import (
    CategoryDiff,
    NumericDelta,
    SetDelta,
    apply_thresholds,
    diff_baselines,
    format_diff_summary,
)
from nfr_review.design_change.extractors import (
    MetricExtractor,
    build_baseline,
    extract_all_metrics,
    extractor_registry,
)
from nfr_review.design_change.models import (
    MetricCategory,
    NumericMetric,
    SetMetric,
    StructuralBaseline,
)
from nfr_review.design_change.snapshot import (
    load_baseline,
    save_baseline,
)

__all__ = [
    "CategoryDiff",
    "MetricCategory",
    "MetricExtractor",
    "NumericDelta",
    "NumericMetric",
    "SetDelta",
    "SetMetric",
    "StructuralBaseline",
    "apply_thresholds",
    "build_baseline",
    "diff_baselines",
    "extract_all_metrics",
    "extractor_registry",
    "format_diff_summary",
    "load_baseline",
    "save_baseline",
]
