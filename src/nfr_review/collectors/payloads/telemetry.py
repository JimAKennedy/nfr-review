# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the telemetry-config collector.

Covers OTel collector pipeline topology, SDK instrumentation patterns,
synthetic test configurations, and the roll-up summary.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import BasePayload

__all__ = [
    "TelemetryConfigSummaryPayload",
    "TelemetryExporterTarget",
    "TelemetryPipelinePayload",
    "TelemetrySdkInitPayload",
    "TelemetrySyntheticConfigPayload",
]


class TelemetryExporterTarget(BasePayload):
    name: str
    type: str
    endpoint: str | None = None


class TelemetryPipelinePayload(BasePayload):
    file_path: str
    receivers: list[str]
    processors: list[str]
    exporters: list[str]
    pipelines: dict[str, dict[str, list[str]]]
    signal_types: list[str]
    exporter_targets: list[TelemetryExporterTarget]
    resource_attributes: dict[str, Any]
    extensions: list[str]


class TelemetrySdkInitPayload(BasePayload):
    file_path: str
    language: str
    sdk_packages: list[str]
    instrumentation_type: str
    configured_signals: list[str]


class TelemetrySyntheticConfigPayload(BasePayload):
    file_path: str
    tool: str
    test_type: str
    targets: list[str]
    frequency: str | None = None


class TelemetryConfigSummaryPayload(BasePayload):
    collector_configs_found: int
    sdk_instrumentations_found: int
    synthetic_configs_found: int
    signal_coverage: dict[str, bool]
    files_parsed: int
    files_failed: int
