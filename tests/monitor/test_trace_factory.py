# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the OTLP trace factory — validates output format and fingerprint round-trip."""

from __future__ import annotations

import pytest

from nfr_review.collectors.otel_trace import _parse_resource_spans
from nfr_review.monitor.fingerprint import extract_fingerprints
from tests.monitor.trace_factory import (
    ServiceEdge,
    TopologySpec,
    TraceFactory,
)


class TestTopologySpec:
    def test_auto_collects_services_from_edges(self) -> None:
        spec = TopologySpec(edges=[ServiceEdge("svc-a", "svc-b", "GET /api", "http")])
        assert "svc-a" in spec.services
        assert "svc-b" in spec.services

    def test_rejects_self_referencing_edge(self) -> None:
        with pytest.raises(ValueError, match="Self-referencing"):
            TopologySpec(edges=[ServiceEdge("svc-a", "svc-a", "GET /self")])

    def test_rejects_empty_service_name(self) -> None:
        with pytest.raises(ValueError, match="empty service name"):
            TopologySpec(edges=[ServiceEdge("", "svc-b", "GET /api")])

    def test_deduplicates_service_names(self) -> None:
        spec = TopologySpec(
            services=["svc-a", "svc-b"],
            edges=[ServiceEdge("svc-a", "svc-b", "GET /api")],
        )
        assert spec.services == ["svc-a", "svc-b"]

    def test_explicit_services_merged_with_edge_services(self) -> None:
        spec = TopologySpec(
            services=["svc-c"],
            edges=[ServiceEdge("svc-a", "svc-b", "GET /api")],
        )
        assert set(spec.services) == {"svc-a", "svc-b", "svc-c"}


class TestTraceFactoryBasic:
    def test_generates_valid_otlp_json(self) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(edges=[ServiceEdge("gateway", "orders", "GET /orders", "http")])
        doc = factory.generate(spec)
        assert "resourceSpans" in doc
        spans = _parse_resource_spans(doc)
        assert len(spans) > 0

    def test_two_service_http_produces_two_spans(self) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(edges=[ServiceEdge("gateway", "orders", "GET /orders", "http")])
        doc = factory.generate(spec)
        spans = _parse_resource_spans(doc)
        assert len(spans) == 2
        caller_span = [s for s in spans if s.service_name == "gateway"][0]
        callee_span = [s for s in spans if s.service_name == "orders"][0]
        assert caller_span.kind == 3  # CLIENT
        assert callee_span.kind == 2  # SERVER
        assert callee_span.parent_span_id == caller_span.span_id

    def test_traces_per_edge_multiplies_spans(self) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(edges=[ServiceEdge("a", "b", "GET /x", "http")])
        doc = factory.generate(spec, traces_per_edge=3)
        spans = _parse_resource_spans(doc)
        assert len(spans) == 6  # 3 traces × 2 spans each

    def test_seeded_factory_is_deterministic(self) -> None:
        spec = TopologySpec(edges=[ServiceEdge("a", "b", "GET /x", "http")])
        doc1 = TraceFactory(seed=99).generate(spec)
        doc2 = TraceFactory(seed=99).generate(spec)
        spans1 = _parse_resource_spans(doc1)
        spans2 = _parse_resource_spans(doc2)
        assert [s.span_id for s in spans1] == [s.span_id for s in spans2]
        assert [s.trace_id for s in spans1] == [s.trace_id for s in spans2]


class TestTraceFactoryThreeServiceChain:
    def test_chain_topology_generates_correct_spans(self) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(
            edges=[
                ServiceEdge("gateway", "orders", "GET /orders", "http"),
                ServiceEdge("orders", "inventory", "GET /stock", "http"),
            ]
        )
        doc = factory.generate(spec)
        spans = _parse_resource_spans(doc)
        assert len(spans) == 4  # 2 edges × 2 spans

        services = {s.service_name for s in spans}
        assert services == {"gateway", "orders", "inventory"}

    def test_chain_fingerprints_correct(self) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(
            edges=[
                ServiceEdge("gateway", "orders", "GET /orders", "http"),
                ServiceEdge("orders", "inventory", "GET /stock", "http"),
            ]
        )
        doc = factory.generate(spec)
        spans = _parse_resource_spans(doc)
        fps = extract_fingerprints(spans)
        # Each HTTP edge produces 2 fingerprints: cross-service (SERVER) + leaf (CLIENT)
        assert len(fps) == 4
        callers = {fp.caller_service for fp in fps}
        assert callers == {"gateway", "orders"}


class TestProtocolTypes:
    @pytest.mark.parametrize(
        "protocol,expected_fp_protocol,expected_fp_count",
        [
            ("http", "http", 2),
            ("grpc", "grpc", 2),
            ("db", "db", 1),
            ("messaging", "messaging", 1),
            ("rpc", "rpc", 2),
            ("internal", "unknown", 2),
        ],
    )
    def test_protocol_sets_correct_attributes(
        self, protocol: str, expected_fp_protocol: str, expected_fp_count: int
    ) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(
            edges=[ServiceEdge("caller", "callee", f"op-{protocol}", protocol)]  # type: ignore[arg-type]
        )
        doc = factory.generate(spec)
        spans = _parse_resource_spans(doc)
        assert len(spans) > 0

        fps = extract_fingerprints(spans)
        # Cross-service protocols produce 2 fps (cross-service SERVER + leaf CLIENT);
        # db/messaging produce 1 (leaf only, no SERVER span)
        assert len(fps) == expected_fp_count
        protocols = {fp.protocol for fp in fps}
        assert expected_fp_protocol in protocols

    def test_db_protocol_produces_single_client_span(self) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(edges=[ServiceEdge("orders", "orders_db", "SELECT orders", "db")])
        doc = factory.generate(spec)
        spans = _parse_resource_spans(doc)
        assert len(spans) == 1
        assert spans[0].kind == 3  # CLIENT
        assert spans[0].service_name == "orders"
        assert "db.system" in spans[0].attributes

    def test_messaging_protocol_produces_single_producer_span(self) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(
            edges=[ServiceEdge("orders", "order-events", "publish order.created", "messaging")]
        )
        doc = factory.generate(spec)
        spans = _parse_resource_spans(doc)
        assert len(spans) == 1
        assert spans[0].kind == 4  # PRODUCER
        assert "messaging.system" in spans[0].attributes

    def test_grpc_protocol_attributes(self) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(
            edges=[ServiceEdge("frontend", "backend", "grpc.health.v1.Health/Check", "grpc")]
        )
        doc = factory.generate(spec)
        spans = _parse_resource_spans(doc)
        caller = [s for s in spans if s.service_name == "frontend"][0]
        assert caller.attributes["rpc.system"] == "grpc"


class TestFingerprintRoundTrip:
    def test_mixed_topology_fingerprints_match(self) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(
            edges=[
                ServiceEdge("gateway", "orders", "GET /orders", "http"),
                ServiceEdge("orders", "inventory", "gRPC GetStock", "grpc"),
                ServiceEdge("orders", "orders_db", "SELECT", "db"),
                ServiceEdge("orders", "events", "publish", "messaging"),
            ]
        )
        doc = factory.generate(spec)
        spans = _parse_resource_spans(doc)
        fps = extract_fingerprints(spans)
        # http:2 + grpc:2 + db:1 + messaging:1 = 6
        assert len(fps) == 6

        protocols = {fp.protocol for fp in fps}
        assert {"http", "grpc", "db", "messaging"} <= protocols

    def test_duplicate_edges_produce_same_fingerprints(self) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(edges=[ServiceEdge("a", "b", "GET /x", "http")])
        doc = factory.generate(spec, traces_per_edge=5)
        spans = _parse_resource_spans(doc)
        fps = extract_fingerprints(spans)
        # HTTP edge: 2 fps (cross-service + leaf), deduped across 5 traces
        assert len(fps) == 2

    def test_different_operations_produce_different_fingerprints(self) -> None:
        factory = TraceFactory(seed=42)
        spec = TopologySpec(
            edges=[
                ServiceEdge("a", "b", "GET /users", "http"),
                ServiceEdge("a", "b", "POST /users", "http"),
            ]
        )
        doc = factory.generate(spec)
        spans = _parse_resource_spans(doc)
        fps = extract_fingerprints(spans)
        # 2 HTTP edges × 2 fps each = 4
        assert len(fps) == 4


class TestNdjsonOutput:
    def test_ndjson_is_valid_json(self) -> None:
        import json

        factory = TraceFactory(seed=42)
        spec = TopologySpec(edges=[ServiceEdge("a", "b", "GET /x", "http")])
        ndjson = factory.generate_ndjson(spec)
        doc = json.loads(ndjson)
        assert "resourceSpans" in doc

    def test_ndjson_round_trips_through_parser(self) -> None:
        from nfr_review.collectors.otel_trace import _parse_otlp_file

        factory = TraceFactory(seed=42)
        spec = TopologySpec(
            edges=[
                ServiceEdge("gateway", "orders", "GET /orders", "http"),
                ServiceEdge("orders", "db", "SELECT", "db"),
            ]
        )
        ndjson = factory.generate_ndjson(spec)
        spans = _parse_otlp_file(ndjson)
        assert len(spans) > 0
        fps = extract_fingerprints(spans)
        # http:2 + db:1 = 3
        assert len(fps) == 3
