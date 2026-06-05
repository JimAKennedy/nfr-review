# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the Istio collector."""

from __future__ import annotations

from typing import Any

from nfr_review.models import BasePayload


class IstioResource(BasePayload):
    """A single Istio CRD resource."""

    kind: str
    api_version: str
    name: str
    namespace: str | None = None
    spec: dict[str, Any]
    line: int


class IstioAnalysisPayload(BasePayload):
    """Payload for kind='istio-analysis' evidence."""

    file_path: str
    resources: list[IstioResource]


__all__ = [
    "IstioResource",
    "IstioAnalysisPayload",
]
