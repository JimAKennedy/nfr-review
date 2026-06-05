# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the privacy hygiene collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "PrivacyMatch",
    "PrivacyPayload",
]


class PrivacyMatch(BasePayload):
    file: str
    line: int
    pattern_type: str
    snippet: str


class PrivacyPayload(BasePayload):
    pii_matches: list[PrivacyMatch]
    internal_references: list[PrivacyMatch]
    tracking_ids: list[PrivacyMatch]
    files_scanned: int
