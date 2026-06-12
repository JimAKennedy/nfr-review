# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Resilience and edge case tests for the monitor pipeline (M051 S05).

Covers malformed payloads, large baselines, E2E dedup correctness
through the full HTTP→engine→alert path, and shutdown flush behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from nfr_review.monitor.baseline import InteractionBaseline
from nfr_review.monitor.fingerprint import InteractionFingerprint
from tests.monitor.harness import MonitorHarness
from tests.monitor.trace_factory import ServiceEdge, TopologySpec, TraceFactory

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Malformed / edge-case payloads
# ---------------------------------------------------------------------------
class TestMalformedPayloads:
    async def test_invalid_json_returns_400(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        simple_topology: TopologySpec,
    ) -> None:
        baseline = baseline_from_topology(simple_topology)
        async with MonitorHarness(baseline, tmp_path) as h:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{h.base_url}/v1/traces",
                    data=b"not json at all",
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    assert resp.status == 400

    async def test_empty_resource_spans_accepted(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        simple_topology: TopologySpec,
    ) -> None:
        """Valid JSON with empty resourceSpans → 200, no alerts."""
        baseline = baseline_from_topology(simple_topology)
        async with MonitorHarness(baseline, tmp_path) as h:
            status = await h.send_traces({"resourceSpans": []})
            assert status == 200
            await h.wait_for_flush()
            assert h.get_novel_alerts() == []

    async def test_missing_spans_key_handled(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        simple_topology: TopologySpec,
    ) -> None:
        """Structurally valid JSON but missing scopeSpans.spans key."""
        baseline = baseline_from_topology(simple_topology)
        payload: dict[str, Any] = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "test"}}
                        ]
                    },
                    "scopeSpans": [{}],
                }
            ]
        }
        async with MonitorHarness(baseline, tmp_path) as h:
            status = await h.send_traces(payload)
            assert status == 200
            await h.wait_for_flush()
            assert h.get_novel_alerts() == []

    async def test_span_with_missing_fields_handled(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        simple_topology: TopologySpec,
    ) -> None:
        """Span with minimal fields (missing parentSpanId, attributes)."""
        baseline = baseline_from_topology(simple_topology)
        payload: dict[str, Any] = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "test"}}
                        ]
                    },
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "a" * 32,
                                    "spanId": "b" * 16,
                                    "name": "minimal-span",
                                    "kind": 1,
                                    "startTimeUnixNano": 1000000000,
                                    "endTimeUnixNano": 2000000000,
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        async with MonitorHarness(baseline, tmp_path) as h:
            status = await h.send_traces(payload)
            assert status == 200

    async def test_unknown_top_level_keys_accepted(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        simple_topology: TopologySpec,
    ) -> None:
        """OTLP payload with extra unknown keys → accepted (forward-compat)."""
        baseline = baseline_from_topology(simple_topology)
        payload: dict[str, Any] = {
            "resourceSpans": [],
            "extraField": "ignored",
        }
        async with MonitorHarness(baseline, tmp_path) as h:
            status = await h.send_traces(payload)
            assert status == 200


# ---------------------------------------------------------------------------
# Large baseline
# ---------------------------------------------------------------------------
class TestLargeBaseline:
    async def test_1000_fingerprint_baseline_works(
        self,
        tmp_path: Path,
        trace_factory: TraceFactory,
    ) -> None:
        """Baseline with 1000 fingerprints still detects novel traffic."""
        fps = [
            InteractionFingerprint(
                caller_service=f"svc-{i}",
                callee_service=f"svc-{i + 1}",
                operation=f"op-{i}",
                span_kind=3,
                protocol="http",
            )
            for i in range(1000)
        ]
        baseline = InteractionBaseline(
            source="large-test", trace_count=1000, span_count=2000, fingerprints=fps
        )
        novel_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "never-seen", "GET /new", "http")]
        )
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(novel_topo))
            await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            assert len(alerts) >= 1
            assert any("never-seen" in a["finding_summary"] for a in alerts)

    async def test_large_baseline_no_false_positives(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
    ) -> None:
        """Known traffic against a large baseline → zero alerts."""
        topo = TopologySpec(edges=[ServiceEdge("svc-0", "svc-1", "op-0", "http")])
        # Use baseline_from_topology to capture both CLIENT+SERVER fingerprints,
        # then pad with extra fingerprints to make it large.
        base = baseline_from_topology(topo)
        extra_fps = [
            InteractionFingerprint(
                caller_service=f"svc-{i}",
                callee_service=f"svc-{i + 1}",
                operation=f"op-{i}",
                span_kind=3,
                protocol="http",
            )
            for i in range(2, 500)
        ]
        baseline = InteractionBaseline(
            source="large-test",
            trace_count=500,
            span_count=1000,
            fingerprints=list(base.fingerprints) + extra_fps,
        )
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(topo))
            await h.wait_for_flush()
            assert h.get_novel_alerts() == []


# ---------------------------------------------------------------------------
# E2E dedup correctness through HTTP path
# ---------------------------------------------------------------------------
class TestDedupE2E:
    async def test_same_novel_across_three_windows_alerts_once(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        """Same novel fingerprints sent in 3 windows → alerts only in first window."""
        baseline = baseline_from_topology(simple_topology)
        novel_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "metrics", "POST /ingest", "http")]
        )
        payload = trace_factory.generate(novel_topo)
        async with MonitorHarness(baseline, tmp_path, deduplicate=True) as h:
            await h.send_traces(payload)
            await h.wait_for_flush()
            first_count = len(h.get_novel_alerts())
            assert first_count >= 1
            # Subsequent windows with same traffic → no new alerts
            await h.send_traces(payload)
            await h.wait_for_flush()
            assert len(h.get_novel_alerts()) == first_count
            await h.send_traces(payload)
            await h.wait_for_flush()
            assert len(h.get_novel_alerts()) == first_count

    async def test_different_novels_each_alert_once(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        """Two different novel edges → alerts for both, no duplicates."""
        baseline = baseline_from_topology(simple_topology)
        async with MonitorHarness(baseline, tmp_path, deduplicate=True) as h:
            topo_a = TopologySpec(edges=[ServiceEdge("gateway", "alpha", "GET /a", "http")])
            await h.send_traces(trace_factory.generate(topo_a))
            await h.wait_for_flush()
            count_after_a = len(h.get_novel_alerts())

            topo_b = TopologySpec(edges=[ServiceEdge("gateway", "beta", "GET /b", "http")])
            await h.send_traces(trace_factory.generate(topo_b))
            await h.wait_for_flush()

            alerts = h.get_novel_alerts()
            summaries = [a["finding_summary"] for a in alerts]
            assert any("alpha" in s for s in summaries)
            assert any("beta" in s for s in summaries)
            assert len(alerts) > count_after_a
            # Replaying alpha should NOT add more alerts
            await h.send_traces(trace_factory.generate(topo_a))
            await h.wait_for_flush()
            assert len(h.get_novel_alerts()) == len(alerts)

    async def test_dedup_disabled_alerts_every_window(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        """With dedup off, same novel in 3 windows → 3 alerts."""
        baseline = baseline_from_topology(simple_topology)
        novel_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "logging", "POST /log", "http")]
        )
        payload = trace_factory.generate(novel_topo)
        async with MonitorHarness(
            baseline, tmp_path, deduplicate=False, window_seconds=0.15
        ) as h:
            for _ in range(3):
                await h.send_traces(payload)
                await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            logging_alerts = [a for a in alerts if "logging" in a["finding_summary"]]
            assert len(logging_alerts) >= 3


# ---------------------------------------------------------------------------
# Shutdown flush
# ---------------------------------------------------------------------------
class TestShutdownFlush:
    async def test_shutdown_flushes_pending_spans(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        """Spans ingested just before shutdown are flushed and produce alerts."""
        baseline = baseline_from_topology(simple_topology)
        novel_topo = TopologySpec(edges=[ServiceEdge("gateway", "audit", "POST /log", "http")])
        h = MonitorHarness(baseline, tmp_path, window_seconds=60.0)
        await h.start()
        await h.send_traces(trace_factory.generate(novel_topo))
        await h.shutdown()
        alerts = h.get_novel_alerts()
        assert len(alerts) >= 1
        assert any("audit" in a["finding_summary"] for a in alerts)


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------
class TestStatsEndpoint:
    async def test_statsz_reflects_ingested_spans(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        baseline = baseline_from_topology(simple_topology)
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(simple_topology))
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{h.base_url}/statsz") as resp:
                    assert resp.status == 200
                    stats = await resp.json()
                    assert stats["total_spans_ingested"] > 0
