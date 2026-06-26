# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-TOOL-003 — checks CI workflows for sanitizer jobs (asan, ubsan, tsan)."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.ci import CiPipelinePayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding
from nfr_review.rules.rule_helpers import make_green_finding

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


class CppSanitizerCiRule(FieldRule[CiPipelinePayload]):
    id = "cpp-sanitizer-ci"
    collector_name = "ci-artifact"
    evidence_kind = "ci-pipeline"
    payload_type = CiPipelinePayload
    pattern_tag = "cpp-sanitizer-ci-missing"
    required_tech = ["cpp"]
    default_confidence = 0.85
    all_clear_summary = "CI includes sanitizer jobs for runtime error detection."

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        relevant = [
            e
            for e in evidence
            if e.collector_name == self.collector_name and e.kind == self.evidence_kind
        ]
        if not relevant:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no ci-pipeline evidence available",
            )

        has_sanitizer = False
        for ev in relevant:
            payload = self._coerce(ev.payload)
            searchable = " ".join(payload.step_names + payload.job_names).lower()
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
                        relevant[0],
                        summary="CI includes sanitizer jobs for runtime error detection.",
                        confidence=0.9,
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_finding(
                    rule_id=self.id,
                    hit=Hit(
                        rag="amber",
                        severity="medium",
                        summary=(
                            "No sanitizer jobs found in CI — runtime errors may go undetected."
                        ),
                        recommendation=(
                            "Add CI jobs with -fsanitize=address and"
                            " -fsanitize=undefined to detect memory errors"
                            " and undefined behavior."
                        ),
                        locator="project-wide",
                    ),
                    ev=relevant[0],
                    pattern_tag=self.pattern_tag,
                    default_confidence=self.default_confidence,
                )
            ],
        )


__all__ = ["CppSanitizerCiRule"]
