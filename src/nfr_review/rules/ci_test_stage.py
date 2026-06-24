# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: ci-test-stage-missing -- checks CI pipelines include a test step."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.ci import CiPipelinePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class CiTestStageMissingRule(FieldRule[CiPipelinePayload]):
    """Flag when CI pipelines exist but no test step is found."""

    id = "ci-test-stage-missing"
    collector_name = "ci-artifact"
    evidence_kind = "ci-pipeline"
    payload_type = CiPipelinePayload
    pattern_tag = "ci-test-stage"
    default_confidence = 0.9
    all_clear_summary = "CI pipeline includes a test step."
    all_clear_recommendation = "No action required -- test step is present."

    def check(self, payload: CiPipelinePayload, ev: Evidence) -> Iterable[Hit]:
        if not payload.has_test_step:
            yield Hit(
                rag="red",
                severity="high",
                summary=("CI pipeline found but does not include a test step."),
                recommendation=(
                    "Add a test step (mvn test, pytest, npm test, etc.)"
                    " to at least one CI pipeline."
                ),
                locator=payload.file_path,
            )


__all__ = ["CiTestStageMissingRule"]
