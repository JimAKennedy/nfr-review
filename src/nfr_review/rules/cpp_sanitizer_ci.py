# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-TOOL-003 — checks CI workflows for sanitizer jobs (asan, ubsan, tsan)."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_SANITIZER_KEYWORDS = frozenset(
    {
        "sanitize=address",
        "sanitize=undefined",
        "sanitize=thread",
        "sanitize=memory",
        "asan",
        "ubsan",
        "tsan",
        "msan",
    }
)


class CppSanitizerCiRule:
    id = "cpp-sanitizer-ci"
    band: Band = 1
    required_collectors: list[str] = ["ci-artifact"]
    required_tech: list[str] = ["cpp"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ci_ev = filter_evidence(evidence, "ci-artifact", "ci-pipeline")
        if not ci_ev:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no ci-pipeline evidence available",
            )

        has_sanitizer = False
        for ev in ci_ev:
            searchable = " ".join(
                ev.payload.get("step_names", []) + ev.payload.get("job_names", [])
            ).lower()
            for keyword in _SANITIZER_KEYWORDS:
                if keyword in searchable:
                    has_sanitizer = True
                    break
            if has_sanitizer:
                break

        if has_sanitizer:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "cpp-sanitizer-ci-present",
                        ci_ev[0],
                        summary="CI includes sanitizer jobs for runtime error detection.",
                        confidence=0.9,
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        "No sanitizer jobs found in CI — runtime errors may go undetected."
                    ),
                    recommendation=(
                        "Add CI jobs with -fsanitize=address and -fsanitize=undefined "
                        "to detect memory errors and undefined behavior."
                    ),
                    evidence_locator="project-wide",
                    collector_name=ci_ev[0].collector_name,
                    collector_version=ci_ev[0].collector_version,
                    confidence=0.85,
                    pattern_tag="cpp-sanitizer-ci-missing",
                )
            ],
        )


def _register() -> None:
    if "cpp-sanitizer-ci" not in rule_registry:
        rule_registry.register("cpp-sanitizer-ci", CppSanitizerCiRule())


_register()

__all__ = ["CppSanitizerCiRule"]
