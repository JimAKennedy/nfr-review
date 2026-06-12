# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Instrumented 3-service test application for monitor pipeline E2E tests.

Runs gateway -> orders -> inventory as in-process aiohttp services with
manual OpenTelemetry SDK instrumentation.  Traces are collected in memory
and can be exported as OTLP NDJSON for baseline creation.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import SpanKind

_SERVICE_NAME = "service.name"

_SDK_TO_OTLP_KIND = {
    SpanKind.INTERNAL: 1,
    SpanKind.SERVER: 2,
    SpanKind.CLIENT: 3,
    SpanKind.PRODUCER: 4,
    SpanKind.CONSUMER: 5,
}


class _CollectingExporter(SpanExporter):
    """Thread-safe in-memory span collector shared across TracerProviders."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spans: list[ReadableSpan] = []

    def export(self, spans: Any) -> SpanExportResult:
        with self._lock:
            self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def get_spans(self) -> list[ReadableSpan]:
        with self._lock:
            return list(self._spans)

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()


def _attr_value(v: Any) -> dict[str, Any]:
    """Convert a Python value to an OTLP attribute value dict."""
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def _span_to_otlp(span: ReadableSpan) -> dict[str, Any]:
    """Convert a ReadableSpan to OTLP JSON span dict."""
    attrs: list[dict[str, Any]] = []
    if span.attributes:
        for k, v in span.attributes.items():
            attrs.append({"key": k, "value": _attr_value(v)})

    parent_span_id = ""
    if span.parent and span.parent.span_id:
        parent_span_id = format(span.parent.span_id, "016x")

    status_code = 0
    if span.status and span.status.status_code:
        status_code = span.status.status_code.value

    return {
        "traceId": format(span.context.trace_id, "032x"),
        "spanId": format(span.context.span_id, "016x"),
        "parentSpanId": parent_span_id,
        "name": span.name,
        "kind": _SDK_TO_OTLP_KIND.get(span.kind, 0),
        "startTimeUnixNano": span.start_time,
        "endTimeUnixNano": span.end_time,
        "status": {"code": status_code},
        "attributes": attrs,
    }


def spans_to_otlp_doc(spans: list[ReadableSpan]) -> dict[str, Any]:
    """Group ReadableSpans by service.name and build an OTLP resourceSpans doc."""
    by_service: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        svc = ""
        if span.resource and span.resource.attributes:
            svc = str(span.resource.attributes.get(_SERVICE_NAME, ""))
        by_service.setdefault(svc, []).append(_span_to_otlp(span))

    resource_spans: list[dict[str, Any]] = []
    for svc_name, otlp_spans in by_service.items():
        resource_spans.append(
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": svc_name}}]
                },
                "scopeSpans": [{"spans": otlp_spans}],
            }
        )
    return {"resourceSpans": resource_spans}


def spans_to_ndjson(spans: list[ReadableSpan]) -> str:
    """Serialize spans to a single NDJSON line (OTLP JSON format)."""
    doc = spans_to_otlp_doc(spans)
    return json.dumps(doc, separators=(",", ":"))


class InstrumentedApp:
    """3-service test application with OpenTelemetry instrumentation.

    Services:
        gateway   — entry point, forwards to orders
        orders    — receives from gateway, calls inventory
        inventory — leaf service, returns stock data
    """

    def __init__(self) -> None:
        self._exporter = _CollectingExporter()
        self._providers: dict[str, TracerProvider] = {}
        self._tracers: dict[str, trace.Tracer] = {}
        self._runners: list[web.AppRunner] = []
        self._ports: dict[str, int] = {}

        for name in ("gateway", "orders", "inventory"):
            resource = Resource.create({_SERVICE_NAME: name})
            provider = TracerProvider(resource=resource)
            provider.add_span_processor(SimpleSpanProcessor(self._exporter))
            self._providers[name] = provider
            self._tracers[name] = provider.get_tracer(name)

    @property
    def ports(self) -> dict[str, int]:
        return dict(self._ports)

    @property
    def gateway_url(self) -> str:
        return f"http://127.0.0.1:{self._ports['gateway']}"

    async def start(self) -> None:
        """Start all 3 services on ephemeral ports (leaf-first)."""
        await self._start_service("inventory", self._inventory_handler)
        await self._start_service("orders", self._orders_handler)
        await self._start_service("gateway", self._gateway_handler)

    async def _start_service(
        self,
        name: str,
        handler: Any,
    ) -> None:
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        sock = list(runner.sites)[0]._server.sockets[0]
        self._ports[name] = sock.getsockname()[1]
        self._runners.append(runner)

    async def _gateway_handler(self, request: web.Request) -> web.Response:
        tracer = self._tracers["gateway"]
        ctx = extract(request.headers)
        with tracer.start_as_current_span("GET /orders", context=ctx, kind=SpanKind.SERVER):
            with tracer.start_as_current_span(
                "GET /orders", kind=SpanKind.CLIENT
            ) as client_span:
                client_span.set_attribute("http.method", "GET")
                client_span.set_attribute("peer.service", "orders")
                headers: dict[str, str] = {}
                inject(headers)
                url = f"http://127.0.0.1:{self._ports['orders']}/orders"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as resp:
                        body = await resp.json()
        return web.json_response({"gateway": "ok", "orders": body})

    async def _orders_handler(self, request: web.Request) -> web.Response:
        tracer = self._tracers["orders"]
        ctx = extract(request.headers)
        with tracer.start_as_current_span("GET /orders", context=ctx, kind=SpanKind.SERVER):
            with tracer.start_as_current_span(
                "GET /stock", kind=SpanKind.CLIENT
            ) as client_span:
                client_span.set_attribute("http.method", "GET")
                client_span.set_attribute("peer.service", "inventory")
                headers: dict[str, str] = {}
                inject(headers)
                url = f"http://127.0.0.1:{self._ports['inventory']}/stock"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as resp:
                        body = await resp.json()
        return web.json_response({"orders": [{"id": 1}], "stock": body})

    async def _inventory_handler(self, request: web.Request) -> web.Response:
        tracer = self._tracers["inventory"]
        ctx = extract(request.headers)
        with tracer.start_as_current_span("GET /stock", context=ctx, kind=SpanKind.SERVER):
            pass
        return web.json_response({"items": [{"sku": "WIDGET-1", "qty": 42}]})

    def get_spans(self) -> list[ReadableSpan]:
        return self._exporter.get_spans()

    def get_otlp_doc(self) -> dict[str, Any]:
        return spans_to_otlp_doc(self.get_spans())

    def export_ndjson(self, path: Path) -> int:
        """Write collected spans to an NDJSON file. Returns span count."""
        spans = self.get_spans()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(spans_to_ndjson(spans) + "\n", encoding="utf-8")
        return len(spans)

    def clear_spans(self) -> None:
        self._exporter.clear()

    async def stop(self) -> None:
        for runner in reversed(self._runners):
            await runner.cleanup()
        for provider in self._providers.values():
            provider.shutdown()
        self._runners.clear()
        self._ports.clear()

    async def __aenter__(self) -> InstrumentedApp:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()


__all__ = ["InstrumentedApp", "spans_to_ndjson", "spans_to_otlp_doc"]
