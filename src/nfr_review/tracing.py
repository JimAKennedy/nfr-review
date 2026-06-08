# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Optional OpenTelemetry tracing for nfr-review scan runs.

When the ``nfr-review[otel]`` extra is installed and ``NFR_OTEL_TRACES``
is set to a file path, this module exports OTLP JSON traces of the scan
pipeline: config -> detect -> collect -> evaluate -> output.

Usage::

    NFR_OTEL_TRACES=traces.ndjson nfr-review run /some/repo --score

The trace file can then be fed back to nfr-review for self-analysis::

    nfr-review run /some/repo --otel-traces traces.ndjson
"""

from __future__ import annotations

import atexit
import json
import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TRACER_NAME = "nfr-review"

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        SimpleSpanProcessor,
        SpanExporter,
        SpanExportResult,
    )

    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False

_provider: Any | None = None
_collected_spans: list[Any] = []
_trace_path: Path | None = None


class _ListExporter(SpanExporter if _HAS_OTEL else object):  # type: ignore[misc]
    """Collects finished spans into a list for later NDJSON flush."""

    def __init__(self, spans: list[Any]) -> None:
        self._spans = spans

    def export(self, spans: Any) -> Any:
        self._spans.extend(spans)
        return SpanExportResult.SUCCESS if _HAS_OTEL else None

    def shutdown(self) -> None:
        pass


def init_tracing(output_path: Path | None = None) -> None:
    """Initialise OTel tracing if the SDK is available.

    If *output_path* is ``None``, checks ``NFR_OTEL_TRACES`` env var.
    Does nothing when the OTel SDK is not installed.
    """
    global _provider, _trace_path  # noqa: PLW0603

    if not _HAS_OTEL:
        logger.debug("OTel SDK not installed -- tracing disabled")
        return

    path = output_path or os.environ.get("NFR_OTEL_TRACES")
    if not path:
        logger.debug("No trace output path -- tracing disabled")
        return

    _trace_path = Path(path)
    resource = Resource.create(
        {
            "service.name": "nfr-review",
            "service.version": "0.1.2",
        }
    )
    exporter = _ListExporter(_collected_spans)
    _provider = TracerProvider(resource=resource)
    _provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(_provider)
    atexit.register(_flush_traces)
    logger.info("OTel tracing enabled -- will write to %s", _trace_path)


def get_tracer() -> Any:
    """Return a tracer instance, or a no-op proxy if tracing is disabled."""
    if not _HAS_OTEL or _provider is None:
        return _NoOpTracer()
    return trace.get_tracer(_TRACER_NAME)


@contextmanager
def trace_phase(name: str, **attrs: Any) -> Generator[Any, None, None]:
    """Context manager that wraps a scan phase in a span."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        for k, v in attrs.items():
            span.set_attribute(k, v)
        yield span


def _flush_traces() -> None:
    """Write collected spans to NDJSON at exit."""
    if not _collected_spans or _trace_path is None:
        return

    records: list[dict[str, Any]] = []
    for span in _collected_spans:
        ctx = span.get_span_context()
        parent_id = format(span.parent.span_id, "016x") if span.parent else None
        record: dict[str, Any] = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "nfr-review"},
                            }
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": _TRACER_NAME},
                            "spans": [
                                {
                                    "traceId": format(ctx.trace_id, "032x"),
                                    "spanId": format(ctx.span_id, "016x"),
                                    "parentSpanId": parent_id or "",
                                    "name": span.name,
                                    "kind": 1,
                                    "startTimeUnixNano": span.start_time,
                                    "endTimeUnixNano": span.end_time,
                                    "attributes": _attrs_to_otlp(span.attributes or {}),
                                    "status": {
                                        "code": span.status.status_code.value
                                        if hasattr(span.status, "status_code")
                                        else 0
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        records.append(record)

    _trace_path.parent.mkdir(parents=True, exist_ok=True)
    with open(_trace_path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    logger.info("Wrote %d spans to %s", len(records), _trace_path)


def _attrs_to_otlp(
    attrs: dict[str, Any] | Any,
) -> list[dict[str, Any]]:
    """Convert span attributes to OTLP JSON format."""
    result: list[dict[str, Any]] = []
    if not isinstance(attrs, dict):
        if hasattr(attrs, "items"):
            attrs = dict(attrs)
        else:
            return result
    for key, val in attrs.items():
        if isinstance(val, bool):
            result.append({"key": key, "value": {"boolValue": val}})
        elif isinstance(val, int):
            result.append({"key": key, "value": {"intValue": str(val)}})
        elif isinstance(val, float):
            result.append({"key": key, "value": {"doubleValue": val}})
        else:
            result.append({"key": key, "value": {"stringValue": str(val)}})
    return result


class _NoOpSpan:
    """Span stand-in when OTel is not available."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoOpTracer:
    """Tracer stand-in when OTel is not available."""

    def start_as_current_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()
