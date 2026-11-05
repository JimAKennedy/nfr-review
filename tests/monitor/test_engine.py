# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the monitor engine."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest

from nfr_review.monitor.baseline import InteractionBaseline, save_baseline
from nfr_review.monitor.engine import MonitorConfig, MonitorEngine, _format_alert
from nfr_review.monitor.window import WindowResult

pytestmark = pytest.mark.asyncio


@pytest.fixture
def baseline_file(tmp_path: Path) -> Path:
    bl = InteractionBaseline(
        source="test",
        trace_count=1,
        span_count=1,
        fingerprints=[],
    )
    p = tmp_path / "baseline.json"
    save_baseline(bl, p)
    return p


@pytest.fixture
def config(baseline_file: Path) -> MonitorConfig:
    return MonitorConfig(
        baseline_path=baseline_file,
        host="127.0.0.1",
        port=0,
        window_seconds=0.2,
    )


class TestFormatAlert:
    def test_produces_valid_json(self) -> None:
        from nfr_review.models import Finding

        f = Finding(
            rule_id="mon-novel-interaction",
            rag="red",
            severity="high",
            summary="Test novel",
            recommendation="Check it",
            evidence_locator="fingerprint:abc123",
            collector_name="test",
            collector_version="0.1.0",
            confidence=0.9,
            pattern_tag="novel-http",
        )
        wr = WindowResult(
            window_start=0.0,
            window_end=1.0,
            span_count=10,
            fingerprint_count=3,
            novel_findings=[f],
            novel_count=1,
            disappeared_count=0,
        )
        line = _format_alert(f, wr)
        parsed = json.loads(line)
        assert parsed["finding_rule_id"] == "mon-novel-interaction"
        assert parsed["finding_severity"] == "high"
        assert parsed["window_span_count"] == 10


class TestMonitorEngineLifecycle:
    async def test_engine_loads_baseline(self, config: MonitorConfig) -> None:
        alert_buf = io.StringIO()
        engine = MonitorEngine(config, alert_stream=alert_buf)
        bl = engine._load_baseline()
        assert bl.source == "test"
        assert len(bl.fingerprints) == 0

    async def test_engine_starts_and_stops(self, config: MonitorConfig) -> None:
        alert_buf = io.StringIO()
        engine = MonitorEngine(config, alert_stream=alert_buf)

        async def stop_soon():
            await asyncio.sleep(0.3)
            engine._request_shutdown()

        task = asyncio.create_task(engine.run())
        stop_task = asyncio.create_task(stop_soon())
        await asyncio.gather(task, stop_task)
        assert engine.receiver is not None
        assert engine.window_manager is not None

    async def test_engine_emits_alerts_for_novel_spans(self, config: MonitorConfig) -> None:
        alert_buf = io.StringIO()
        config.window_seconds = 0.15
        engine = MonitorEngine(config, alert_stream=alert_buf)

        async def send_and_stop():
            await asyncio.sleep(0.05)
            from nfr_review.collectors.payloads.otel_trace import OtelTraceSpan

            span = OtelTraceSpan(
                trace_id="t1",
                span_id="s1",
                parent_span_id="",
                name="GET /novel",
                service_name="svc-a",
                kind=3,
                start_time_unix_nano=1000,
                end_time_unix_nano=2000,
                status_code=0,
                code_namespace="",
                code_function="",
                attributes={"http.method": "GET", "peer.service": "svc-b"},
            )
            assert engine.window_manager is not None
            engine.window_manager.ingest([span])
            await asyncio.sleep(0.3)
            engine._request_shutdown()

        task = asyncio.create_task(engine.run())
        helper = asyncio.create_task(send_and_stop())
        await asyncio.gather(task, helper)

        output = alert_buf.getvalue()
        assert output.strip() != ""
        for line in output.strip().splitlines():
            parsed = json.loads(line)
            assert parsed["finding_rule_id"] == "mon-novel-interaction"
