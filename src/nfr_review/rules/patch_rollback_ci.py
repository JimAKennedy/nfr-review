# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: PATCH-ROLL-002 — CI rollback stage presence check.

Scans CI pipeline evidence for rollback/revert/canary-rollback job or step
names.  Flags amber when no CI pipeline includes a rollback-related stage,
green when at least one pipeline does.

* SKIPPED when no ci-pipeline evidence is available.
* AMBER when no pipeline has a rollback-related job or step name.
* GREEN when any pipeline has a matching job or step name.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from nfr_review.collectors.payloads.ci import CiPipelinePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_ROLLBACK_RE = re.compile(
    r"(rollback|roll[-_]?back|revert|canary[-_]?rollback)", re.IGNORECASE
)


class CiRollbackStageMissingRule(FieldRule[CiPipelinePayload]):
    """Check that at least one CI pipeline has a rollback/revert stage."""

    id = "PATCH-ROLL-002"
    collector_name = "ci-artifact"
    evidence_kind = "ci-pipeline"
    payload_type = CiPipelinePayload
    pattern_tag = "patch-rollback-ci"
    default_confidence = 0.85
    all_clear_summary = "CI pipeline has a rollback-related stage."
    all_clear_recommendation = "No action required — rollback stage detected."

    def check(self, payload: CiPipelinePayload, ev: Evidence) -> Iterable[Hit]:
        job_names = payload.job_names
        step_names = payload.step_names

        matched = any(_ROLLBACK_RE.search(name) for name in job_names + step_names)

        if not matched:
            yield Hit(
                rag="amber",
                severity="medium",
                summary="No CI rollback stage detected",
                recommendation=(
                    "Add a rollback or revert stage to your CI pipeline"
                    " so that failed deployments can be automatically"
                    " rolled back."
                ),
                locator=payload.file_path,
            )


__all__ = ["CiRollbackStageMissingRule"]
