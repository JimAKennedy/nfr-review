# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for adr-gap rule — cross-referencing derived vs existing ADRs."""

from __future__ import annotations

from nfr_review.collectors.payloads.adr import AdrDocumentPayload
from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.adr_gap import AdrGapRule


def _derived(
    title: str,
    category: str = "framework",
    confidence: float = 0.8,
    rationale: str = "inferred from config",
) -> Evidence:
    return Evidence(
        collector_name="adr-derive",
        collector_version="0.1.0",
        locator=f"adr-derived:{title}",
        kind="adr-derived",
        payload={
            "title": title,
            "category": category,
            "confidence": confidence,
            "rationale": rationale,
            "evidence_refs": [],
        },
    )


def _existing(
    title: str,
    status: str = "accepted",
) -> Evidence:
    return Evidence(
        collector_name="adr",
        collector_version="0.1.0",
        locator=f"docs/adr/{title}.md",
        kind="adr-document",
        payload=AdrDocumentPayload(
            file_path=f"docs/adr/{title}.md",
            title=title,
            status=status,
            date=None,
            superseded_by=None,
            has_frontmatter=True,
        ),
    )


class TestRegistration:
    def test_registered(self) -> None:
        assert "adr-gap" in rule_registry

    def test_rule_id(self) -> None:
        assert AdrGapRule().id == "adr-gap"


class TestSkipBehavior:
    def test_skip_when_no_derived(self) -> None:
        rule = AdrGapRule()
        result = rule.evaluate([_existing("Use Spring Boot")], None)
        assert result.skipped is True

    def test_skip_when_no_evidence(self) -> None:
        rule = AdrGapRule()
        result = rule.evaluate([], None)
        assert result.skipped is True


class TestGapDetection:
    def test_undocumented_decision_flagged(self) -> None:
        evidence = [
            _derived("Use Spring Boot for REST API"),
            # No matching existing ADR
        ]
        rule = AdrGapRule()
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].pattern_tag == "adr-gap-undocumented"
        assert "Spring Boot" in result.findings[0].summary

    def test_documented_decision_green(self) -> None:
        evidence = [
            _derived("Use Spring Boot for REST API"),
            _existing("Use Spring Boot for REST API"),
        ]
        rule = AdrGapRule()
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert all(f.rag == "green" for f in result.findings)
        assert result.findings[0].pattern_tag == "adr-gap-ok"

    def test_fuzzy_match_works(self) -> None:
        evidence = [
            _derived("Use PostgreSQL for primary database storage"),
            _existing("Use PostgreSQL as primary database backend"),
        ]
        rule = AdrGapRule()
        result = rule.evaluate(evidence, None)
        assert all(f.rag == "green" for f in result.findings)

    def test_mixed_documented_and_undocumented(self) -> None:
        evidence = [
            _derived("Use Spring Boot for REST API"),
            _derived("Adopt Kubernetes for container orchestration"),
            _existing("Use Spring Boot for REST API"),
        ]
        rule = AdrGapRule()
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "Kubernetes" in amber[0].summary


class TestSupersededDetection:
    def test_superseded_but_active(self) -> None:
        evidence = [
            _derived("Use Spring Boot for REST API"),
            _existing("Use Spring Boot for REST API", status="superseded"),
        ]
        rule = AdrGapRule()
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert amber[0].pattern_tag == "adr-gap-superseded-active"


class TestConfidence:
    def test_confidence_propagated(self) -> None:
        evidence = [_derived("Use Redis for caching", confidence=0.6)]
        rule = AdrGapRule()
        result = rule.evaluate(evidence, None)
        assert result.findings[0].confidence == 0.6

    def test_superseded_confidence_discounted(self) -> None:
        evidence = [
            _derived("Use Spring Boot for REST API", confidence=1.0),
            _existing("Use Spring Boot for REST API", status="superseded"),
        ]
        rule = AdrGapRule()
        result = rule.evaluate(evidence, None)
        assert result.findings[0].confidence == 0.8
