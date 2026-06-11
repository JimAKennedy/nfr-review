# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the OTLP HTTP receiver."""

from __future__ import annotations

import pytest

from nfr_review.collectors.payloads.otel_trace import OtelTraceSpan
from nfr_review.monitor.receiver import OtlpReceiver

pytestmark = pytest.mark.asyncio


def _make_otlp_payload(
    service: str = "svc-a",
    span_name: str = "GET /api",
    kind: int = 3,
    trace_id: str = "abc123",
    span_id: str = "def456",
    parent_span_id: str = "",
) -> dict:
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": service},
                        }
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "parentSpanId": parent_span_id,
                                "name": span_name,
                                "kind": kind,
                                "startTimeUnixNano": 1000000000,
                                "endTimeUnixNano": 2000000000,
                                "status": {"code": 0},
                                "attributes": [
                                    {
                                        "key": "http.method",
                                        "value": {"stringValue": "GET"},
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }


@pytest.fixture
def collected_spans() -> list[list[OtelTraceSpan]]:
    return []


@pytest.fixture
def receiver(collected_spans: list[list[OtelTraceSpan]]) -> OtlpReceiver:
    def on_spans(spans: list[OtelTraceSpan]) -> bool:
        collected_spans.append(spans)
        return True

    return OtlpReceiver(on_spans=on_spans, host="127.0.0.1", port=0)


@pytest.fixture
def app(receiver: OtlpReceiver):
    return receiver.create_app()


async def test_post_valid_traces(
    aiohttp_client,
    app,
    receiver: OtlpReceiver,
    collected_spans: list[list[OtelTraceSpan]],
) -> None:
    client = await aiohttp_client(app)
    payload = _make_otlp_payload()
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status == 200
    body = await resp.json()
    assert "partialSuccess" in body
    assert len(collected_spans) == 1
    assert len(collected_spans[0]) == 1
    assert collected_spans[0][0].service_name == "svc-a"
    assert receiver.spans_received == 1
    assert receiver.requests_total == 1


async def test_post_invalid_json(
    aiohttp_client,
    app,
    receiver: OtlpReceiver,
) -> None:
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/traces",
        data=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400
    assert receiver.requests_total == 1
    assert receiver.spans_received == 0


async def test_post_empty_resource_spans(
    aiohttp_client,
    app,
    collected_spans: list[list[OtelTraceSpan]],
) -> None:
    client = await aiohttp_client(app)
    resp = await client.post("/v1/traces", json={"resourceSpans": []})
    assert resp.status == 200
    assert len(collected_spans) == 0


async def test_healthz(aiohttp_client, app) -> None:
    client = await aiohttp_client(app)
    resp = await client.get("/healthz")
    assert resp.status == 200
    text = await resp.text()
    assert text == "ok"


async def test_readyz_not_ready(aiohttp_client, app, receiver: OtlpReceiver) -> None:
    client = await aiohttp_client(app)
    assert not receiver.ready
    resp = await client.get("/readyz")
    assert resp.status == 503


async def test_readyz_ready(aiohttp_client, app, receiver: OtlpReceiver) -> None:
    client = await aiohttp_client(app)
    receiver.ready = True
    resp = await client.get("/readyz")
    assert resp.status == 200
    text = await resp.text()
    assert text == "ready"


async def test_multiple_spans_in_payload(
    aiohttp_client,
    app,
    collected_spans: list[list[OtelTraceSpan]],
    receiver: OtlpReceiver,
) -> None:
    client = await aiohttp_client(app)
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "svc-a"}}]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "t1",
                                "spanId": "s1",
                                "parentSpanId": "",
                                "name": "op1",
                                "kind": 2,
                                "startTimeUnixNano": 1000,
                                "endTimeUnixNano": 2000,
                                "status": {},
                                "attributes": [],
                            },
                            {
                                "traceId": "t1",
                                "spanId": "s2",
                                "parentSpanId": "s1",
                                "name": "op2",
                                "kind": 3,
                                "startTimeUnixNano": 1100,
                                "endTimeUnixNano": 1900,
                                "status": {},
                                "attributes": [],
                            },
                        ]
                    }
                ],
            }
        ]
    }
    resp = await client.post("/v1/traces", json=payload)
    assert resp.status == 200
    assert len(collected_spans) == 1
    assert len(collected_spans[0]) == 2
    assert receiver.spans_received == 2
