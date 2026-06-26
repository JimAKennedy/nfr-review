# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: apim-rate-limit-missing -- checks APIM policies for rate limiting."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.apim import ApimPolicyPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class ApimRateLimitMissingRule(FieldRule[ApimPolicyPayload]):
    """Flag when no APIM policy has rate limiting configured in inbound section."""

    id = "apim-rate-limit-missing"
    collector_name = "apim-policy"
    evidence_kind = "apim-policy"
    payload_type = ApimPolicyPayload
    pattern_tag = "apim-rate-limit"
    required_tech = ["apim"]
    default_confidence = 0.95
    all_clear_summary = "Rate limiting is configured."
    all_clear_recommendation = "No action required -- rate limiting is present."

    def check(self, payload: ApimPolicyPayload, ev: Evidence) -> Iterable[Hit]:
        if not payload.has_rate_limit:
            yield Hit(
                rag="red",
                severity="high",
                summary=(
                    "No rate limiting policy found."
                    " API is unprotected against request flooding."
                ),
                recommendation=(
                    "Add a <rate-limit> or <rate-limit-by-key> policy"
                    " to the <inbound> section to protect against"
                    " excessive traffic."
                ),
                locator=payload.file_path,
            )


__all__ = ["ApimRateLimitMissingRule"]
