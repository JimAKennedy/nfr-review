# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the Skaffold collector."""

from __future__ import annotations

from typing import Any

from nfr_review.models import BasePayload


class SkaffoldAnalysisPayload(BasePayload):
    """Payload for kind='skaffold-analysis' evidence."""

    file_path: str
    api_version: str
    build: dict[str, Any]
    deploy: dict[str, Any]
    profiles: list[dict[str, Any]]


__all__ = ["SkaffoldAnalysisPayload"]
