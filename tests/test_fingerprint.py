# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for interaction fingerprint extraction."""

from __future__ import annotations

from nfr_review.collectors.payloads.otel_trace import OtelTraceSpan
from nfr_review.monitor.fingerprint import (
    InteractionFingerprint,
    _detect_protocol,
    _resolve_callee,
    extract_fingerprints,
)


def _span(
    trace_id: str = "t1",
    span_id: str = "s1",
    parent_span_id: str = "",
    name: str = "op",
    service_name: str = "svc-a",
    kind: int = 2,
    attributes: dict[str, str] | None = None,
) -> OtelTraceSpan:
    return OtelTraceSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=name,
        service_name=service_name,
        kind=kind,
        start_time_unix_nano=0,
        end_time_unix_nano=1_000_000,
        status_code=0,
        code_namespace="",
        code_function="",
        attributes=attributes or {},
    )


class TestDetectProtocol:
    def test_db(self) -> None:
        assert _detect_protocol({"db.system": "postgresql"}) == "db"

    def test_messaging(self) -> None:
        assert _detect_protocol({"messaging.system": "kafka"}) == "messaging"

    def test_grpc(self) -> None:
        assert _detect_protocol({"rpc.system": "grpc"}) == "grpc"

    def test_rpc_generic(self) -> None:
        assert _detect_protocol({"rpc.system": "apache_dubbo"}) == "rpc"

    def test_http_method(self) -> None:
        assert _detect_protocol({"http.method": "GET"}) == "http"

    def test_http_request_method(self) -> None:
        assert _detect_protocol({"http.request.method": "POST"}) == "http"

    def test_unknown(self) -> None:
        assert _detect_protocol({}) == "unknown"

    def test_db_takes_precedence_over_http(self) -> None:
        assert _detect_protocol({"db.system": "mysql", "http.method": "GET"}) == "db"


class TestResolveCallee:
    def test_peer_service(self) -> None:
        s = _span(attributes={"peer.service": "order-svc"})
        assert _resolve_callee(s) == "order-svc"

    def test_db_system_with_name(self) -> None:
        s = _span(attributes={"db.system": "postgresql", "db.name": "orders"})
        assert _resolve_callee(s) == "postgresql:orders"

    def test_db_system_without_name(self) -> None:
        s = _span(attributes={"db.system": "redis"})
        assert _resolve_callee(s) == "redis"

    def test_messaging_with_destination(self) -> None:
        s = _span(
            attributes={"messaging.system": "kafka", "messaging.destination.name": "events"}
        )
        assert _resolve_callee(s) == "kafka:events"

    def test_net_peer_name(self) -> None:
        s = _span(attributes={"net.peer.name": "db.internal"})
        assert _resolve_callee(s) == "db.internal"

    def test_server_address(self) -> None:
        s = _span(attributes={"server.address": "cache.internal"})
        assert _resolve_callee(s) == "cache.internal"

    def test_empty_when_no_attrs(self) -> None:
        s = _span(attributes={})
        assert _resolve_callee(s) == ""


class TestFingerprintHash:
    def test_deterministic(self) -> None:
        fp1 = InteractionFingerprint(
            caller_service="a",
            callee_service="b",
            operation="op",
            span_kind=3,
            protocol="http",
        )
        fp2 = InteractionFingerprint(
            caller_service="a",
            callee_service="b",
            operation="op",
            span_kind=3,
            protocol="http",
        )
        assert fp1.fingerprint_hash == fp2.fingerprint_hash
        assert len(fp1.fingerprint_hash) == 16

    def test_different_inputs_different_hash(self) -> None:
        fp1 = InteractionFingerprint(
            caller_service="a",
            callee_service="b",
            operation="GET",
            span_kind=3,
            protocol="http",
        )
        fp2 = InteractionFingerprint(
            caller_service="a",
            callee_service="b",
            operation="POST",
            span_kind=3,
            protocol="http",
        )
        assert fp1.fingerprint_hash != fp2.fingerprint_hash

    def test_frozen_model(self) -> None:
        fp = InteractionFingerprint(
            caller_service="a",
            callee_service="b",
            operation="op",
            span_kind=3,
            protocol="http",
        )
        assert fp.model_config.get("frozen") is True

    def test_equality(self) -> None:
        fp1 = InteractionFingerprint(
            caller_service="a",
            callee_service="b",
            operation="op",
            span_kind=3,
            protocol="http",
        )
        fp2 = InteractionFingerprint(
            caller_service="a",
            callee_service="b",
            operation="op",
            span_kind=3,
            protocol="http",
        )
        assert fp1 == fp2

    def test_set_dedup(self) -> None:
        fp1 = InteractionFingerprint(
            caller_service="a",
            callee_service="b",
            operation="op",
            span_kind=3,
            protocol="http",
        )
        fp2 = InteractionFingerprint(
            caller_service="a",
            callee_service="b",
            operation="op",
            span_kind=3,
            protocol="http",
        )
        assert len({fp1, fp2}) == 1


class TestExtractFingerprints:
    def test_cross_service_edge(self) -> None:
        parent = _span(
            span_id="p1",
            service_name="gateway",
            kind=3,
            name="HTTP GET",
            attributes={"http.method": "GET"},
        )
        child = _span(
            span_id="c1",
            parent_span_id="p1",
            service_name="orders",
            kind=2,
            name="GET /orders",
            attributes={"http.method": "GET"},
        )
        fps = extract_fingerprints([parent, child])
        assert len(fps) == 1
        fp = next(iter(fps))
        assert fp.caller_service == "gateway"
        assert fp.callee_service == "orders"
        assert fp.protocol == "http"

    def test_leaf_db_call(self) -> None:
        parent = _span(span_id="p1", service_name="orders", kind=1, name="findAll")
        child = _span(
            span_id="c1",
            parent_span_id="p1",
            service_name="orders",
            kind=3,
            name="SELECT orders",
            attributes={"db.system": "postgresql", "db.name": "mydb"},
        )
        fps = extract_fingerprints([parent, child])
        assert len(fps) == 1
        fp = next(iter(fps))
        assert fp.caller_service == "orders"
        assert fp.callee_service == "postgresql:mydb"
        assert fp.protocol == "db"

    def test_leaf_messaging_call(self) -> None:
        parent = _span(span_id="p1", service_name="orders", kind=1, name="process")
        child = _span(
            span_id="c1",
            parent_span_id="p1",
            service_name="orders",
            kind=4,
            name="publish",
            attributes={"messaging.system": "kafka", "messaging.destination.name": "events"},
        )
        fps = extract_fingerprints([parent, child])
        assert len(fps) == 1
        fp = next(iter(fps))
        assert fp.callee_service == "kafka:events"
        assert fp.protocol == "messaging"

    def test_empty_spans(self) -> None:
        assert len(extract_fingerprints([])) == 0

    def test_no_cross_service_no_leaf(self) -> None:
        parent = _span(span_id="p1", service_name="svc", kind=2, name="GET /")
        child = _span(
            span_id="c1", parent_span_id="p1", service_name="svc", kind=1, name="internal"
        )
        fps = extract_fingerprints([parent, child])
        assert len(fps) == 0

    def test_dedup_same_interaction_type(self) -> None:
        parent = _span(
            span_id="p1",
            service_name="gw",
            kind=3,
            name="HTTP GET",
            attributes={"http.method": "GET"},
        )
        child1 = _span(
            trace_id="t1",
            span_id="c1",
            parent_span_id="p1",
            service_name="orders",
            kind=2,
            name="GET /orders",
            attributes={"http.method": "GET"},
        )
        child2 = _span(
            trace_id="t2",
            span_id="c2",
            parent_span_id="p1",
            service_name="orders",
            kind=2,
            name="GET /orders",
            attributes={"http.method": "GET"},
        )
        fps = extract_fingerprints([parent, child1, child2])
        assert len(fps) == 1

    def test_multi_service_fixture(self) -> None:
        """Use the actual trace fixture structure from traces-multi-service.ndjson."""
        from pathlib import Path

        from nfr_review.collectors.otel_trace import _parse_otlp_file

        fixture = Path("tests/fixtures/otel-traces/traces-multi-service.ndjson")
        spans = _parse_otlp_file(fixture.read_text())
        fps = extract_fingerprints(spans)

        callee_set = {fp.callee_service for fp in fps}
        assert "greeting-service" in callee_set
        protocols = {fp.protocol for fp in fps}
        assert "http" in protocols
        assert "db" in protocols
        assert "messaging" in protocols
        assert len(fps) >= 5
