# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""OTLP HTTP receiver — accepts POST /v1/traces and converts to OtelTraceSpan."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from aiohttp import web

from nfr_review.collectors.otel_trace import _parse_resource_spans
from nfr_review.collectors.payloads.otel_trace import OtelTraceSpan

logger = logging.getLogger(__name__)

SpanCallback = Callable[[list[OtelTraceSpan]], None]


class OtlpReceiver:
    """HTTP server that receives OTLP JSON trace exports.

    Accepts ``POST /v1/traces`` with JSON-encoded OTLP payloads and
    forwards parsed spans to a callback.  Serves ``/healthz`` and
    ``/readyz`` for container orchestration.
    """

    def __init__(
        self,
        *,
        on_spans: SpanCallback,
        host: str = "0.0.0.0",  # nosec B104
        port: int = 4318,
        max_body_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        self._on_spans = on_spans
        self._host = host
        self._port = port
        self._max_body_bytes = max_body_bytes
        self._ready = False
        self._spans_received: int = 0
        self._requests_total: int = 0
        self._app: web.Application | None = None

    @property
    def ready(self) -> bool:
        return self._ready

    @ready.setter
    def ready(self, value: bool) -> None:
        self._ready = value

    @property
    def spans_received(self) -> int:
        return self._spans_received

    @property
    def requests_total(self) -> int:
        return self._requests_total

    def create_app(self) -> web.Application:
        app = web.Application(client_max_size=self._max_body_bytes)
        app.router.add_post("/v1/traces", self._handle_traces)
        app.router.add_get("/healthz", self._handle_healthz)
        app.router.add_get("/readyz", self._handle_readyz)
        self._app = app
        return app

    async def _handle_traces(self, request: web.Request) -> web.Response:
        self._requests_total += 1
        try:
            body = await request.read()
        except (ConnectionError, OSError):
            logger.warning("failed to read request body")
            return web.Response(status=400, text="bad request")

        try:
            doc: dict[str, Any] = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("invalid JSON in trace request")
            return web.Response(status=400, text="invalid JSON")

        spans = _parse_resource_spans(doc)
        if spans:
            self._spans_received += len(spans)
            try:
                self._on_spans(spans)
            except Exception:
                logger.exception("span callback failed")
                return web.Response(status=500, text="internal error")

        return web.json_response(
            {"partialSuccess": {}},
            status=200,
        )

    async def _handle_healthz(self, _request: web.Request) -> web.Response:
        return web.Response(status=200, text="ok")

    async def _handle_readyz(self, _request: web.Request) -> web.Response:
        if self._ready:
            return web.Response(status=200, text="ready")
        return web.Response(status=503, text="not ready")


__all__ = ["OtlpReceiver", "SpanCallback"]
