# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Configurable OTLP trace factory for deterministic monitor tests.

Generates valid OTLP JSON payloads from topology specs.  Output is directly
parseable by ``_parse_resource_spans()`` and produces predictable fingerprints
via ``extract_fingerprints()``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

Protocol = Literal["http", "grpc", "db", "messaging", "rpc", "internal"]

_SPAN_KIND_INTERNAL = 1
_SPAN_KIND_SERVER = 2
_SPAN_KIND_CLIENT = 3
_SPAN_KIND_PRODUCER = 4


@dataclass(frozen=True)
class ServiceEdge:
    """A directed interaction between two services."""

    caller: str
    callee: str
    operation: str
    protocol: Protocol = "http"


@dataclass
class TopologySpec:
    """Declares services and their edges for trace generation."""

    services: list[str] = field(default_factory=list)
    edges: list[ServiceEdge] = field(default_factory=list)

    def __post_init__(self) -> None:
        for edge in self.edges:
            if not edge.caller or not edge.callee:
                raise ValueError(f"Edge has empty service name: {edge}")
            if edge.caller == edge.callee:
                raise ValueError(f"Self-referencing edge not allowed: {edge}")
        all_names = set(self.services)
        for edge in self.edges:
            all_names.add(edge.caller)
            all_names.add(edge.callee)
        self.services = sorted(all_names)


def _protocol_attributes(edge: ServiceEdge) -> list[dict[str, Any]]:
    """Return OTLP-format attributes appropriate for the protocol."""
    attrs: list[dict[str, Any]] = []
    if edge.protocol == "http":
        attrs.append({"key": "http.method", "value": {"stringValue": "GET"}})
        attrs.append({"key": "peer.service", "value": {"stringValue": edge.callee}})
    elif edge.protocol == "grpc":
        attrs.append({"key": "rpc.system", "value": {"stringValue": "grpc"}})
        attrs.append({"key": "rpc.service", "value": {"stringValue": edge.callee}})
        attrs.append({"key": "peer.service", "value": {"stringValue": edge.callee}})
    elif edge.protocol == "db":
        attrs.append({"key": "db.system", "value": {"stringValue": "postgresql"}})
        attrs.append({"key": "db.name", "value": {"stringValue": edge.callee}})
    elif edge.protocol == "messaging":
        attrs.append({"key": "messaging.system", "value": {"stringValue": "kafka"}})
        attrs.append(
            {"key": "messaging.destination.name", "value": {"stringValue": edge.callee}}
        )
    elif edge.protocol == "rpc":
        attrs.append({"key": "rpc.system", "value": {"stringValue": "thrift"}})
        attrs.append({"key": "peer.service", "value": {"stringValue": edge.callee}})
    elif edge.protocol == "internal":
        attrs.append({"key": "peer.service", "value": {"stringValue": edge.callee}})
    return attrs


def _make_span_id() -> str:
    return uuid.uuid4().hex[:16]


def _make_trace_id() -> str:
    return uuid.uuid4().hex


class TraceFactory:
    """Generate OTLP JSON payloads from topology specs."""

    def __init__(self, seed: int | None = None) -> None:
        self._counter = 0
        if seed is not None:
            import random

            self._rng = random.Random(seed)
        else:
            self._rng = None

    def _next_span_id(self) -> str:
        self._counter += 1
        if self._rng:
            return f"{self._rng.getrandbits(64):016x}"
        return _make_span_id()

    def _next_trace_id(self) -> str:
        if self._rng:
            return f"{self._rng.getrandbits(128):032x}"
        return _make_trace_id()

    def generate(
        self,
        topology: TopologySpec,
        *,
        traces_per_edge: int = 1,
        base_time_ns: int = 1_000_000_000_000,
        duration_ns: int = 50_000_000,
    ) -> dict[str, Any]:
        """Generate an OTLP JSON document from a topology spec.

        Returns a dict with ``resourceSpans`` suitable for
        ``_parse_resource_spans()``.  Each edge produces a pair of spans:
        a CLIENT span on the caller side and a SERVER span on the callee side
        (linked via parentSpanId), replicating real cross-service trace
        propagation.

        For ``db`` and ``messaging`` protocols, the callee service won't appear
        as a separate resourceSpan (databases/brokers aren't instrumented), so
        only the caller's CLIENT/PRODUCER span is emitted.
        """
        service_spans: dict[str, list[dict[str, Any]]] = {svc: [] for svc in topology.services}
        time_cursor = base_time_ns

        for edge in topology.edges:
            for _ in range(traces_per_edge):
                trace_id = self._next_trace_id()
                caller_span_id = self._next_span_id()
                callee_span_id = self._next_span_id()
                start = time_cursor
                end = start + duration_ns
                time_cursor = end + 1_000_000

                caller_kind = (
                    _SPAN_KIND_PRODUCER if edge.protocol == "messaging" else _SPAN_KIND_CLIENT
                )

                caller_span: dict[str, Any] = {
                    "traceId": trace_id,
                    "spanId": caller_span_id,
                    "parentSpanId": "",
                    "name": edge.operation,
                    "kind": caller_kind,
                    "startTimeUnixNano": start,
                    "endTimeUnixNano": end,
                    "status": {"code": 0},
                    "attributes": _protocol_attributes(edge),
                }
                service_spans[edge.caller].append(caller_span)

                if edge.protocol not in ("db", "messaging"):
                    callee_span: dict[str, Any] = {
                        "traceId": trace_id,
                        "spanId": callee_span_id,
                        "parentSpanId": caller_span_id,
                        "name": edge.operation,
                        "kind": _SPAN_KIND_SERVER,
                        "startTimeUnixNano": start + 1_000_000,
                        "endTimeUnixNano": end - 1_000_000,
                        "status": {"code": 0},
                        "attributes": [],
                    }
                    service_spans[edge.callee].append(callee_span)

        resource_spans: list[dict[str, Any]] = []
        for svc_name, spans in service_spans.items():
            if not spans:
                continue
            resource_spans.append(
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": svc_name}}
                        ]
                    },
                    "scopeSpans": [{"spans": spans}],
                }
            )

        return {"resourceSpans": resource_spans}

    def generate_ndjson(
        self,
        topology: TopologySpec,
        *,
        traces_per_edge: int = 1,
    ) -> str:
        """Generate NDJSON output (one JSON doc per line)."""
        import json

        doc = self.generate(topology, traces_per_edge=traces_per_edge)
        return json.dumps(doc, separators=(",", ":"))


__all__ = ["Protocol", "ServiceEdge", "TopologySpec", "TraceFactory"]
