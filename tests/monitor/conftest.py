# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures for monitor tests — trace factory, topologies, harness."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from nfr_review.collectors.otel_trace import _parse_resource_spans
from nfr_review.monitor.baseline import InteractionBaseline
from nfr_review.monitor.fingerprint import extract_fingerprints
from tests.monitor.trace_factory import ServiceEdge, TopologySpec, TraceFactory


@pytest.fixture(scope="session")
def trace_factory() -> TraceFactory:
    return TraceFactory(seed=42)


@pytest.fixture(scope="session")
def simple_topology() -> TopologySpec:
    """2-service HTTP topology: gateway -> orders."""
    return TopologySpec(edges=[ServiceEdge("gateway", "orders", "GET /orders", "http")])


@pytest.fixture(scope="session")
def multi_service_topology() -> TopologySpec:
    """3-service chain: gateway->orders (HTTP), orders->inventory (gRPC)."""
    return TopologySpec(
        edges=[
            ServiceEdge("gateway", "orders", "GET /orders", "http"),
            ServiceEdge("orders", "inventory", "gRPC GetStock", "grpc"),
        ]
    )


@pytest.fixture(scope="session")
def microservices_topology() -> TopologySpec:
    """5-service mesh with HTTP, gRPC, DB, and messaging edges."""
    return TopologySpec(
        edges=[
            ServiceEdge("api-gateway", "user-service", "GET /users", "http"),
            ServiceEdge("api-gateway", "order-service", "POST /orders", "http"),
            ServiceEdge("order-service", "inventory-service", "gRPC CheckStock", "grpc"),
            ServiceEdge("order-service", "orders-db", "INSERT orders", "db"),
            ServiceEdge("order-service", "order-events", "publish order.created", "messaging"),
        ]
    )


@pytest.fixture
def baseline_from_topology(
    trace_factory: TraceFactory,
) -> Callable[[TopologySpec], InteractionBaseline]:
    """Factory fixture: build an InteractionBaseline from a TopologySpec."""

    def _make(topology: TopologySpec) -> InteractionBaseline:
        doc = trace_factory.generate(topology)
        spans = _parse_resource_spans(doc)
        fps = list(extract_fingerprints(spans))
        return InteractionBaseline(
            source="test-factory",
            trace_count=1,
            span_count=len(spans),
            fingerprints=fps,
        )

    return _make
