# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the JaCoCo report collector."""

from __future__ import annotations

from nfr_review.models import BasePayload


class JacocoCoverageMetrics(BasePayload):
    """Overall coverage metrics from a JaCoCo report."""

    line_covered: int
    line_missed: int
    line_pct: float
    branch_covered: int
    branch_missed: int
    branch_pct: float
    instruction_covered: int
    instruction_missed: int
    instruction_pct: float


class JacocoPackageCoverage(BasePayload):
    """Per-package coverage summary."""

    name: str
    line_pct: float
    branch_pct: float
    instruction_pct: float


class JacocoReportPayload(BasePayload):
    """Payload for kind='jacoco-report' evidence."""

    report_path: str
    report_name: str
    overall: JacocoCoverageMetrics
    packages: list[JacocoPackageCoverage]


__all__ = [
    "JacocoCoverageMetrics",
    "JacocoPackageCoverage",
    "JacocoReportPayload",
]
