# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the APIM Policy collector."""

from __future__ import annotations

from nfr_review.models import BasePayload


class ApimPolicyPayload(BasePayload):
    """Payload for kind='apim-policy' evidence."""

    file_path: str
    has_rate_limit: bool
    has_auth_policy: bool
    backend_urls: list[str]
    uses_named_values: bool
    inbound_policies: list[str]
    outbound_policies: list[str]


__all__ = ["ApimPolicyPayload"]
