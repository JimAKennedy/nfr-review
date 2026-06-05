# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the Helm collector."""

from __future__ import annotations

from typing import Any

from nfr_review.models import BasePayload


class HelmAnalysisPayload(BasePayload):
    """Payload for kind='helm-analysis' evidence."""

    chart_path: str
    chart_name: str | None = None
    chart_version: str | None = None
    app_version: str | None = None
    description: str | None = None
    maintainers: list[dict[str, Any]] | None = None
    chart_values: dict[str, Any]
    rendered_manifests: list[dict[str, Any]]
    template_files: list[str]
    helm_available: bool


__all__ = [
    "HelmAnalysisPayload",
]
