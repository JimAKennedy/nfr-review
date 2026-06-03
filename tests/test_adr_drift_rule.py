"""Tests for ArchitecturalDriftFromAdrRule — LLM-only Band 2 rule."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from nfr_review.llm_client import LlmUnavailableError
from nfr_review.models import Evidence
from nfr_review.protocols import LlmClient
from nfr_review.rules.adr_drift import ArchitecturalDriftFromAdrRule


def _make_adr_evidence(
    title: str = "ADR-001: Use Spring Boot",
    status: str = "accepted",
    file_path: str = "docs/adr/001-use-spring-boot.md",
) -> Evidence:
    return Evidence(
        collector_name="adr",
        collector_version="0.1.0",
        locator=file_path,
        kind="adr-document",
        payload={
            "file_path": file_path,
            "title": title,
            "status": status,
            "date": "2024-01-15",
            "superseded_by": None,
            "has_frontmatter": True,
        },
    )


def _make_java_evidence(
    file_path: str = "src/main/java/com/example/App.java",
    class_name: str = "App",
    annotations: list[str] | None = None,
    imports: list[str] | None = None,
) -> Evidence:
    return Evidence(
        collector_name="java-ast",
        collector_version="0.1.0",
        locator=file_path,
        kind="java-ast-file",
        payload={
            "file_path": file_path,
            "classes": [
                {
                    "name": class_name,
                    "annotations": annotations or ["SpringBootApplication"],
                    "methods": [],
                }
            ],
            "methods": [],
            "catch_blocks": [],
            "imports": imports or ["org.springframework.boot.SpringApplication"],
            "thread_pool_constructions": [],
            "log_statements": [],
        },
    )


def _unavailable_client() -> LlmClient:
    client = MagicMock(spec=LlmClient)
    client.available = False
    client.analyze.side_effect = LlmUnavailableError("no key")
    return client


def _mock_client(response: str) -> LlmClient:
    client = MagicMock(spec=LlmClient)
    client.available = True
    client.analyze.return_value = response
    return client


class TestNoAdrEvidence:
    def test_no_adr_evidence_skipped(self) -> None:
        java_ev = _make_java_evidence()
        rule = ArchitecturalDriftFromAdrRule(llm_client=_unavailable_client())
        result = rule.evaluate([java_ev], context=None)
        assert result.skipped is True
        assert "no ADR evidence" in (result.skip_reason or "")

    def test_empty_evidence_skipped(self) -> None:
        rule = ArchitecturalDriftFromAdrRule(llm_client=_unavailable_client())
        result = rule.evaluate([], context=None)
        assert result.skipped is True


class TestNoJavaEvidence:
    def test_no_java_evidence_skipped(self) -> None:
        adr_ev = _make_adr_evidence()
        rule = ArchitecturalDriftFromAdrRule(llm_client=_unavailable_client())
        result = rule.evaluate([adr_ev], context=None)
        assert result.skipped is True
        assert "no Java AST evidence" in (result.skip_reason or "")


class TestLlmUnavailable:
    def test_llm_unavailable_skipped(self) -> None:
        adr_ev = _make_adr_evidence()
        java_ev = _make_java_evidence()
        rule = ArchitecturalDriftFromAdrRule(llm_client=_unavailable_client())
        result = rule.evaluate([adr_ev, java_ev], context=None)
        assert result.skipped is True
        assert "LLM unavailable" in (result.skip_reason or "")
        assert "requires Claude API" in (result.skip_reason or "")


class TestDriftDetected:
    def test_drift_detected_amber(self) -> None:
        adr_ev = _make_adr_evidence(title="ADR-002: Use PostgreSQL")
        java_ev = _make_java_evidence(
            imports=["com.mongodb.client.MongoClient"],
        )
        response = json.dumps(
            {
                "drifts": [
                    {
                        "adr_title": "ADR-002: Use PostgreSQL",
                        "violation": "Code uses MongoDB instead of PostgreSQL",
                        "severity": "medium",
                    }
                ],
                "summary": "Database choice drifted from ADR.",
            }
        )
        rule = ArchitecturalDriftFromAdrRule(llm_client=_mock_client(response))
        result = rule.evaluate([adr_ev, java_ev], context=None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.confidence == 0.75
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "ADR-002" in f.summary
        assert f.pattern_tag == "adr-drift"

    def test_high_severity_drift_is_red(self) -> None:
        adr_ev = _make_adr_evidence(title="ADR-003: No direct DB access from controllers")
        java_ev = _make_java_evidence()
        response = json.dumps(
            {
                "drifts": [
                    {
                        "adr_title": "ADR-003: No direct DB access from controllers",
                        "violation": "Controller directly instantiates JDBC connection",
                        "severity": "high",
                    }
                ],
                "summary": "Layering violation found.",
            }
        )
        rule = ArchitecturalDriftFromAdrRule(llm_client=_mock_client(response))
        result = rule.evaluate([adr_ev, java_ev], context=None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "high"
        assert f.confidence == 0.75

    def test_multiple_drifts(self) -> None:
        adr_ev = _make_adr_evidence()
        java_ev = _make_java_evidence()
        response = json.dumps(
            {
                "drifts": [
                    {"adr_title": "ADR-1", "violation": "v1", "severity": "medium"},
                    {"adr_title": "ADR-2", "violation": "v2", "severity": "high"},
                ],
                "summary": "Multiple drifts.",
            }
        )
        rule = ArchitecturalDriftFromAdrRule(llm_client=_mock_client(response))
        result = rule.evaluate([adr_ev, java_ev], context=None)
        assert len(result.findings) == 2
        rags = [f.rag for f in result.findings]
        assert "amber" in rags
        assert "red" in rags


class TestNoDrift:
    def test_no_drift_green(self) -> None:
        adr_ev = _make_adr_evidence()
        java_ev = _make_java_evidence()
        response = json.dumps(
            {
                "drifts": [],
                "summary": "No architectural drift detected.",
            }
        )
        rule = ArchitecturalDriftFromAdrRule(llm_client=_mock_client(response))
        result = rule.evaluate([adr_ev, java_ev], context=None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "green"
        assert f.severity == "info"
        assert f.confidence == 0.75


class TestEvidenceBundleSize:
    def test_evidence_bundle_under_8kb(self) -> None:
        adr_items = [
            _make_adr_evidence(
                title=(
                    f"ADR-{i:03d}: Decision about component {i}"
                    " with a very long title that is padded"
                ),
                file_path=f"docs/adr/{i:03d}-decision.md",
            )
            for i in range(50)
        ]
        java_items = [
            _make_java_evidence(
                file_path=f"src/main/java/com/example/Service{i}.java",
                class_name=f"Service{i}",
                annotations=["Service", "Transactional"],
                imports=[
                    "org.springframework.stereotype.Service",
                    "org.springframework.transaction.annotation.Transactional",
                    f"com.example.repo.Repo{i}",
                ],
            )
            for i in range(50)
        ]
        rule = ArchitecturalDriftFromAdrRule(llm_client=_unavailable_client())
        bundle = rule._build_evidence_bundle(adr_items, java_items)
        assert len(bundle.encode()) <= 8192


class TestLlmErrors:
    def test_api_error_returns_skipped(self) -> None:
        adr_ev = _make_adr_evidence()
        java_ev = _make_java_evidence()
        llm = MagicMock(spec=LlmClient)
        llm.available = True
        llm.analyze.side_effect = RuntimeError("API timeout")
        rule = ArchitecturalDriftFromAdrRule(llm_client=llm)
        result = rule.evaluate([adr_ev, java_ev], context=None)
        assert result.skipped is True
        assert "error" in (result.skip_reason or "").lower()

    def test_malformed_response_returns_skipped(self) -> None:
        adr_ev = _make_adr_evidence()
        java_ev = _make_java_evidence()
        llm = _mock_client("Sorry, I cannot analyze that.")
        rule = ArchitecturalDriftFromAdrRule(llm_client=llm)
        result = rule.evaluate([adr_ev, java_ev], context=None)
        assert result.skipped is True
        assert "parse" in (result.skip_reason or "").lower()

    def test_llm_response_with_prose_wrapper(self) -> None:
        adr_ev = _make_adr_evidence()
        java_ev = _make_java_evidence()
        wrapped = (
            "Here is my analysis:\n\n"
            + json.dumps({"drifts": [], "summary": "All good."})
            + "\n\nHope that helps!"
        )
        rule = ArchitecturalDriftFromAdrRule(llm_client=_mock_client(wrapped))
        result = rule.evaluate([adr_ev, java_ev], context=None)
        assert not result.skipped
        assert result.findings[0].rag == "green"


class TestAdrsWithoutTitles:
    def test_adrs_without_titles_excluded_from_bundle(self) -> None:
        adr_with_title = _make_adr_evidence(title="ADR-001: Real Decision")
        adr_no_title = Evidence(
            collector_name="adr",
            collector_version="0.1.0",
            locator="docs/adr/draft.md",
            kind="adr-document",
            payload={
                "file_path": "docs/adr/draft.md",
                "title": None,
                "status": None,
                "date": None,
                "superseded_by": None,
                "has_frontmatter": False,
            },
        )
        java_ev = _make_java_evidence()
        rule = ArchitecturalDriftFromAdrRule(llm_client=_unavailable_client())
        bundle = rule._build_evidence_bundle([adr_with_title, adr_no_title], [java_ev])
        parsed = json.loads(bundle)
        adr_section = [s for s in parsed if s["section"] == "adrs"][0]
        assert len(adr_section["items"]) == 1
        assert adr_section["items"][0]["title"] == "ADR-001: Real Decision"
