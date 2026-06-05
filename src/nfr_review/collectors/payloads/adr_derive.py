# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the ADR derivation collector."""

from __future__ import annotations

from nfr_review.models import BasePayload


class AdrDerivedPayload(BasePayload):
    """Payload for kind='adr-derived' evidence."""

    title: str
    rationale: str
    category: str
    confidence: float
    evidence_refs: list[str]


class AdrDeriveSummaryPayload(BasePayload):
    """Payload for kind='adr-derive-summary' evidence."""

    total_derived: int
    categories: dict[str, int]
    avg_confidence: float


class AdrDeriveSkipPayload(BasePayload):
    """Payload for kind='adr-derive-skip' evidence."""

    reason: str


__all__ = [
    "AdrDerivedPayload",
    "AdrDeriveSkipPayload",
    "AdrDeriveSummaryPayload",
]
