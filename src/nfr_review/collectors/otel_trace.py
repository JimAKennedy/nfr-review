# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""OTel trace collector — parses OTLP JSON / NDJSON trace exports and
normalises them into ``OtelTracePayload`` evidence.

Evidence payload contract (kind="otel-trace"):
    spans: list[OtelTraceSpan] — normalised span records
    trace_ids: list[str] — unique trace IDs found
    service_names: list[str] — unique service names found
    source_file: str — path to the ingested file
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.otel_trace import OtelTracePayload, OtelTraceSpan
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.otel_trace")


# ---------------------------------------------------------------------------
# OTLP attribute helpers
# ---------------------------------------------------------------------------


def _flatten_otlp_attributes(attrs: list[dict[str, Any]]) -> dict[str, str]:
    """Convert OTLP ``[{"key": "k", "value": {"stringValue": "v"}}]`` to a
    flat ``dict[str, str]``.  Non-string values are stringified.
    """
    flat: dict[str, str] = {}
    for entry in attrs:
        key = entry.get("key", "")
        value_obj = entry.get("value", {})
        if not isinstance(value_obj, dict):
            flat[key] = str(value_obj)
            continue
        # OTLP value wrappers: stringValue, intValue, boolValue, doubleValue, ...
        for vk in ("stringValue", "intValue", "boolValue", "doubleValue"):
            if vk in value_obj:
                flat[key] = str(value_obj[vk])
                break
        else:
            # arrayValue / kvlistValue — store JSON representation
            flat[key] = json.dumps(value_obj)
    return flat


def _extract_service_name(resource: dict[str, Any]) -> str:
    """Extract ``service.name`` from OTLP resource attributes."""
    for attr in resource.get("attributes", []):
        if attr.get("key") == "service.name":
            value_obj = attr.get("value", {})
            if isinstance(value_obj, dict):
                return str(value_obj.get("stringValue", ""))
            return str(value_obj)
    return ""


# ---------------------------------------------------------------------------
# Span normalisation
# ---------------------------------------------------------------------------


def _normalise_span(
    raw_span: dict[str, Any],
    service_name: str,
) -> OtelTraceSpan:
    """Build an ``OtelTraceSpan`` from a raw OTLP span dict."""
    attrs = _flatten_otlp_attributes(raw_span.get("attributes", []))
    status = raw_span.get("status", {}) or {}

    return OtelTraceSpan(
        trace_id=raw_span.get("traceId", ""),
        span_id=raw_span.get("spanId", ""),
        parent_span_id=raw_span.get("parentSpanId", ""),
        name=raw_span.get("name", ""),
        service_name=service_name,
        kind=int(raw_span.get("kind", 0)),
        start_time_unix_nano=int(raw_span.get("startTimeUnixNano", 0)),
        end_time_unix_nano=int(raw_span.get("endTimeUnixNano", 0)),
        status_code=int(status.get("code", 0)),
        code_namespace=attrs.get("code.namespace", ""),
        code_function=attrs.get("code.function", ""),
        attributes=attrs,
    )


# ---------------------------------------------------------------------------
# OTLP JSON / NDJSON parsing
# ---------------------------------------------------------------------------


def _parse_resource_spans(doc: dict[str, Any]) -> list[OtelTraceSpan]:
    """Parse a single OTLP JSON document with ``resourceSpans``."""
    spans: list[OtelTraceSpan] = []
    for rs in doc.get("resourceSpans", []):
        resource = rs.get("resource", {}) or {}
        service_name = _extract_service_name(resource)
        for scope_spans in rs.get("scopeSpans", []):
            for raw_span in scope_spans.get("spans", []):
                spans.append(_normalise_span(raw_span, service_name))
    return spans


def _parse_otlp_file(text: str) -> list[OtelTraceSpan]:
    """Parse an OTLP JSON file.  Supports both single-object and NDJSON."""
    stripped = text.strip()
    if not stripped:
        return []

    # Try single OTLP JSON object first
    if stripped.startswith("{"):
        try:
            doc = json.loads(stripped)
            if "resourceSpans" in doc:
                return _parse_resource_spans(doc)
        except json.JSONDecodeError:
            pass

    # Fall back to NDJSON (one JSON object per line)
    spans: list[OtelTraceSpan] = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Skipping unparseable NDJSON line: %.80s", line)
            continue
        if "resourceSpans" in doc:
            spans.extend(_parse_resource_spans(doc))
    return spans


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class OtelTraceCollector:
    name = "otel-trace"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        traces_path_raw = getattr(config, "otel_traces", None)
        if not traces_path_raw:
            return []

        traces_path = Path(traces_path_raw)
        if not traces_path.is_absolute():
            traces_path = repo_path / traces_path

        if not traces_path.is_file():
            logger.debug("otel_traces path does not exist: %s", traces_path)
            return []

        try:
            text = traces_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.debug("Cannot read %s: %s", traces_path, exc)
            return []

        try:
            spans = _parse_otlp_file(text)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to parse OTLP trace file %s", traces_path, exc_info=True)
            return []

        if not spans:
            return []

        trace_ids = sorted(set(s.trace_id for s in spans if s.trace_id))
        service_names = sorted(set(s.service_name for s in spans if s.service_name))

        try:
            rel = str(traces_path.relative_to(repo_path))
        except ValueError:
            rel = str(traces_path)

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=rel,
                kind="otel-trace",
                payload=OtelTracePayload(
                    spans=spans,
                    trace_ids=trace_ids,
                    service_names=service_names,
                    source_file=rel,
                ),
            )
        ]


def _register() -> None:
    if "otel-trace" not in collector_registry:
        collector_registry.register("otel-trace", OtelTraceCollector())


_register()

__all__ = ["OtelTraceCollector"]
