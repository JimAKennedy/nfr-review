# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the instrumented test application (S03).

Proves the 3-service app produces real OTel SDK traces that round-trip
through the monitor pipeline (parse -> fingerprint -> baseline).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiohttp
import pytest
import pytest_asyncio

from nfr_review.collectors.otel_trace import _parse_otlp_file, _parse_resource_spans
from nfr_review.monitor.fingerprint import extract_fingerprints
from tests.testapp.app import InstrumentedApp

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def test_app() -> AsyncIterator[InstrumentedApp]:
    app = InstrumentedApp()
    await app.start()
    yield app
    await app.stop()


class TestAppLifecycle:
    async def test_services_start_on_ephemeral_ports(self, test_app: InstrumentedApp) -> None:
        assert "gateway" in test_app.ports
        assert "orders" in test_app.ports
        assert "inventory" in test_app.ports
        for port in test_app.ports.values():
            assert port > 0

    async def test_gateway_responds(self, test_app: InstrumentedApp) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{test_app.gateway_url}/orders") as resp:
                assert resp.status == 200
                body = await resp.json()
                assert "gateway" in body


class TestTraceProduction:
    async def test_request_produces_spans(self, test_app: InstrumentedApp) -> None:
        async with aiohttp.ClientSession() as session:
            await session.get(f"{test_app.gateway_url}/orders")
        spans = test_app.get_spans()
        assert len(spans) >= 5

    async def test_spans_have_correct_service_names(self, test_app: InstrumentedApp) -> None:
        async with aiohttp.ClientSession() as session:
            await session.get(f"{test_app.gateway_url}/orders")
        spans = test_app.get_spans()
        service_names = {str(s.resource.attributes.get("service.name", "")) for s in spans}
        assert service_names == {"gateway", "orders", "inventory"}

    async def test_spans_have_parent_child_across_services(
        self, test_app: InstrumentedApp
    ) -> None:
        async with aiohttp.ClientSession() as session:
            await session.get(f"{test_app.gateway_url}/orders")
        spans = test_app.get_spans()
        parent_ids = {
            format(s.parent.span_id, "016x") for s in spans if s.parent and s.parent.span_id
        }
        span_ids = {format(s.context.span_id, "016x") for s in spans}
        assert parent_ids & span_ids, "cross-service parent-child links"


class TestOtlpRoundTrip:
    async def test_otlp_doc_parseable(self, test_app: InstrumentedApp) -> None:
        async with aiohttp.ClientSession() as session:
            await session.get(f"{test_app.gateway_url}/orders")
        doc = test_app.get_otlp_doc()
        parsed = _parse_resource_spans(doc)
        assert len(parsed) >= 5

    async def test_fingerprints_from_real_traces(self, test_app: InstrumentedApp) -> None:
        async with aiohttp.ClientSession() as session:
            await session.get(f"{test_app.gateway_url}/orders")
        doc = test_app.get_otlp_doc()
        parsed = _parse_resource_spans(doc)
        fps = extract_fingerprints(parsed)
        assert len(fps) >= 3
        protocols = {fp.protocol for fp in fps}
        assert "http" in protocols

    async def test_fingerprints_cover_all_edges(self, test_app: InstrumentedApp) -> None:
        async with aiohttp.ClientSession() as session:
            await session.get(f"{test_app.gateway_url}/orders")
        doc = test_app.get_otlp_doc()
        parsed = _parse_resource_spans(doc)
        fps = extract_fingerprints(parsed)
        caller_callee_pairs = {(fp.caller_service, fp.callee_service) for fp in fps}
        assert ("gateway", "orders") in caller_callee_pairs
        assert ("orders", "inventory") in caller_callee_pairs


class TestNdjsonExport:
    async def test_ndjson_round_trips(self, test_app: InstrumentedApp, tmp_path: Path) -> None:
        async with aiohttp.ClientSession() as session:
            await session.get(f"{test_app.gateway_url}/orders")
        ndjson_path = tmp_path / "traces.ndjson"
        count = test_app.export_ndjson(ndjson_path)
        assert count >= 5

        text = ndjson_path.read_text(encoding="utf-8")
        parsed = _parse_otlp_file(text)
        assert len(parsed) == count

        fps = extract_fingerprints(parsed)
        assert len(fps) >= 3

    async def test_clear_spans_resets(self, test_app: InstrumentedApp) -> None:
        async with aiohttp.ClientSession() as session:
            await session.get(f"{test_app.gateway_url}/orders")
        assert len(test_app.get_spans()) > 0
        test_app.clear_spans()
        assert len(test_app.get_spans()) == 0
