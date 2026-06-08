"""Tests for the service topology graph builder."""

from __future__ import annotations

from nfr_review.collectors.payloads.otel_trace import OtelTracePayload, OtelTraceSpan
from nfr_review.models import Evidence
from nfr_review.output.topology import (
    TopologyGraph,
    build_topology_graph,
    render_topology_dot,
    render_topology_mermaid,
)


def _span(
    *,
    trace_id: str = "t1",
    span_id: str,
    parent_span_id: str = "",
    service_name: str,
    kind: int = 2,
    name: str = "op",
) -> OtelTraceSpan:
    return OtelTraceSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=name,
        service_name=service_name,
        kind=kind,
        start_time_unix_nano=0,
        end_time_unix_nano=100_000_000,
        status_code=1,
        code_namespace="",
        code_function="",
        attributes={},
    )


def _trace_evidence(spans: list[OtelTraceSpan]) -> Evidence:
    svc_names = sorted({s.service_name for s in spans if s.service_name})
    trace_ids = sorted({s.trace_id for s in spans if s.trace_id})
    return Evidence(
        collector_name="otel-trace",
        collector_version="0.1.0",
        locator="traces.json",
        kind="otel-trace",
        payload=OtelTracePayload(
            spans=spans,
            trace_ids=trace_ids,
            service_names=svc_names,
            source_file="traces.json",
        ),
    )


class TestBuildTopologyGraph:
    def test_empty_evidence(self) -> None:
        graph = build_topology_graph([])
        assert graph.services == set()
        assert graph.edges == {}

    def test_single_service_no_edges(self) -> None:
        spans = [
            _span(span_id="s1", service_name="svc-a"),
            _span(span_id="s2", parent_span_id="s1", service_name="svc-a"),
        ]
        graph = build_topology_graph([_trace_evidence(spans)])
        assert graph.services == {"svc-a"}
        assert graph.edges == {}

    def test_cross_service_edge(self) -> None:
        spans = [
            _span(span_id="s1", service_name="api-gateway", kind=2),
            _span(span_id="s2", parent_span_id="s1", service_name="api-gateway", kind=3),
            _span(span_id="s3", parent_span_id="s2", service_name="order-service", kind=2),
        ]
        graph = build_topology_graph([_trace_evidence(spans)])
        assert "api-gateway" in graph.services
        assert "order-service" in graph.services
        assert ("api-gateway", "order-service") in graph.edges

    def test_multiple_services_chain(self) -> None:
        spans = [
            _span(span_id="s1", service_name="gateway"),
            _span(span_id="s2", parent_span_id="s1", service_name="gateway", kind=3),
            _span(span_id="s3", parent_span_id="s2", service_name="orders", kind=2),
            _span(span_id="s4", parent_span_id="s3", service_name="orders", kind=3),
            _span(span_id="s5", parent_span_id="s4", service_name="payments", kind=2),
        ]
        graph = build_topology_graph([_trace_evidence(spans)])
        assert graph.services == {"gateway", "orders", "payments"}
        assert ("gateway", "orders") in graph.edges
        assert ("orders", "payments") in graph.edges
        assert len(graph.edges) == 2

    def test_edge_count_increments(self) -> None:
        spans = [
            _span(trace_id="t1", span_id="s1", service_name="a"),
            _span(trace_id="t1", span_id="s2", parent_span_id="s1", service_name="b"),
            _span(trace_id="t2", span_id="s3", service_name="a"),
            _span(trace_id="t2", span_id="s4", parent_span_id="s3", service_name="b"),
        ]
        graph = build_topology_graph([_trace_evidence(spans)])
        assert graph.edges[("a", "b")] == 2

    def test_cross_trace_spans_not_linked(self) -> None:
        spans = [
            _span(trace_id="t1", span_id="s1", service_name="a"),
            _span(trace_id="t2", span_id="s2", parent_span_id="s1", service_name="b"),
        ]
        graph = build_topology_graph([_trace_evidence(spans)])
        assert graph.edges == {}

    def test_edge_list_sorted(self) -> None:
        graph = TopologyGraph()
        graph.add_edge("b", "c")
        graph.add_edge("a", "b")
        edges = graph.edge_list()
        assert edges[0].caller == "a"
        assert edges[1].caller == "b"


class TestRenderMermaid:
    def test_empty_graph(self) -> None:
        graph = TopologyGraph()
        result = render_topology_mermaid(graph)
        assert "graph TD" in result
        assert "No services observed" in result

    def test_with_edges(self) -> None:
        graph = TopologyGraph()
        graph.add_edge("api-gateway", "order-service")
        result = render_topology_mermaid(graph)
        assert "graph TD" in result
        assert "api_gateway" in result
        assert "order_service" in result
        assert "-->|1|" in result


class TestRenderDot:
    def test_empty_graph(self) -> None:
        graph = TopologyGraph()
        result = render_topology_dot(graph)
        assert "digraph" in result
        assert "rankdir=LR" in result

    def test_with_edges(self) -> None:
        graph = TopologyGraph()
        graph.add_edge("svc-a", "svc-b")
        result = render_topology_dot(graph)
        assert "svc_a" in result
        assert "svc_b" in result
        assert "svc_a -> svc_b" in result
