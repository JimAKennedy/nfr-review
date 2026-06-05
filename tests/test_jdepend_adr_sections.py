"""Tests for build_jdepend_section, build_adr_section, and build_derived_adrs_section."""

from __future__ import annotations

from nfr_review.collectors.payloads.adr import AdrDocumentPayload, AdrSummaryPayload
from nfr_review.models import BasePayload, Evidence
from nfr_review.output.jdepend_section import (
    build_adr_section,
    build_derived_adrs_section,
    build_jdepend_section,
)


def _ev(kind: str, payload: dict | BasePayload, locator: str = ".") -> Evidence:
    return Evidence(
        collector_name="test",
        collector_version="0.1.0",
        locator=locator,
        kind=kind,
        payload=payload,
    )


class TestBuildAdrSection:
    def test_empty_evidence_returns_empty(self) -> None:
        assert build_adr_section([]) == ""

    def test_no_adr_documents_returns_empty(self) -> None:
        evidence = [_ev("jdepend-packages", {"packages": []})]
        assert build_adr_section(evidence) == ""

    def test_renders_adr_table(self) -> None:
        evidence = [
            _ev(
                "adr-document",
                AdrDocumentPayload(
                    file_path="docs/adr/0001-use-spring.md",
                    title="Use Spring Boot",
                    status="accepted",
                    superseded_by=None,
                ),
                locator="docs/adr/0001-use-spring.md",
            ),
            _ev(
                "adr-document",
                AdrDocumentPayload(
                    file_path="docs/adr/0002-use-postgres.md",
                    title="Use PostgreSQL",
                    status="proposed",
                    superseded_by="3",
                ),
                locator="docs/adr/0002-use-postgres.md",
            ),
            _ev(
                "adr-summary",
                AdrSummaryPayload(
                    total_adrs=2,
                    statuses={"accepted": 1, "proposed": 1},
                    has_lifecycle_tracking=True,
                ),
                locator="adr-summary",
            ),
        ]
        result = build_adr_section(evidence)
        assert "## Architecture Decision Records" in result
        assert "**2 ADRs**" in result
        assert "Use Spring Boot" in result
        assert "Use PostgreSQL" in result
        assert "accepted" in result
        assert "proposed" in result
        assert "3" in result

    def test_renders_without_summary_evidence(self) -> None:
        evidence = [
            _ev(
                "adr-document",
                AdrDocumentPayload(file_path="adr/0001.md", title="First ADR", status=None),
                locator="adr/0001.md",
            ),
        ]
        result = build_adr_section(evidence)
        assert "## Architecture Decision Records" in result
        assert "First ADR" in result


class TestBuildDerivedAdrsSection:
    def test_empty_evidence_returns_empty(self) -> None:
        assert build_derived_adrs_section([]) == ""

    def test_renders_derived_adrs(self) -> None:
        evidence = [
            _ev(
                "adr-derived",
                {
                    "title": "Use Redis for Caching",
                    "category": "infrastructure",
                    "confidence": 0.85,
                    "rationale": "Redis is used for session caching.",
                    "evidence_refs": ["docker-compose.yml"],
                },
            ),
        ]
        result = build_derived_adrs_section(evidence)
        assert "## Derived Architecture Decision Records" in result
        assert "Use Redis for Caching" in result
        assert "infrastructure" in result
        assert "85%" in result
        assert "docker-compose.yml" in result


class TestBuildJdependSection:
    def test_empty_evidence_returns_empty(self) -> None:
        assert build_jdepend_section([]) == ""

    def test_renders_jdepend_packages(self) -> None:
        evidence = [
            _ev(
                "jdepend-packages",
                {
                    "bytecode_dir": "target/classes",
                    "packages": [
                        {
                            "name": "com.example",
                            "ca": 1,
                            "ce": 2,
                            "a": 0.5,
                            "i": 0.67,
                            "d": 0.17,
                            "total_classes": 5,
                        }
                    ],
                },
            ),
        ]
        result = build_jdepend_section(evidence)
        assert "## JDepend Structural Analysis" in result
        assert "com.example" in result
