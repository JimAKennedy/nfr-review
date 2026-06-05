# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the OTel collector."""

from __future__ import annotations

from typing import Any

from nfr_review.models import BasePayload


class OtelAnalysisPayload(BasePayload):
    """Payload for kind='otel-analysis' evidence."""

    file_path: str
    receivers: list[str]
    processors: list[str]
    exporters: list[str]
    pipelines: dict[str, Any]


__all__ = ["OtelAnalysisPayload"]
