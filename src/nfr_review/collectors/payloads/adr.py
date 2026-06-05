# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the ADR collector."""

from __future__ import annotations

from nfr_review.models import BasePayload


class AdrDocumentPayload(BasePayload):
    """Payload for kind='adr-document' evidence."""

    file_path: str
    title: str | None = None
    status: str | None = None
    date: str | None = None
    superseded_by: str | None = None
    has_frontmatter: bool = False


class AdrSummaryPayload(BasePayload):
    """Payload for kind='adr-summary' evidence."""

    total_adrs: int
    statuses: dict[str, int]
    has_lifecycle_tracking: bool


__all__ = ["AdrDocumentPayload", "AdrSummaryPayload"]
