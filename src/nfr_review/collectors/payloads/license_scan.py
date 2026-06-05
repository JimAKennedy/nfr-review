# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the license-scan hygiene collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "CopyleftFlags",
    "LicenseDetection",
    "LicenseScanPayload",
    "LicenseScanSummaryPayload",
]


class LicenseDetection(BasePayload):
    spdx_key: str
    score: float
    start_line: int
    end_line: int


class LicenseScanPayload(BasePayload):
    licenses: list[LicenseDetection]
    copyrights: list[str]
    holders: list[str]
    detected_expression_spdx: str | None


class CopyleftFlags(BasePayload):
    has_gpl: bool
    has_agpl: bool
    has_lgpl: bool


class LicenseScanSummaryPayload(BasePayload):
    total_files_scanned: int
    unique_licenses: list[str]
    copyleft_flags: CopyleftFlags
