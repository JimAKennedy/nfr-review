# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the code-debt hygiene collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "CodeDebtFileEntry",
    "CodeDebtPayload",
]


class CodeDebtFileEntry(BasePayload):
    path: str
    count: int
    markers: dict[str, int]


class CodeDebtPayload(BasePayload):
    total_markers: int
    per_marker: dict[str, int]
    file_count: int
    top_files: list[CodeDebtFileEntry]
