"""Tests for the ProtoCollector — regex parsing, payload structure, and edge cases."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.proto import ProtoCollector
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

FIXTURES = Path(__file__).parent / "fixtures" / "proto-sample-repo"


@pytest.fixture
def collector() -> ProtoCollector:
    return ProtoCollector()


def _payload_by_path(results: list[Evidence], substr: str) -> dict[str, Any]:
    return next(e.payload for e in results if substr in e.payload["file_path"])


class TestRegistration:
    def test_proto_registered_in_collector_registry(self) -> None:
        import nfr_review.collectors.proto

        importlib.reload(nfr_review.collectors.proto)
        assert "proto" in collector_registry


class TestFindsProtoFiles:
    def test_finds_all_fixture_protos(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert len(results) == 4
        locators = {e.locator for e in results}
        assert "good.proto" in locators
        assert "bad_gaps.proto" in locators
        assert "bad_service.proto" in locators
        assert "with_reserved.proto" in locators

    def test_skips_hidden_dirs(self, collector: ProtoCollector, tmp_path: Path) -> None:
        hidden = tmp_path / ".git" / "protos"
        hidden.mkdir(parents=True)
        (hidden / "secret.proto").write_text('syntax = "proto3";')
        visible = tmp_path / "api"
        visible.mkdir()
        (visible / "svc.proto").write_text('syntax = "proto3";')
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].locator == "api/svc.proto"

    def test_empty_repo_returns_empty(self, collector: ProtoCollector, tmp_path: Path) -> None:
        results = collector.collect(tmp_path, config=None)
        assert results == []


class TestEvidenceFields:
    def test_kind_and_collector_metadata(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert ev.kind == "proto-analysis"
            assert ev.collector_name == "proto"
            assert ev.collector_version == "0.1.0"

    def test_locator_is_relative_path(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert not ev.locator.startswith("/")


class TestGoodProto:
    def test_syntax_and_package(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "good.proto")
        assert payload["syntax"] == "proto3"
        assert payload["package"] == "example.v1"

    def test_imports(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "good.proto")
        assert "google/protobuf/timestamp.proto" in payload["imports"]

    def test_messages_parsed(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "good.proto")
        names = [m["name"] for m in payload["messages"]]
        assert "User" in names
        assert "Order" in names
        assert "OrderItem" in names

    def test_message_fields(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "good.proto")
        user = next(m for m in payload["messages"] if m["name"] == "User")
        field_names = [f["name"] for f in user["fields"]]
        assert "id" in field_names
        assert "name" in field_names
        assert "email" in field_names
        field_numbers = [f["number"] for f in user["fields"]]
        assert field_numbers == [1, 2, 3, 4]

    def test_message_has_comment(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "good.proto")
        user = next(m for m in payload["messages"] if m["name"] == "User")
        assert user["has_comment"] is True

    def test_repeated_field_label(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "good.proto")
        order = next(m for m in payload["messages"] if m["name"] == "Order")
        items_field = next(f for f in order["fields"] if f["name"] == "items")
        assert items_field["label"] == "repeated"

    def test_service_parsed(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "good.proto")
        assert len(payload["services"]) == 1
        svc = payload["services"][0]
        assert svc["name"] == "UserServiceV1"
        assert svc["has_comment"] is True

    def test_service_methods(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "good.proto")
        svc = payload["services"][0]
        method_names = [m["name"] for m in svc["methods"]]
        assert "CreateUser" in method_names
        assert "GetUser" in method_names
        for method in svc["methods"]:
            assert method["has_comment"] is True
            assert method["request_type"] == "User"
            assert method["response_type"] == "User"


class TestBadGaps:
    def test_field_number_gaps_detected(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "bad_gaps.proto")
        account = next(m for m in payload["messages"] if m["name"] == "Account")
        numbers = [f["number"] for f in account["fields"]]
        assert numbers == [1, 2, 5, 8]
        assert account["reserved_numbers"] == []

    def test_no_reserved_declarations(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "bad_gaps.proto")
        for msg in payload["messages"]:
            assert msg["reserved_numbers"] == []


class TestBadService:
    def test_unversioned_service_name(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "bad_service.proto")
        svc = payload["services"][0]
        assert svc["name"] == "OrderService"

    def test_uncommented_methods(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "bad_service.proto")
        svc = payload["services"][0]
        for method in svc["methods"]:
            assert method["has_comment"] is False

    def test_method_count(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "bad_service.proto")
        svc = payload["services"][0]
        assert len(svc["methods"]) == 3


class TestWithReserved:
    def test_reserved_numbers_parsed(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "with_reserved.proto")
        customer = next(m for m in payload["messages"] if m["name"] == "Customer")
        assert 3 in customer["reserved_numbers"]
        assert 4 in customer["reserved_numbers"]

    def test_reserved_range_parsed(self, collector: ProtoCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload_by_path(results, "with_reserved.proto")
        product = next(m for m in payload["messages"] if m["name"] == "Product")
        assert product["reserved_ranges"] == [{"start": 2, "end": 4}]
        assert 2 in product["reserved_numbers"]
        assert 3 in product["reserved_numbers"]
        assert 4 in product["reserved_numbers"]


class TestNegativeCases:
    def test_empty_proto_file(self, collector: ProtoCollector, tmp_path: Path) -> None:
        (tmp_path / "empty.proto").write_text("")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        payload = results[0].payload
        assert payload["syntax"] is None
        assert payload["messages"] == []
        assert payload["services"] == []

    def test_comments_only_proto(self, collector: ProtoCollector, tmp_path: Path) -> None:
        (tmp_path / "comments.proto").write_text(
            "// This file has only comments\n// No real content\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        payload = results[0].payload
        assert payload["syntax"] is None
        assert payload["messages"] == []

    def test_binary_content_handled(self, collector: ProtoCollector, tmp_path: Path) -> None:
        (tmp_path / "binary.proto").write_bytes(b"\x00\x01\x02\xff\xfe")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1

    def test_message_with_zero_fields(self, collector: ProtoCollector, tmp_path: Path) -> None:
        (tmp_path / "noop.proto").write_text('syntax = "proto3";\nmessage Empty {\n}\n')
        results = collector.collect(tmp_path, config=None)
        payload = results[0].payload
        msg = next(m for m in payload["messages"] if m["name"] == "Empty")
        assert msg["fields"] == []

    def test_service_with_zero_methods(
        self, collector: ProtoCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "emptysvc.proto").write_text('syntax = "proto3";\nservice EmptySvc {\n}\n')
        results = collector.collect(tmp_path, config=None)
        payload = results[0].payload
        svc = next(s for s in payload["services"] if s["name"] == "EmptySvc")
        assert svc["methods"] == []

    def test_collector_name_and_version(self, collector: ProtoCollector) -> None:
        assert collector.name == "proto"
        assert collector.version == "0.1.0"
