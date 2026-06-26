# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: jacoco-coverage-actual — evaluates actual code coverage from JaCoCo
XML reports against quality thresholds.

This complements the existing jacoco-threshold-missing rule (which checks if
JaCoCo is configured) by evaluating the actual coverage numbers."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.jacoco import JacocoReportPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class JaCoCoCoverageActualRule(FieldRule[JacocoReportPayload]):
    """Evaluate actual coverage from JaCoCo reports.

    Thresholds:
    - Line coverage < 50% -> red/high
    - Line coverage < 70% -> amber/medium
    - Line coverage >= 70% -> green/info
    - Branch coverage < 50% -> amber/medium (additional finding)
    """

    id = "jacoco-coverage-actual"
    band = 2
    collector_name = "jacoco-report"
    evidence_kind = "jacoco-report"
    payload_type = JacocoReportPayload
    pattern_tag = "jacoco-coverage"
    default_confidence = 0.95
    all_clear_summary = "Code coverage meets thresholds."
    all_clear_recommendation = "No action required — coverage is adequate."

    def check(self, payload: JacocoReportPayload, ev: Evidence) -> Iterable[Hit]:
        overall = payload.overall
        report_name = payload.report_name
        line_pct = overall.line_pct
        branch_pct = overall.branch_pct

        # Evaluate line coverage
        if line_pct < 50.0:
            yield Hit(
                rag="red",
                severity="high",
                summary=(
                    f"Line coverage is {line_pct}% in {report_name} — "
                    f"below 50% minimum threshold"
                ),
                recommendation=(
                    "Increase test coverage significantly. "
                    "Focus on covering critical business logic and "
                    "error-handling paths first."
                ),
                locator=ev.locator,
            )
        elif line_pct < 70.0:
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(
                    f"Line coverage is {line_pct}% in {report_name} — "
                    f"below 70% recommended threshold"
                ),
                recommendation=(
                    "Improve test coverage to at least 70%. "
                    "Prioritise untested modules and edge cases."
                ),
                locator=ev.locator,
            )
        else:
            yield Hit(
                rag="green",
                summary=(
                    f"Line coverage is {line_pct}% in {report_name} — meets 70% threshold"
                ),
                recommendation="No action required — coverage is adequate.",
                locator=ev.locator,
            )

        # Evaluate branch coverage separately
        if branch_pct < 50.0:
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(
                    f"Branch coverage is {branch_pct}% in {report_name} — below 50% threshold"
                ),
                recommendation=(
                    "Improve branch coverage by adding tests for "
                    "conditional logic, error paths, and edge cases."
                ),
                locator=ev.locator,
                confidence=0.90,
                pattern_tag="jacoco-branch-coverage",
            )


__all__ = ["JaCoCoCoverageActualRule"]
