# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: apim-auth-policy-missing -- checks APIM policies for authentication."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.apim import ApimPolicyPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class ApimAuthPolicyMissingRule(FieldRule[ApimPolicyPayload]):
    """Flag when no APIM policy has authentication configured."""

    id = "apim-auth-policy-missing"
    collector_name = "apim-policy"
    evidence_kind = "apim-policy"
    payload_type = ApimPolicyPayload
    pattern_tag = "apim-auth-policy"
    required_tech = ["apim"]
    default_confidence = 0.95
    all_clear_summary = "Authentication policy is configured."
    all_clear_recommendation = "No action required -- authentication is present."

    def check(self, payload: ApimPolicyPayload, ev: Evidence) -> Iterable[Hit]:
        if not payload.has_auth_policy:
            yield Hit(
                rag="red",
                severity="critical",
                summary="No authentication policy found. API endpoints are unprotected.",
                recommendation=(
                    "Add a <validate-jwt> or"
                    " <authentication-managed-identity> policy to the"
                    " <inbound> section to enforce authentication."
                ),
                locator=payload.file_path,
            )


__all__ = ["ApimAuthPolicyMissingRule"]
