# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: jacoco-coverage-actual — evaluates actual code coverage from JaCoCo
XML reports against quality thresholds.

This complements the existing jacoco-threshold-missing rule (which checks if
JaCoCo is configured) by evaluating the actual coverage numbers."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class JaCoCoCoverageActualRule:
    """Evaluate actual coverage from JaCoCo reports.

    Thresholds:
    - Line coverage < 50% -> red/high
    - Line coverage < 70% -> amber/medium
    - Line coverage >= 70% -> green/info
    - Branch coverage < 50% -> amber/medium (additional finding)
    """

    id = "jacoco-coverage-actual"
    band: Band = 2
    required_collectors: list[str] = ["jacoco-report"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        jacoco_evidence = filter_evidence(evidence, "jacoco-report", "jacoco-report")
        if not jacoco_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no jacoco-report evidence available",
            )

        findings: list[Finding] = []

        for ev in jacoco_evidence:
            overall = ev.payload.overall
            report_name = ev.payload.report_name
            line_pct = overall.get("line_pct", 0.0)
            branch_pct = overall.get("branch_pct", 0.0)

            # Evaluate line coverage
            if line_pct < 50.0:
                findings.append(
                    Finding(
                        rule_id=self.id,
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
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="jacoco-coverage",
                    )
                )
            elif line_pct < 70.0:
                findings.append(
                    Finding(
                        rule_id=self.id,
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
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="jacoco-coverage",
                    )
                )
            else:
                findings.append(
                    make_green_finding(
                        self.id,
                        "jacoco-coverage",
                        ev,
                        summary=(
                            f"Line coverage is {line_pct}% in {report_name} — "
                            f"meets 70% threshold"
                        ),
                        recommendation="No action required — coverage is adequate.",
                        confidence=0.95,
                        evidence_locator=ev.locator,
                    )
                )

            # Evaluate branch coverage separately
            if branch_pct < 50.0:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Branch coverage is {branch_pct}% in {report_name} — "
                            f"below 50% threshold"
                        ),
                        recommendation=(
                            "Improve branch coverage by adding tests for "
                            "conditional logic, error paths, and edge cases."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.90,
                        pattern_tag="jacoco-branch-coverage",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "jacoco-coverage-actual" not in rule_registry:
        rule_registry.register(
            "jacoco-coverage-actual",
            JaCoCoCoverageActualRule(),
        )


_register()

__all__ = ["JaCoCoCoverageActualRule"]
