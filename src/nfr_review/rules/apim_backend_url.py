# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: apim-hardcoded-backend-url -- checks APIM policies for hardcoded backend URLs."""

from __future__ import annotations

import re
from collections.abc import Iterable

from nfr_review.collectors.payloads.apim import ApimPolicyPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_NAMED_VALUE_RE = re.compile(r"\{\{.+?\}\}")


class ApimHardcodedBackendUrlRule(FieldRule[ApimPolicyPayload]):
    id = "apim-hardcoded-backend-url"
    collector_name = "apim-policy"
    evidence_kind = "apim-policy"
    payload_type = ApimPolicyPayload
    pattern_tag = "apim-backend-url"
    required_tech = ["apim"]
    default_confidence = 0.9
    all_clear_summary = "No backend URLs found in any APIM policy."
    all_clear_recommendation = "No action required."

    def check(self, payload: ApimPolicyPayload, ev: Evidence) -> Iterable[Hit]:
        if not payload.backend_urls:
            return

        hardcoded = [url for url in payload.backend_urls if not _NAMED_VALUE_RE.search(url)]

        if hardcoded:
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(
                    f"Hardcoded backend URL(s): {', '.join(hardcoded)}."
                    " Environment-specific values should use named values."
                ),
                recommendation=(
                    "Replace hardcoded backend URLs with named values"
                    " (e.g. {{backend-url}}) to support environment"
                    " promotion and avoid secrets in source control."
                ),
                locator=payload.file_path,
            )


__all__ = ["ApimHardcodedBackendUrlRule"]
