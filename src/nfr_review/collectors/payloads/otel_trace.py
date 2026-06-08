# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the OTel trace collector."""

from __future__ import annotations

from nfr_review.models import BasePayload


class OtelTraceSpan(BasePayload):
    """A single normalised OTel span."""

    trace_id: str
    span_id: str
    parent_span_id: str
    name: str
    service_name: str
    kind: int  # 0=UNSPECIFIED, 1=INTERNAL, 2=SERVER, 3=CLIENT, 4=PRODUCER, 5=CONSUMER
    start_time_unix_nano: int
    end_time_unix_nano: int
    status_code: int  # 0=UNSET, 1=OK, 2=ERROR
    code_namespace: str
    code_function: str
    attributes: dict[str, str]


class OtelTracePayload(BasePayload):
    """Payload for kind='otel-trace' evidence."""

    spans: list[OtelTraceSpan]
    trace_ids: list[str]
    service_names: list[str]
    source_file: str


__all__ = ["OtelTracePayload", "OtelTraceSpan"]
