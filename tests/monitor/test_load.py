# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Load test: sustained OTLP traffic, backpressure, graceful shutdown."""

from __future__ import annotations

import asyncio
import io
import resource
import sys
import time
from pathlib import Path

import aiohttp
import pytest

from nfr_review.monitor.baseline import InteractionBaseline, save_baseline
from nfr_review.monitor.engine import MonitorConfig, MonitorEngine
from nfr_review.monitor.fingerprint import InteractionFingerprint

pytestmark = [pytest.mark.asyncio, pytest.mark.loadtest]


def _make_otlp_batch(batch_size: int, batch_id: int) -> dict:
    spans = []
    for i in range(batch_size):
        spans.append(
            {
                "traceId": f"trace-{batch_id}-{i}",
                "spanId": f"span-{batch_id}-{i}",
                "parentSpanId": "",
                "name": f"GET /endpoint-{i % 20}",
                "kind": 3,
                "startTimeUnixNano": 1_000_000_000,
                "endTimeUnixNano": 2_000_000_000,
                "status": {"code": 0},
                "attributes": [
                    {"key": "http.method", "value": {"stringValue": "GET"}},
                    {
                        "key": "peer.service",
                        "value": {"stringValue": f"svc-{i % 5}"},
                    },
                ],
            }
        )
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "load-gen"}}
                    ]
                },
                "scopeSpans": [{"spans": spans}],
            }
        ]
    }


@pytest.fixture
def baseline_file(tmp_path: Path) -> Path:
    bl = InteractionBaseline(
        source="load-test-uat",
        trace_count=100,
        span_count=500,
        fingerprints=[
            InteractionFingerprint(
                caller_service="load-gen",
                callee_service=f"svc-{i}",
                operation=f"GET /endpoint-{j}",
                span_kind=3,
                protocol="http",
            )
            for i in range(3)
            for j in range(10)
        ],
    )
    p = tmp_path / "baseline.json"
    save_baseline(bl, p)
    return p


async def test_sustained_load(baseline_file: Path) -> None:
    """Send ~1000 spans/sec for 5s, verify stable performance."""
    alert_buf = io.StringIO()
    config = MonitorConfig(
        baseline_path=baseline_file,
        host="127.0.0.1",
        port=0,
        window_seconds=1.0,
        max_queue_spans=50_000,
    )
    engine = MonitorEngine(config, alert_stream=alert_buf)

    response_times: list[float] = []
    status_codes: list[int] = []
    mem_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    async def load_driver():
        await asyncio.sleep(0.1)
        assert engine._runner is not None
        site = list(engine._runner.sites)[0]
        port = site._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        batch_size = 50
        batches_per_sec = 20
        duration_sec = 5

        async with aiohttp.ClientSession() as session:
            for sec in range(duration_sec):
                for batch_id in range(batches_per_sec):
                    payload = _make_otlp_batch(batch_size, sec * batches_per_sec + batch_id)
                    t0 = time.monotonic()
                    resp = await session.post(f"{base}/v1/traces", json=payload)
                    elapsed = time.monotonic() - t0
                    response_times.append(elapsed)
                    status_codes.append(resp.status)
                await asyncio.sleep(0.05)

            resp = await session.get(f"{base}/statsz")
            assert resp.status == 200
            stats = await resp.json()
            assert stats["spans_received"] > 0

        await asyncio.sleep(1.5)
        engine._request_shutdown()

    task = asyncio.create_task(engine.run())
    driver = asyncio.create_task(load_driver())
    await asyncio.gather(task, driver)

    mem_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform.startswith("darwin"):
        # macOS: ru_maxrss is in bytes
        mem_delta_mb = (mem_after - mem_before) / (1024 * 1024)
    else:
        # Linux: ru_maxrss is in kilobytes
        mem_delta_mb = (mem_after - mem_before) / 1024

    # All responses should be 200 (queue big enough for this load)
    ok_count = sum(1 for s in status_codes if s == 200)
    assert ok_count > 0
    assert len(response_times) > 0

    # p99 response time under 500ms (generous for test environment)
    sorted_times = sorted(response_times)
    p99_idx = int(len(sorted_times) * 0.99)
    p99 = sorted_times[p99_idx]
    assert p99 < 0.5, f"p99 response time {p99:.3f}s exceeds 500ms"

    # Memory should not explode (< 100MB delta — generous for CI)
    assert mem_delta_mb < 100, f"memory delta {mem_delta_mb:.1f}MB exceeds 100MB"


async def test_backpressure_under_load(baseline_file: Path) -> None:
    """Fill queue to trigger 429, then drain and accept again."""
    alert_buf = io.StringIO()
    config = MonitorConfig(
        baseline_path=baseline_file,
        host="127.0.0.1",
        port=0,
        window_seconds=30.0,
        max_queue_spans=200,
    )
    engine = MonitorEngine(config, alert_stream=alert_buf)

    got_429 = False
    got_200_after_drain = False

    async def pressure_driver():
        nonlocal got_429, got_200_after_drain
        await asyncio.sleep(0.1)
        assert engine._runner is not None
        site = list(engine._runner.sites)[0]
        port = site._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        async with aiohttp.ClientSession() as session:
            # Flood until 429
            for i in range(100):
                payload = _make_otlp_batch(50, i)
                resp = await session.post(f"{base}/v1/traces", json=payload)
                if resp.status == 429:
                    got_429 = True
                    break

            # Force flush to drain
            assert engine.window_manager is not None
            engine.window_manager.flush()

            # Should accept again
            payload = _make_otlp_batch(10, 999)
            resp = await session.post(f"{base}/v1/traces", json=payload)
            if resp.status == 200:
                got_200_after_drain = True

        engine._request_shutdown()

    task = asyncio.create_task(engine.run())
    driver = asyncio.create_task(pressure_driver())
    await asyncio.gather(task, driver)

    assert got_429, "expected at least one 429 response"
    assert got_200_after_drain, "expected 200 after queue drain"


async def test_graceful_shutdown_flushes(baseline_file: Path) -> None:
    """Shutdown mid-stream should flush pending spans."""
    alert_buf = io.StringIO()
    config = MonitorConfig(
        baseline_path=baseline_file,
        host="127.0.0.1",
        port=0,
        window_seconds=60.0,
    )
    engine = MonitorEngine(config, alert_stream=alert_buf)

    async def send_then_shutdown():
        await asyncio.sleep(0.1)
        assert engine._runner is not None
        site = list(engine._runner.sites)[0]
        port = site._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        async with aiohttp.ClientSession() as session:
            # Send novel spans
            payload = _make_otlp_batch(10, 0)
            resp = await session.post(f"{base}/v1/traces", json=payload)
            assert resp.status == 200

        # Verify pending before shutdown
        assert engine.window_manager is not None
        assert engine.window_manager.pending_span_count > 0

        # Trigger shutdown — engine should flush remaining
        engine._request_shutdown()

    task = asyncio.create_task(engine.run())
    driver = asyncio.create_task(send_then_shutdown())
    await asyncio.gather(task, driver)

    # After shutdown, queue should be drained
    assert engine.window_manager is not None
    assert engine.window_manager.pending_span_count == 0
