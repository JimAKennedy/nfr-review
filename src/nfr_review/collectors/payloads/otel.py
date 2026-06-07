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


class OtelSdkConfigPayload(BasePayload):
    """Payload for kind='otel-sdk-config' evidence.

    Captures OTel SDK-level configuration found across docker-compose,
    CI workflows, Maven POMs, Spring Boot configs, and Dockerfiles.
    """

    agent_attached: bool
    exporter_type: str | None
    propagators: list[str]
    resource_attributes: dict[str, str]
    source_file: str


__all__ = ["OtelAnalysisPayload", "OtelSdkConfigPayload"]
