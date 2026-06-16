# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: ci-test-stage-missing — checks CI pipelines include a test step."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class CiTestStageMissingRule:
    """Flag when CI pipelines exist but no test step is found."""

    id = "ci-test-stage-missing"
    band: Band = 1
    required_collectors: list[str] = ["ci-artifact"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ci_pipelines = filter_evidence(evidence, "ci-artifact", "ci-pipeline")
        if not ci_pipelines:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no CI pipeline evidence available",
            )

        any_test = any(e.payload.has_test_step for e in ci_pipelines)

        cmake_signals = filter_evidence(evidence, "ci-artifact", "cmake-test-signals")
        has_cmake_tests = any(e.payload.has_test_framework for e in cmake_signals)

        if any_test or has_cmake_tests:
            if any_test:
                locator = next(
                    e.payload.file_path for e in ci_pipelines if e.payload.has_test_step
                )
            else:
                locator = cmake_signals[0].payload.files[0].file_path
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "ci-test-stage",
                        ci_pipelines[0],
                        summary="CI pipeline includes a test step.",
                        confidence=0.9,
                        recommendation="No action required — test step is present.",
                        evidence_locator=locator,
                    )
                ],
            )

        pipeline_files = [e.payload.file_path for e in ci_pipelines]
        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
                    rag="red",
                    severity="high",
                    summary=(
                        f"{len(ci_pipelines)} CI pipeline(s) found but none"
                        " include a test step."
                    ),
                    recommendation=(
                        "Add a test step (mvn test, pytest, npm test, etc.)"
                        " to at least one CI pipeline."
                    ),
                    evidence_locator=pipeline_files[0],
                    collector_name="ci-artifact",
                    collector_version="0.1.0",
                    confidence=0.9,
                    pattern_tag="ci-test-stage",
                )
            ],
        )


def _register() -> None:
    if "ci-test-stage-missing" not in rule_registry:
        rule_registry.register("ci-test-stage-missing", CiTestStageMissingRule())


_register()

__all__ = ["CiTestStageMissingRule"]
