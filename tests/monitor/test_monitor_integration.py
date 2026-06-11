# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Integration test: start monitor, send OTLP traffic, verify alerts."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import aiohttp
import pytest

from nfr_review.monitor.baseline import InteractionBaseline, save_baseline
from nfr_review.monitor.engine import MonitorConfig, MonitorEngine
from nfr_review.monitor.fingerprint import InteractionFingerprint

pytestmark = pytest.mark.asyncio


def _make_otlp_payload(
    caller: str,
    callee: str,
    operation: str,
    *,
    span_id: str = "s1",
    parent_span_id: str = "",
) -> dict:
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": caller}}]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "t1",
                                "spanId": span_id,
                                "parentSpanId": parent_span_id,
                                "name": operation,
                                "kind": 3,
                                "startTimeUnixNano": 1000000000,
                                "endTimeUnixNano": 2000000000,
                                "status": {"code": 0},
                                "attributes": [
                                    {
                                        "key": "http.method",
                                        "value": {"stringValue": "GET"},
                                    },
                                    {
                                        "key": "peer.service",
                                        "value": {"stringValue": callee},
                                    },
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }


@pytest.fixture
def known_fingerprint() -> InteractionFingerprint:
    return InteractionFingerprint(
        caller_service="svc-a",
        callee_service="svc-b",
        operation="GET /known",
        span_kind=3,
        protocol="http",
    )


@pytest.fixture
def baseline_file(tmp_path: Path, known_fingerprint: InteractionFingerprint) -> Path:
    bl = InteractionBaseline(
        source="test-uat",
        trace_count=1,
        span_count=1,
        fingerprints=[known_fingerprint],
    )
    p = tmp_path / "baseline.json"
    save_baseline(bl, p)
    return p


async def test_full_monitor_lifecycle(baseline_file: Path) -> None:
    """Start monitor, send known + novel spans, verify alert output."""
    alert_buf = io.StringIO()
    config = MonitorConfig(
        baseline_path=baseline_file,
        host="127.0.0.1",
        port=0,
        window_seconds=0.2,
    )
    engine = MonitorEngine(config, alert_stream=alert_buf)

    async def drive_traffic():
        await asyncio.sleep(0.05)
        assert engine.receiver is not None

        runner = engine._runner
        assert runner is not None
        sites = runner.sites
        assert len(sites) > 0
        site = list(sites)[0]
        port = site._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        async with aiohttp.ClientSession() as session:
            resp = await session.get(f"{base}/healthz")
            assert resp.status == 200

            resp = await session.get(f"{base}/readyz")
            assert resp.status == 200

            known_payload = _make_otlp_payload("svc-a", "svc-b", "GET /known")
            resp = await session.post(f"{base}/v1/traces", json=known_payload)
            assert resp.status == 200

            novel_payload = _make_otlp_payload(
                "svc-a", "svc-c", "POST /admin/users", span_id="s2"
            )
            resp = await session.post(f"{base}/v1/traces", json=novel_payload)
            assert resp.status == 200

        await asyncio.sleep(0.4)
        engine._request_shutdown()

    task = asyncio.create_task(engine.run())
    driver = asyncio.create_task(drive_traffic())
    await asyncio.gather(task, driver)

    output = alert_buf.getvalue().strip()
    assert output, "expected at least one alert line"
    alerts = [json.loads(line) for line in output.splitlines()]
    novel_alerts = [a for a in alerts if a["finding_rule_id"] == "mon-novel-interaction"]
    assert len(novel_alerts) >= 1
    assert any("svc-c" in a["finding_summary"] for a in novel_alerts)


async def test_monitor_no_alerts_for_known_traffic(baseline_file: Path) -> None:
    """Known traffic only — no alerts expected."""
    alert_buf = io.StringIO()
    config = MonitorConfig(
        baseline_path=baseline_file,
        host="127.0.0.1",
        port=0,
        window_seconds=0.15,
    )
    engine = MonitorEngine(config, alert_stream=alert_buf)

    async def drive_known():
        await asyncio.sleep(0.05)
        assert engine.receiver is not None

        runner = engine._runner
        assert runner is not None
        site = list(runner.sites)[0]
        port = site._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        async with aiohttp.ClientSession() as session:
            payload = _make_otlp_payload("svc-a", "svc-b", "GET /known")
            resp = await session.post(f"{base}/v1/traces", json=payload)
            assert resp.status == 200

        await asyncio.sleep(0.3)
        engine._request_shutdown()

    task = asyncio.create_task(engine.run())
    driver = asyncio.create_task(drive_known())
    await asyncio.gather(task, driver)

    output = alert_buf.getvalue().strip()
    if output:
        alerts = [json.loads(line) for line in output.splitlines()]
        novel = [a for a in alerts if a["finding_rule_id"] == "mon-novel-interaction"]
        assert len(novel) == 0, f"unexpected novel alerts: {novel}"
