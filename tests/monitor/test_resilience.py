# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for production resilience: backpressure, memory bounds, statsz."""

from __future__ import annotations

import pytest

from nfr_review.collectors.payloads.otel_trace import OtelTraceSpan
from nfr_review.monitor.baseline import InteractionBaseline
from nfr_review.monitor.fingerprint import InteractionFingerprint
from nfr_review.monitor.receiver import OtlpReceiver
from nfr_review.monitor.window import WindowManager

pytestmark = pytest.mark.asyncio


def _make_span(
    service: str = "svc-a",
    name: str = "GET /api",
    kind: int = 3,
) -> OtelTraceSpan:
    return OtelTraceSpan(
        trace_id="t1",
        span_id="s1",
        parent_span_id="",
        name=name,
        kind=kind,
        service_name=service,
        start_time_unix_nano=1_000_000_000,
        end_time_unix_nano=2_000_000_000,
        status_code=0,
        code_namespace="",
        code_function="",
        attributes={"http.method": "GET"},
    )


@pytest.fixture
def baseline() -> InteractionBaseline:
    return InteractionBaseline(
        source="test",
        trace_count=1,
        span_count=1,
        fingerprints=[
            InteractionFingerprint(
                caller_service="svc-a",
                callee_service="unknown",
                operation="GET /api",
                span_kind=3,
                protocol="http",
            )
        ],
    )


class TestBackpressure:
    def test_ingest_returns_true_under_limit(self, baseline: InteractionBaseline) -> None:
        wm = WindowManager(baseline, max_queue_spans=100)
        assert wm.ingest([_make_span()]) is True
        assert wm.pending_span_count == 1

    def test_ingest_returns_false_when_full(self, baseline: InteractionBaseline) -> None:
        wm = WindowManager(baseline, max_queue_spans=2)
        assert wm.ingest([_make_span(), _make_span()]) is True
        assert wm.ingest([_make_span()]) is False
        assert wm.pending_span_count == 2

    def test_is_saturated_property(self, baseline: InteractionBaseline) -> None:
        wm = WindowManager(baseline, max_queue_spans=1)
        assert not wm.is_saturated
        wm.ingest([_make_span()])
        assert wm.is_saturated

    def test_rejected_count_tracked(self, baseline: InteractionBaseline) -> None:
        wm = WindowManager(baseline, max_queue_spans=1)
        wm.ingest([_make_span()])
        wm.ingest([_make_span(), _make_span()])
        assert wm.total_rejected == 2

    def test_flush_frees_queue(self, baseline: InteractionBaseline) -> None:
        wm = WindowManager(baseline, max_queue_spans=2)
        wm.ingest([_make_span(), _make_span()])
        assert wm.is_saturated
        wm.flush()
        assert not wm.is_saturated
        assert wm.ingest([_make_span()]) is True


class TestSeenHashEviction:
    def test_evicts_when_cap_reached(self) -> None:
        """Verify _seen_hashes clears when it reaches the cap."""
        empty_bl = InteractionBaseline(
            source="test",
            trace_count=0,
            span_count=0,
            fingerprints=[],
        )
        wm = WindowManager(empty_bl, max_queue_spans=10000, max_seen_hashes=2)

        # Manually inject hashes to simulate dedup accumulation
        wm._seen_hashes.add("hash-a")
        wm._seen_hashes.add("hash-b")
        assert len(wm._seen_hashes) == 2

        # Flush with deduplicate=True should trigger eviction at cap
        wm.flush(deduplicate=True)
        assert len(wm._seen_hashes) == 0


class TestReceiverBackpressure:
    async def test_429_when_queue_full(self, aiohttp_client) -> None:
        rejected = False

        def on_spans(spans: list[OtelTraceSpan]) -> bool:
            nonlocal rejected
            if rejected:
                return False
            rejected = True
            return True

        receiver = OtlpReceiver(on_spans=on_spans, host="127.0.0.1", port=0)
        app = receiver.create_app()
        client = await aiohttp_client(app)

        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "svc-a"}}
                        ]
                    },
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "t1",
                                    "spanId": "s1",
                                    "parentSpanId": "",
                                    "name": "GET /api",
                                    "kind": 3,
                                    "startTimeUnixNano": 1000,
                                    "endTimeUnixNano": 2000,
                                    "status": {},
                                    "attributes": [],
                                }
                            ]
                        }
                    ],
                }
            ]
        }

        resp1 = await client.post("/v1/traces", json=payload)
        assert resp1.status == 200

        resp2 = await client.post("/v1/traces", json=payload)
        assert resp2.status == 429
        assert resp2.headers.get("Retry-After") == "5"
        assert receiver.backpressure_count == 1


class TestStatsEndpoint:
    async def test_statsz_returns_counters(self, aiohttp_client) -> None:
        def on_spans(spans: list[OtelTraceSpan]) -> bool:
            return True

        def stats_cb() -> dict[str, object]:
            return {"queue_depth": 42, "alerts_emitted": 7}

        receiver = OtlpReceiver(
            on_spans=on_spans,
            host="127.0.0.1",
            port=0,
            stats_callback=stats_cb,
        )
        app = receiver.create_app()
        client = await aiohttp_client(app)

        resp = await client.get("/statsz")
        assert resp.status == 200
        data = await resp.json()
        assert data["spans_received"] == 0
        assert data["requests_total"] == 0
        assert data["backpressure_count"] == 0
        assert data["queue_depth"] == 42
        assert data["alerts_emitted"] == 7

    async def test_statsz_without_callback(self, aiohttp_client) -> None:
        def on_spans(spans: list[OtelTraceSpan]) -> bool:
            return True

        receiver = OtlpReceiver(on_spans=on_spans, host="127.0.0.1", port=0)
        app = receiver.create_app()
        client = await aiohttp_client(app)

        resp = await client.get("/statsz")
        assert resp.status == 200
        data = await resp.json()
        assert "spans_received" in data
        assert "queue_depth" not in data
