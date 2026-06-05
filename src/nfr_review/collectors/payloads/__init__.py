# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for collector evidence.

Each collector's payload contract is defined as a BasePayload subclass here,
replacing the untyped dict[str, Any] payloads with validated Pydantic models.
"""

from __future__ import annotations

from nfr_review.collectors.payloads.adr import AdrDocumentPayload, AdrSummaryPayload

__all__ = [
    "AdrDocumentPayload",
    "AdrSummaryPayload",
]
