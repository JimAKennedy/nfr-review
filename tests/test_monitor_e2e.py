# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""End-to-end workflow test: baseline create → baseline diff → live monitor.

Exercises the full CLI-to-engine pipeline using real trace fixtures.
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import aiohttp
import pytest
from click.testing import CliRunner

from nfr_review.cli import cli
from nfr_review.monitor.baseline import load_baseline, save_baseline
from nfr_review.monitor.engine import MonitorConfig, MonitorEngine
from nfr_review.monitor.fingerprint import InteractionFingerprint

MULTI_SVC = Path("tests/fixtures/otel-traces/traces-multi-service.ndjson")
TOPOLOGY = Path("tests/fixtures/otel-traces/traces-multi-service-topology.json")


class TestBaselineWorkflowE2E:
    """Create a baseline via CLI, diff against a different fixture, verify findings."""

    def test_create_then_diff_finds_novel(self, tmp_path: Path) -> None:
        bl_path = tmp_path / "baseline.json"
        result = CliRunner().invoke(
            cli,
            ["baseline", "create", "--otel-traces", str(MULTI_SVC), "-o", str(bl_path)],
        )
        assert result.exit_code == 0, result.output

        bl = load_baseline(bl_path)
        assert len(bl.fingerprints) > 0

        result = CliRunner().invoke(
            cli,
            ["baseline", "diff", "--baseline", str(bl_path), "--otel-traces", str(TOPOLOGY)],
        )
        assert result.exit_code == 0, result.output
        assert (
            "Novel Interactions" in result.output
            or "Disappeared Interactions" in result.output
        )

    def test_create_then_diff_json_pipeline(self, tmp_path: Path) -> None:
        bl_path = tmp_path / "baseline.json"
        diff_out = tmp_path / "findings.jsonl"

        CliRunner().invoke(
            cli,
            ["baseline", "create", "--otel-traces", str(MULTI_SVC), "-o", str(bl_path)],
        )
        result = CliRunner().invoke(
            cli,
            [
                "baseline",
                "diff",
                "--baseline",
                str(bl_path),
                "--otel-traces",
                str(TOPOLOGY),
                "--format",
                "json",
                "-o",
                str(diff_out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert diff_out.exists()

        lines = [ln for ln in diff_out.read_text().strip().split("\n") if ln.strip()]
        for line in lines:
            finding = json.loads(line)
            assert finding["rule_id"] in (
                "mon-novel-interaction",
                "mon-disappeared-interaction",
            )

    def test_create_same_fixture_diff_no_findings(self, tmp_path: Path) -> None:
        bl_path = tmp_path / "baseline.json"
        CliRunner().invoke(
            cli,
            ["baseline", "create", "--otel-traces", str(MULTI_SVC), "-o", str(bl_path)],
        )
        result = CliRunner().invoke(
            cli,
            ["baseline", "diff", "--baseline", str(bl_path), "--otel-traces", str(MULTI_SVC)],
        )
        assert result.exit_code == 0
        assert "No differences found" in result.output


def _build_otlp_payload(
    caller: str,
    callee: str,
    operation: str,
    span_id: str = "e2e01",
    kind: int = 3,
) -> dict:
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": caller}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "e2e00000000000000000000000000001",
                                "spanId": span_id,
                                "parentSpanId": "",
                                "name": operation,
                                "kind": kind,
                                "startTimeUnixNano": 1000000000,
                                "endTimeUnixNano": 2000000000,
                                "status": {"code": 0},
                                "attributes": [
                                    {"key": "http.method", "value": {"stringValue": "GET"}},
                                    {"key": "peer.service", "value": {"stringValue": callee}},
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }


@pytest.mark.asyncio
class TestMonitorE2E:
    """Monitor from CLI-created baseline, post live traffic, verify alerts."""

    @pytest.fixture
    def cli_baseline(self, tmp_path: Path) -> Path:
        bl_path = tmp_path / "baseline.json"
        result = CliRunner().invoke(
            cli,
            ["baseline", "create", "--otel-traces", str(MULTI_SVC), "-o", str(bl_path)],
        )
        assert result.exit_code == 0, result.output
        return bl_path

    @pytest.fixture
    def partial_baseline(self, tmp_path: Path) -> Path:
        fp = InteractionFingerprint(
            caller_service="api-gateway",
            callee_service="greeting-service",
            operation="GET /api/greetings",
            span_kind=2,
            protocol="http",
        )
        from nfr_review.monitor.baseline import InteractionBaseline

        bl = InteractionBaseline(
            source="partial-uat", trace_count=1, span_count=1, fingerprints=[fp]
        )
        p = tmp_path / "partial.json"
        save_baseline(bl, p)
        return p

    async def test_full_workflow_cli_baseline_to_monitor(self, cli_baseline: Path) -> None:
        alert_buf = io.StringIO()
        config = MonitorConfig(
            baseline_path=cli_baseline,
            host="127.0.0.1",
            port=0,
            window_seconds=0.2,
        )
        engine = MonitorEngine(config, alert_stream=alert_buf)

        async def drive():
            await asyncio.sleep(0.05)
            assert engine.receiver is not None
            runner = engine._runner
            assert runner is not None
            site = list(runner.sites)[0]
            port = site._server.sockets[0].getsockname()[1]
            base = f"http://127.0.0.1:{port}"

            async with aiohttp.ClientSession() as session:
                resp = await session.get(f"{base}/healthz")
                assert resp.status == 200

                resp = await session.get(f"{base}/readyz")
                assert resp.status == 200

                novel = _build_otlp_payload(
                    "unknown-svc", "secret-backend", "POST /admin/nuke", span_id="novel01"
                )
                resp = await session.post(f"{base}/v1/traces", json=novel)
                assert resp.status == 200

            await asyncio.sleep(0.4)
            engine._request_shutdown()

        task = asyncio.create_task(engine.run())
        driver = asyncio.create_task(drive())
        await asyncio.gather(task, driver)

        output = alert_buf.getvalue().strip()
        assert output, "expected at least one alert"
        alerts = [json.loads(line) for line in output.splitlines()]
        novel_alerts = [a for a in alerts if a["finding_rule_id"] == "mon-novel-interaction"]
        assert len(novel_alerts) >= 1
        assert any("secret-backend" in a["finding_summary"] for a in novel_alerts)

    async def test_statsz_endpoint(self, partial_baseline: Path) -> None:
        alert_buf = io.StringIO()
        config = MonitorConfig(
            baseline_path=partial_baseline,
            host="127.0.0.1",
            port=0,
            window_seconds=0.2,
        )
        engine = MonitorEngine(config, alert_stream=alert_buf)

        async def check_statsz():
            await asyncio.sleep(0.05)
            runner = engine._runner
            assert runner is not None
            site = list(runner.sites)[0]
            port = site._server.sockets[0].getsockname()[1]
            base = f"http://127.0.0.1:{port}"

            async with aiohttp.ClientSession() as session:
                payload = _build_otlp_payload("x", "y", "GET /foo")
                await session.post(f"{base}/v1/traces", json=payload)

                resp = await session.get(f"{base}/statsz")
                assert resp.status == 200
                stats = await resp.json()
                assert "spans_received" in stats
                assert "requests_total" in stats
                assert stats["requests_total"] >= 1
                assert "alerts_emitted" in stats

            engine._request_shutdown()

        task = asyncio.create_task(engine.run())
        driver = asyncio.create_task(check_statsz())
        await asyncio.gather(task, driver)

    async def test_known_traffic_no_alerts(self, cli_baseline: Path) -> None:
        """Send only traffic matching the baseline — no novel alerts expected."""
        bl = load_baseline(cli_baseline)
        if not bl.fingerprints:
            pytest.skip("baseline has no fingerprints")

        fp = bl.fingerprints[0]
        alert_buf = io.StringIO()
        config = MonitorConfig(
            baseline_path=cli_baseline,
            host="127.0.0.1",
            port=0,
            window_seconds=0.15,
        )
        engine = MonitorEngine(config, alert_stream=alert_buf)

        async def send_known():
            await asyncio.sleep(0.05)
            runner = engine._runner
            assert runner is not None
            site = list(runner.sites)[0]
            port = site._server.sockets[0].getsockname()[1]
            base = f"http://127.0.0.1:{port}"

            payload = _build_otlp_payload(
                fp.caller_service, fp.callee_service, fp.operation, kind=fp.span_kind
            )
            async with aiohttp.ClientSession() as session:
                resp = await session.post(f"{base}/v1/traces", json=payload)
                assert resp.status == 200

            await asyncio.sleep(0.3)
            engine._request_shutdown()

        task = asyncio.create_task(engine.run())
        driver = asyncio.create_task(send_known())
        await asyncio.gather(task, driver)

        output = alert_buf.getvalue().strip()
        if output:
            alerts = [json.loads(line) for line in output.splitlines()]
            novel = [a for a in alerts if a["finding_rule_id"] == "mon-novel-interaction"]
            assert len(novel) == 0, f"unexpected novel alerts: {novel}"

    async def test_graceful_shutdown_flushes_remaining(self, partial_baseline: Path) -> None:
        alert_buf = io.StringIO()
        config = MonitorConfig(
            baseline_path=partial_baseline,
            host="127.0.0.1",
            port=0,
            window_seconds=10.0,
        )
        engine = MonitorEngine(config, alert_stream=alert_buf)

        async def send_then_shutdown():
            await asyncio.sleep(0.05)
            runner = engine._runner
            assert runner is not None
            site = list(runner.sites)[0]
            port = site._server.sockets[0].getsockname()[1]
            base = f"http://127.0.0.1:{port}"

            payload = _build_otlp_payload("a", "b", "POST /novel-op")
            async with aiohttp.ClientSession() as session:
                await session.post(f"{base}/v1/traces", json=payload)

            await asyncio.sleep(0.05)
            engine._request_shutdown()

        task = asyncio.create_task(engine.run())
        driver = asyncio.create_task(send_then_shutdown())
        await asyncio.gather(task, driver)

        output = alert_buf.getvalue().strip()
        assert output, "shutdown should have flushed pending spans"
        alerts = [json.loads(line) for line in output.splitlines()]
        assert any(a["finding_rule_id"] == "mon-novel-interaction" for a in alerts)
