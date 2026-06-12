# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""End-to-end scenario tests for the monitor pipeline (M051 S04).

Proves the full UAT → baseline → monitor → alert lifecycle for every
drift detection pattern: new service, new endpoint, protocol change,
volume-only, and zero false positives.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import aiohttp
import pytest
import pytest_asyncio

otel = pytest.importorskip("opentelemetry", reason="opentelemetry not installed")

from nfr_review.collectors.otel_trace import _parse_resource_spans  # noqa: E402
from nfr_review.monitor.baseline import InteractionBaseline  # noqa: E402
from nfr_review.monitor.fingerprint import extract_fingerprints  # noqa: E402
from tests.monitor.harness import MonitorHarness  # noqa: E402
from tests.monitor.trace_factory import ServiceEdge, TopologySpec, TraceFactory  # noqa: E402
from tests.testapp.app import InstrumentedApp  # noqa: E402

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Scenario: new service appears
# ---------------------------------------------------------------------------
class TestNewServiceDetection:
    async def test_new_service_triggers_novel_alert(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        """Baseline has gateway→orders; inject gateway→payments → novel alert."""
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

    async def test_new_service_severity_is_high_for_http(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        baseline = baseline_from_topology(simple_topology)
        novel_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "analytics", "POST /events", "http")]
        )
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(novel_topo))
            await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            http_alerts = [a for a in alerts if "analytics" in a["finding_summary"]]
            assert len(http_alerts) >= 1
            # CLIENT-side fingerprint gets severity "high" for HTTP
            assert any(a["finding_severity"] == "high" for a in http_alerts)


# ---------------------------------------------------------------------------
# Scenario: new endpoint on existing service
# ---------------------------------------------------------------------------
class TestNewEndpointDetection:
    async def test_new_operation_triggers_novel_alert(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
    ) -> None:
        """Baseline has GET /orders; inject POST /orders → novel alert."""
        baseline_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "orders", "GET /orders", "http")]
        )
        baseline = baseline_from_topology(baseline_topo)
        novel_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "orders", "POST /orders", "http")]
        )
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(novel_topo))
            await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            summaries = " ".join(a["finding_summary"] for a in alerts)
            assert "POST /orders" in summaries


# ---------------------------------------------------------------------------
# Scenario: protocol change on existing edge
# ---------------------------------------------------------------------------
class TestProtocolChangeDetection:
    async def test_protocol_change_triggers_novel_alert(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
    ) -> None:
        """Baseline has HTTP gateway→orders; inject gRPC → novel alert."""
        baseline_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "orders", "GetOrders", "http")]
        )
        baseline = baseline_from_topology(baseline_topo)
        novel_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "orders", "GetOrders", "grpc")]
        )
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(novel_topo))
            await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            assert len(alerts) >= 1
            summaries = " ".join(a["finding_summary"] for a in alerts)
            assert "grpc" in summaries.lower()

    async def test_grpc_severity_is_high(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
    ) -> None:
        baseline_topo = TopologySpec(edges=[ServiceEdge("api", "backend", "Query", "http")])
        baseline = baseline_from_topology(baseline_topo)
        novel_topo = TopologySpec(edges=[ServiceEdge("api", "backend", "Query", "grpc")])
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(novel_topo))
            await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            assert all(a["finding_severity"] == "high" for a in alerts)


# ---------------------------------------------------------------------------
# Scenario: volume-only increase (same topology) → zero alerts
# ---------------------------------------------------------------------------
class TestVolumeOnlyNoAlert:
    async def test_same_topology_more_volume_no_alerts(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        """Same interactions with more traces → zero novel alerts."""
        baseline = baseline_from_topology(simple_topology)
        async with MonitorHarness(baseline, tmp_path) as h:
            payload = trace_factory.generate(simple_topology, traces_per_edge=10)
            await h.send_traces(payload)
            await h.wait_for_flush()
            assert h.get_novel_alerts() == []


# ---------------------------------------------------------------------------
# Scenario: zero false positives (known traffic only)
# ---------------------------------------------------------------------------
class TestZeroFalsePositives:
    async def test_known_multi_service_traffic_no_alerts(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
        multi_service_topology: TopologySpec,
    ) -> None:
        """3-service chain with all known interactions → zero alerts."""
        baseline = baseline_from_topology(multi_service_topology)
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(multi_service_topology))
            await h.wait_for_flush()
            assert h.get_novel_alerts() == []

    async def test_known_microservices_mesh_no_alerts(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
        microservices_topology: TopologySpec,
    ) -> None:
        """5-service mesh with HTTP, gRPC, DB, messaging → zero alerts."""
        baseline = baseline_from_topology(microservices_topology)
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(microservices_topology))
            await h.wait_for_flush()
            assert h.get_novel_alerts() == []


# ---------------------------------------------------------------------------
# Scenario: mixed known + novel in single payload
# ---------------------------------------------------------------------------
class TestMixedTraffic:
    async def test_only_novel_interactions_alert(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
    ) -> None:
        """Payload has both known and novel edges; only novel ones alert."""
        baseline_topo = TopologySpec(
            edges=[
                ServiceEdge("gateway", "orders", "GET /orders", "http"),
                ServiceEdge("orders", "inventory", "GetStock", "grpc"),
            ]
        )
        baseline = baseline_from_topology(baseline_topo)
        mixed_topo = TopologySpec(
            edges=[
                ServiceEdge("gateway", "orders", "GET /orders", "http"),
                ServiceEdge("orders", "inventory", "GetStock", "grpc"),
                ServiceEdge("gateway", "notifications", "POST /notify", "http"),
            ]
        )
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(mixed_topo))
            await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            summaries = " ".join(a["finding_summary"] for a in alerts)
            assert "notifications" in summaries
            assert "orders" not in summaries or "inventory" not in summaries


# ---------------------------------------------------------------------------
# Scenario: severity varies by protocol type
# ---------------------------------------------------------------------------
class TestSeverityByProtocol:
    @pytest.mark.parametrize(
        "protocol,expected_severity",
        [
            ("http", "high"),
            ("grpc", "high"),
            ("db", "medium"),
            ("messaging", "medium"),
            ("rpc", "high"),
            ("internal", "low"),
        ],
    )
    async def test_severity_matches_protocol(
        self,
        tmp_path: Path,
        trace_factory: TraceFactory,
        protocol: str,
        expected_severity: str,
    ) -> None:
        baseline = InteractionBaseline(
            source="empty", trace_count=0, span_count=0, fingerprints=[]
        )
        topo = TopologySpec(
            edges=[ServiceEdge("svc-a", "svc-b", "op", protocol)]  # type: ignore[arg-type]
        )
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(topo))
            await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            matching = [a for a in alerts if "svc-b" in a["finding_summary"]]
            assert len(matching) >= 1, f"expected alert for {protocol}"
            # CLIENT span carries protocol attrs; SERVER span is "unknown".
            # Verify at least one alert has the expected severity.
            severities = {a["finding_severity"] for a in matching}
            assert expected_severity in severities


# ---------------------------------------------------------------------------
# Scenario: real test app E2E (InstrumentedApp → baseline → detection)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def test_app() -> AsyncIterator[InstrumentedApp]:
    app = InstrumentedApp()
    await app.start()
    yield app
    await app.stop()


class TestRealAppE2E:
    async def test_baseline_from_app_traces_detects_novel_factory_traffic(
        self,
        test_app: InstrumentedApp,
        tmp_path: Path,
        trace_factory: TraceFactory,
    ) -> None:
        """Full lifecycle: real app traces → baseline → factory novel → alert."""
        async with aiohttp.ClientSession() as session:
            await session.get(f"{test_app.gateway_url}/orders")

        doc = test_app.get_otlp_doc()
        parsed = _parse_resource_spans(doc)
        fps = list(extract_fingerprints(parsed))
        baseline = InteractionBaseline(
            source="test-app",
            trace_count=1,
            span_count=len(parsed),
            fingerprints=fps,
        )
        assert len(fps) >= 3

        novel_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "shipping", "POST /ship", "http")]
        )
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(novel_topo))
            await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            assert len(alerts) >= 1
            assert any("shipping" in a["finding_summary"] for a in alerts)

    async def test_app_known_traffic_no_false_positives(
        self,
        test_app: InstrumentedApp,
        tmp_path: Path,
        trace_factory: TraceFactory,
    ) -> None:
        """Baseline from app; replayed app traffic → zero alerts."""
        async with aiohttp.ClientSession() as session:
            await session.get(f"{test_app.gateway_url}/orders")

        doc = test_app.get_otlp_doc()
        parsed = _parse_resource_spans(doc)
        fps = list(extract_fingerprints(parsed))
        baseline = InteractionBaseline(
            source="test-app",
            trace_count=1,
            span_count=len(parsed),
            fingerprints=fps,
        )

        async with MonitorHarness(baseline, tmp_path) as h:
            test_app.clear_spans()
            async with aiohttp.ClientSession() as session:
                await session.get(f"{test_app.gateway_url}/orders")
            replay_doc = test_app.get_otlp_doc()
            await h.send_traces(replay_doc)
            await h.wait_for_flush()
            assert h.get_novel_alerts() == []


# ---------------------------------------------------------------------------
# Scenario: multi-window consistency
# ---------------------------------------------------------------------------
class TestMultiWindowConsistency:
    async def test_novel_detected_across_separate_windows(
        self,
        tmp_path: Path,
        baseline_from_topology: Callable[[TopologySpec], InteractionBaseline],
        trace_factory: TraceFactory,
        simple_topology: TopologySpec,
    ) -> None:
        """Window 1: known traffic, Window 2: novel traffic → alert in W2."""
        baseline = baseline_from_topology(simple_topology)
        novel_topo = TopologySpec(
            edges=[ServiceEdge("gateway", "cache", "GET /cached", "http")]
        )
        async with MonitorHarness(baseline, tmp_path) as h:
            await h.send_traces(trace_factory.generate(simple_topology))
            await h.wait_for_flush()
            assert h.get_novel_alerts() == []

            await h.send_traces(trace_factory.generate(novel_topo))
            await h.wait_for_flush()
            alerts = h.get_novel_alerts()
            assert len(alerts) >= 1
            assert any("cache" in a["finding_summary"] for a in alerts)
