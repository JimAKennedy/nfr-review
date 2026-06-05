# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for typed payload infrastructure and ADR payload models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nfr_review.collectors.payloads.adr import AdrDocumentPayload, AdrSummaryPayload
from nfr_review.models import BasePayload, Evidence


class TestBasePayload:
    def test_empty_base_payload(self) -> None:
        p = BasePayload()
        assert p.model_dump() == {}

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            BasePayload(bogus="nope")  # type: ignore[call-arg]


class TestEvidencePayloadUnion:
    def test_accepts_dict_payload(self) -> None:
        e = Evidence(
            collector_name="test",
            collector_version="0.1",
            locator="x",
            kind="test",
            payload={"key": "val"},
        )
        assert isinstance(e.payload, dict)
        assert e.payload["key"] == "val"

    def test_accepts_typed_payload(self) -> None:
        p = AdrDocumentPayload(file_path="docs/adr/0001.md", title="Test")
        e = Evidence(
            collector_name="adr",
            collector_version="0.1",
            locator="x",
            kind="adr-document",
            payload=p,
        )
        assert isinstance(e.payload, AdrDocumentPayload)
        assert e.payload.file_path == "docs/adr/0001.md"
        assert e.payload.title == "Test"

    def test_default_payload_is_empty_dict(self) -> None:
        e = Evidence(
            collector_name="test",
            collector_version="0.1",
            locator="x",
            kind="test",
        )
        assert e.payload == {}
        assert isinstance(e.payload, dict)

    def test_dict_payload_roundtrip(self) -> None:
        e = Evidence(
            collector_name="test",
            collector_version="0.1",
            locator="x",
            kind="test",
            payload={"count": 42},
        )
        dumped = e.model_dump()
        assert dumped["payload"] == {"count": 42}
        restored = Evidence(**dumped)
        assert restored == e

    def test_typed_payload_serializes_to_dict(self) -> None:
        p = AdrDocumentPayload(
            file_path="docs/adr/0001.md",
            title="Use Spring Boot",
            status="accepted",
            has_frontmatter=True,
        )
        e = Evidence(
            collector_name="adr",
            collector_version="0.1",
            locator="x",
            kind="adr-document",
            payload=p,
        )
        dumped = e.model_dump()
        assert dumped["payload"] == {
            "file_path": "docs/adr/0001.md",
            "title": "Use Spring Boot",
            "status": "accepted",
            "date": None,
            "superseded_by": None,
            "has_frontmatter": True,
        }


class TestAdrDocumentPayload:
    def test_minimal_construction(self) -> None:
        p = AdrDocumentPayload(file_path="docs/adr/0001.md")
        assert p.file_path == "docs/adr/0001.md"
        assert p.title is None
        assert p.status is None
        assert p.date is None
        assert p.superseded_by is None
        assert p.has_frontmatter is False

    def test_full_construction(self) -> None:
        p = AdrDocumentPayload(
            file_path="docs/adr/0001.md",
            title="Use Spring Boot",
            status="accepted",
            date="2024-01-15",
            superseded_by="0002",
            has_frontmatter=True,
        )
        assert p.title == "Use Spring Boot"
        assert p.status == "accepted"
        assert p.date == "2024-01-15"
        assert p.superseded_by == "0002"
        assert p.has_frontmatter is True

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            AdrDocumentPayload(file_path="x", bogus="nope")  # type: ignore[call-arg]

    def test_requires_file_path(self) -> None:
        with pytest.raises(ValidationError):
            AdrDocumentPayload()  # type: ignore[call-arg]

    def test_json_schema(self) -> None:
        schema = AdrDocumentPayload.model_json_schema()
        assert "file_path" in schema["properties"]
        assert schema["properties"]["file_path"]["type"] == "string"
        assert "file_path" in schema["required"]


class TestAdrSummaryPayload:
    def test_construction(self) -> None:
        p = AdrSummaryPayload(
            total_adrs=3,
            statuses={"accepted": 2, "superseded": 1},
            has_lifecycle_tracking=True,
        )
        assert p.total_adrs == 3
        assert p.statuses == {"accepted": 2, "superseded": 1}
        assert p.has_lifecycle_tracking is True

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            AdrSummaryPayload(  # type: ignore[call-arg]
                total_adrs=1,
                statuses={},
                has_lifecycle_tracking=False,
                bogus="nope",
            )

    def test_requires_all_fields(self) -> None:
        with pytest.raises(ValidationError):
            AdrSummaryPayload(total_adrs=1)  # type: ignore[call-arg]
