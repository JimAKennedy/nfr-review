# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for MonitorHarness — proves the harness enables concise test authoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.monitor.baseline import InteractionBaseline
from nfr_review.monitor.fingerprint import InteractionFingerprint
from tests.monitor.harness import MonitorHarness
from tests.monitor.trace_factory import ServiceEdge, TopologySpec, TraceFactory

pytestmark = pytest.mark.asyncio


@pytest.fixture
def known_baseline() -> InteractionBaseline:
    """Baseline containing a single known HTTP interaction."""
    fp = InteractionFingerprint(
        caller_service="gateway",
        callee_service="orders",
        operation="GET /orders",
        span_kind=3,
        protocol="http",
    )
    return InteractionBaseline(source="test", trace_count=1, span_count=1, fingerprints=[fp])


class TestHarnessLifecycle:
    async def test_start_and_shutdown(
        self, known_baseline: InteractionBaseline, tmp_path: Path
    ) -> None:
        async with MonitorHarness(known_baseline, tmp_path) as h:
            assert h.port > 0
            assert h.base_url.startswith("http://127.0.0.1:")

    async def test_healthz_reachable(
        self, known_baseline: InteractionBaseline, tmp_path: Path
    ) -> None:
        import aiohttp

        async with MonitorHarness(known_baseline, tmp_path) as h:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{h.base_url}/healthz") as resp:
                    assert resp.status == 200


class TestHarnessKnownTraffic:
    async def test_known_traffic_no_alerts(
        self,
        tmp_path: Path,
        baseline_from_topology: ...,
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        baseline = baseline_from_topology(simple_topology)
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(simple_topology))
            await h.wait_for_flush()
            assert h.get_novel_alerts() == []


class TestHarnessNovelDetection:
    async def test_novel_traffic_produces_alert(
        self,
        tmp_path: Path,
        baseline_from_topology: ...,
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        baseline = baseline_from_topology(simple_topology)
        novel_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "payments", "POST /pay", "http")]
        )
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(novel_topo))
            await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            assert len(alerts) >= 1
            assert any("payments" in a["finding_summary"] for a in alerts)

    async def test_mixed_known_and_novel(
        self,
        tmp_path: Path,
        baseline_from_topology: ...,
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        baseline = baseline_from_topology(simple_topology)
        mixed_topo = TopologySpec(
            edges=[
                ServiceEdge("gateway", "orders", "GET /orders", "http"),
                ServiceEdge("gateway", "analytics", "POST /events", "http"),
            ]
        )
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(mixed_topo))
            await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            assert len(alerts) >= 1
            summaries = " ".join(a["finding_summary"] for a in alerts)
            assert "analytics" in summaries


class TestHarnessDedup:
    async def test_dedup_same_novel_across_windows(
        self,
        tmp_path: Path,
        baseline_from_topology: ...,
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        baseline = baseline_from_topology(simple_topology)
        novel_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "cache", "GET /cached", "http")]
        )
        payload = trace_factory.generate(novel_topo)
        async with MonitorHarness(baseline, tmp_path, deduplicate=True) as h:
            await h.send_traces(payload)
            await h.wait_for_flush()
            first_count = len(h.get_novel_alerts())
            assert first_count >= 1
            await h.send_traces(payload)
            await h.wait_for_flush()
            assert len(h.get_novel_alerts()) == first_count

    async def test_no_dedup_reports_every_window(
        self,
        tmp_path: Path,
        baseline_from_topology: ...,
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        baseline = baseline_from_topology(simple_topology)
        novel_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "cache", "GET /cached", "http")]
        )
        payload = trace_factory.generate(novel_topo)
        async with MonitorHarness(baseline, tmp_path, deduplicate=False) as h:
            await h.send_traces(payload)
            await h.wait_for_flush()
            first_count = len(h.get_novel_alerts())
            await h.send_traces(payload)
            await h.wait_for_flush()
            assert len(h.get_novel_alerts()) > first_count
