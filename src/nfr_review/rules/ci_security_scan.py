# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: ci-security-scan-missing -- checks CI pipelines include security scanning."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.ci import CiPipelinePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class CiSecurityScanMissingRule(FieldRule[CiPipelinePayload]):
    """Flag when CI pipelines exist but no security scan step is found."""

    id = "ci-security-scan-missing"
    collector_name = "ci-artifact"
    evidence_kind = "ci-pipeline"
    payload_type = CiPipelinePayload
    pattern_tag = "ci-security-scan"
    default_confidence = 0.9
    all_clear_summary = "Security scanning is present in CI pipeline."
    all_clear_recommendation = "No action required -- security scanning is present."

    def check(self, payload: CiPipelinePayload, ev: Evidence) -> Iterable[Hit]:
        if not payload.has_security_scan:
            yield Hit(
                rag="red",
                severity="high",
                summary=(
                    "CI pipeline found but does not include security scanning (SAST/DAST/SCA)."
                ),
                recommendation=(
                    "Add a security scan step (e.g., CodeQL, Snyk, Trivy)"
                    " to at least one CI pipeline."
                ),
                locator=payload.file_path,
            )


__all__ = ["CiSecurityScanMissingRule"]
