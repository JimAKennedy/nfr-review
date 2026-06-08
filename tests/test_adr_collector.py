"""Tests for the AdrCollector — markdown parsing, frontmatter extraction,
status heading detection, summary evidence, and fault isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.adr import AdrCollector
from nfr_review.collectors.payloads.adr import AdrDocumentPayload, AdrSummaryPayload

FIXTURES = Path(__file__).parent / "fixtures" / "adr-sample-repo"


@pytest.fixture
def collector() -> AdrCollector:
    return AdrCollector()


class TestFileDiscovery:
    def test_finds_adrs_in_docs_adr_dir(self, collector: AdrCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        doc_evidence = [e for e in results if e.kind == "adr-document"]
        assert len(doc_evidence) == 4

    def test_empty_dir_returns_no_evidence(
        self, collector: AdrCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "docs" / "adr").mkdir(parents=True)
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_discovers_alternative_adr_locations(
        self, collector: AdrCollector, tmp_path: Path
    ) -> None:
        for dirname in ("doc/adr", "decisions"):
            d = tmp_path / dirname
            d.mkdir(parents=True)
            (d / "0001-test.md").write_text("# Test\n\n## Status\n\nAccepted\n")
        results = collector.collect(tmp_path, config=None)
        doc_evidence = [e for e in results if e.kind == "adr-document"]
        assert len(doc_evidence) == 2


class TestFrontmatterParsing:
    def test_extracts_status_from_frontmatter(self, collector: AdrCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        adr_0001 = next(e for e in results if e.kind == "adr-document" and "0001" in e.locator)
        assert isinstance(adr_0001.payload, AdrDocumentPayload)
        assert adr_0001.payload.status == "accepted"
        assert adr_0001.payload.has_frontmatter is True

    def test_extracts_date_from_frontmatter(self, collector: AdrCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        adr_0001 = next(e for e in results if e.kind == "adr-document" and "0001" in e.locator)
        assert isinstance(adr_0001.payload, AdrDocumentPayload)
        assert adr_0001.payload.date == "2024-01-15"

    def test_extracts_superseded_by_from_frontmatter(self, collector: AdrCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        adr_0003 = next(e for e in results if e.kind == "adr-document" and "0003" in e.locator)
        assert isinstance(adr_0003.payload, AdrDocumentPayload)
        assert adr_0003.payload.superseded_by == "0002"
        assert adr_0003.payload.status == "superseded"


class TestHeadingStatusExtraction:
    def test_extracts_status_from_heading_section(self, collector: AdrCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        adr_0002 = next(e for e in results if e.kind == "adr-document" and "0002" in e.locator)
        assert isinstance(adr_0002.payload, AdrDocumentPayload)
        assert adr_0002.payload.status == "accepted"
        assert adr_0002.payload.has_frontmatter is False

    def test_no_status_when_missing(self, collector: AdrCollector, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-no-status.md").write_text("# No Status ADR\n\nJust a description.\n")
        results = collector.collect(tmp_path, config=None)
        doc = next(e for e in results if e.kind == "adr-document")
        assert isinstance(doc.payload, AdrDocumentPayload)
        assert doc.payload.status is None


class TestTitleExtraction:
    def test_extracts_title_from_heading(self, collector: AdrCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        adr_0001 = next(e for e in results if e.kind == "adr-document" and "0001" in e.locator)
        assert isinstance(adr_0001.payload, AdrDocumentPayload)
        assert adr_0001.payload.title == "Use Spring Boot"

    def test_title_from_non_frontmatter_file(self, collector: AdrCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        adr_0002 = next(e for e in results if e.kind == "adr-document" and "0002" in e.locator)
        assert isinstance(adr_0002.payload, AdrDocumentPayload)
        assert adr_0002.payload.title == "Use PostgreSQL for persistence"


class TestSummaryEvidence:
    def test_emits_summary_with_counts(self, collector: AdrCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        summary = next(e for e in results if e.kind == "adr-summary")
        assert isinstance(summary.payload, AdrSummaryPayload)
        assert summary.payload.total_adrs == 4
        assert summary.payload.has_lifecycle_tracking is True
        assert "accepted" in summary.payload.statuses
        assert "superseded" in summary.payload.statuses

    def test_no_summary_for_empty_repo(self, collector: AdrCollector, tmp_path: Path) -> None:
        results = collector.collect(tmp_path, config=None)
        assert not any(e.kind == "adr-summary" for e in results)


class TestFaultIsolation:
    def test_malformed_markdown_skipped_gracefully(
        self, collector: AdrCollector, tmp_path: Path
    ) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-good.md").write_text("# Good ADR\n\n## Status\n\nAccepted\n")
        # Binary/garbage content
        (adr_dir / "0002-bad.md").write_bytes(b"\x00\x01\x02\x03" * 100)
        results = collector.collect(tmp_path, config=None)
        doc_evidence = [e for e in results if e.kind == "adr-document"]
        assert len(doc_evidence) >= 1
