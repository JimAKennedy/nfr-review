# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the Gatling collector."""

from __future__ import annotations

from nfr_review.models import BasePayload


class GatlingResultPayload(BasePayload):
    """Payload for kind='gatling-result' evidence."""

    simulation_dir: str
    total_requests: int
    ok_requests: int
    ko_requests: int
    error_rate: float
    mean_response_time_ms: float
    p50_response_time_ms: float
    p75_response_time_ms: float
    p95_response_time_ms: float
    p99_response_time_ms: float
    min_response_time_ms: float
    max_response_time_ms: float
    requests_per_second: float


class GatlingSummaryPayload(BasePayload):
    """Payload for kind='gatling-summary' evidence."""

    simulation_count: int
    simulations: list[str]


__all__ = ["GatlingResultPayload", "GatlingSummaryPayload"]
