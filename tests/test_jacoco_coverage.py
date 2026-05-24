# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the JaCoCo report collector and jacoco-coverage-actual rule."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.jacoco_report import JaCoCoReportCollector
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.jacoco_coverage import JaCoCoCoverageActualRule

GOOD_FIXTURES = Path(__file__).parent / "fixtures" / "jacoco-sample-repo"
BAD_FIXTURES = Path(__file__).parent / "fixtures" / "jacoco-bad-repo"


# ---------------------------------------------------------------------------
# Collector tests
# ---------------------------------------------------------------------------


@pytest.fixture
def collector() -> JaCoCoReportCollector:
    return JaCoCoReportCollector()


class TestJaCoCoCollectorGoodRepo:
    def test_returns_evidence(self, collector: JaCoCoReportCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        assert len(results) == 1
        assert results[0].kind == "jacoco-report"

    def test_evidence_has_correct_fields(self, collector: JaCoCoReportCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        ev = results[0]
        assert ev.collector_name == "jacoco-report"
        assert ev.collector_version == "0.1.0"

    def test_overall_coverage(self, collector: JaCoCoReportCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        overall = results[0].payload["overall"]
        # LINE: covered=23, missed=1 -> 95.83%
        assert overall["line_covered"] == 23
        assert overall["line_missed"] == 1
        assert overall["line_pct"] == pytest.approx(95.83, abs=0.01)
        # BRANCH: covered=7, missed=1 -> 87.5%
        assert overall["branch_covered"] == 7
        assert overall["branch_missed"] == 1
        assert overall["branch_pct"] == pytest.approx(87.5, abs=0.01)

    def test_package_coverage(self, collector: JaCoCoReportCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        packages = results[0].payload["packages"]
        assert len(packages) == 1
        assert packages[0]["name"] == "com/example/service"
        assert packages[0]["line_pct"] == pytest.approx(95.83, abs=0.01)

    def test_report_name(self, collector: JaCoCoReportCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        assert results[0].payload["report_name"] == "example-service"

    def test_empty_dir_returns_nothing(
        self, collector: JaCoCoReportCollector, tmp_path: Path
    ) -> None:
        results = collector.collect(tmp_path, config=None)
        assert results == []


class TestJaCoCoCollectorBadRepo:
    def test_returns_evidence(self, collector: JaCoCoReportCollector) -> None:
        results = collector.collect(BAD_FIXTURES, config=None)
        assert len(results) == 1

    def test_low_coverage(self, collector: JaCoCoReportCollector) -> None:
        results = collector.collect(BAD_FIXTURES, config=None)
        overall = results[0].payload["overall"]
        # LINE: covered=11, missed=78 -> 12.36%
        assert overall["line_covered"] == 11
        assert overall["line_missed"] == 78
        assert overall["line_pct"] == pytest.approx(12.36, abs=0.01)
        # BRANCH: covered=3, missed=26 -> 10.34%
        assert overall["branch_pct"] == pytest.approx(10.34, abs=0.01)

    def test_report_name(self, collector: JaCoCoReportCollector) -> None:
        results = collector.collect(BAD_FIXTURES, config=None)
        assert results[0].payload["report_name"] == "legacy-service"


# ---------------------------------------------------------------------------
# Rule tests
# ---------------------------------------------------------------------------


def _jacoco_evidence(
    line_pct: float = 80.0,
    branch_pct: float = 70.0,
    report_name: str = "test-service",
) -> Evidence:
    return Evidence(
        collector_name="jacoco-report",
        collector_version="0.1.0",
        locator="target/site/jacoco/jacoco.xml",
        kind="jacoco-report",
        payload={
            "report_path": "target/site/jacoco/jacoco.xml",
            "report_name": report_name,
            "overall": {
                "line_covered": int(line_pct),
                "line_missed": int(100 - line_pct),
                "line_pct": line_pct,
                "branch_covered": int(branch_pct),
                "branch_missed": int(100 - branch_pct),
                "branch_pct": branch_pct,
                "instruction_covered": 80,
                "instruction_missed": 20,
                "instruction_pct": 80.0,
            },
            "packages": [
                {
                    "name": "com/example/service",
                    "line_pct": line_pct,
                    "branch_pct": branch_pct,
                    "instruction_pct": 80.0,
                }
            ],
        },
    )


class TestJaCoCoCoverageRule:
    def setup_method(self) -> None:
        self.rule = JaCoCoCoverageActualRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no jacoco-report evidence available"

    def test_good_coverage_green(self) -> None:
        ev = _jacoco_evidence(line_pct=85.0, branch_pct=75.0)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        line_findings = [f for f in result.findings if f.pattern_tag == "jacoco-coverage"]
        assert len(line_findings) == 1
        assert line_findings[0].rag == "green"
        assert line_findings[0].severity == "info"
        assert "85.0%" in line_findings[0].summary

    def test_low_coverage_red(self) -> None:
        ev = _jacoco_evidence(line_pct=30.0, branch_pct=20.0)
        result = self.rule.evaluate([ev], None)
        line_findings = [f for f in result.findings if f.pattern_tag == "jacoco-coverage"]
        assert len(line_findings) == 1
        assert line_findings[0].rag == "red"
        assert line_findings[0].severity == "high"
        assert "30.0%" in line_findings[0].summary
        assert "below 50%" in line_findings[0].summary

    def test_medium_coverage_amber(self) -> None:
        ev = _jacoco_evidence(line_pct=60.0, branch_pct=55.0)
        result = self.rule.evaluate([ev], None)
        line_findings = [f for f in result.findings if f.pattern_tag == "jacoco-coverage"]
        assert len(line_findings) == 1
        assert line_findings[0].rag == "amber"
        assert line_findings[0].severity == "medium"
        assert "60.0%" in line_findings[0].summary
        assert "below 70%" in line_findings[0].summary

    def test_low_branch_coverage_amber(self) -> None:
        ev = _jacoco_evidence(line_pct=80.0, branch_pct=30.0)
        result = self.rule.evaluate([ev], None)
        branch_findings = [
            f for f in result.findings if f.pattern_tag == "jacoco-branch-coverage"
        ]
        assert len(branch_findings) == 1
        assert branch_findings[0].rag == "amber"
        assert branch_findings[0].severity == "medium"
        assert "30.0%" in branch_findings[0].summary

    def test_good_branch_coverage_no_branch_finding(self) -> None:
        ev = _jacoco_evidence(line_pct=80.0, branch_pct=60.0)
        result = self.rule.evaluate([ev], None)
        branch_findings = [
            f for f in result.findings if f.pattern_tag == "jacoco-branch-coverage"
        ]
        assert len(branch_findings) == 0

    def test_both_line_and_branch_low(self) -> None:
        ev = _jacoco_evidence(line_pct=40.0, branch_pct=30.0)
        result = self.rule.evaluate([ev], None)
        line_findings = [f for f in result.findings if f.pattern_tag == "jacoco-coverage"]
        branch_findings = [
            f for f in result.findings if f.pattern_tag == "jacoco-branch-coverage"
        ]
        assert len(line_findings) == 1
        assert line_findings[0].rag == "red"
        assert len(branch_findings) == 1
        assert branch_findings[0].rag == "amber"

    def test_exactly_70_line_coverage_green(self) -> None:
        ev = _jacoco_evidence(line_pct=70.0, branch_pct=55.0)
        result = self.rule.evaluate([ev], None)
        line_findings = [f for f in result.findings if f.pattern_tag == "jacoco-coverage"]
        assert line_findings[0].rag == "green"

    def test_exactly_50_line_coverage_amber(self) -> None:
        ev = _jacoco_evidence(line_pct=50.0, branch_pct=55.0)
        result = self.rule.evaluate([ev], None)
        line_findings = [f for f in result.findings if f.pattern_tag == "jacoco-coverage"]
        assert line_findings[0].rag == "amber"

    def test_ignores_non_jacoco_evidence(self) -> None:
        ev = Evidence(
            collector_name="other",
            collector_version="0.1.0",
            locator="other.xml",
            kind="other-report",
            payload={},
        )
        result = self.rule.evaluate([ev], None)
        assert result.skipped is True


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_rule_protocol_compliance() -> None:
    rule = JaCoCoCoverageActualRule()
    assert hasattr(rule, "id")
    assert hasattr(rule, "band")
    assert hasattr(rule, "required_collectors")
    assert rule.id == "jacoco-coverage-actual"
    assert rule.band == 2
    assert rule.required_collectors == ["jacoco-report"]
    result = rule.evaluate([], None)
    assert isinstance(result, RuleResult)
    assert result.skipped is True


def test_finding_has_all_r007_fields() -> None:
    """Verify that when the rule fires, findings have all 10 R007 fields."""
    ev = _jacoco_evidence(line_pct=80.0, branch_pct=60.0)
    rule = JaCoCoCoverageActualRule()
    result = rule.evaluate([ev], None)
    assert not result.skipped
    for finding in result.findings:
        assert finding.rule_id
        assert finding.rag in ("red", "amber", "green")
        assert finding.severity
        assert finding.summary
        assert finding.recommendation
        assert finding.evidence_locator
        assert finding.collector_name == "jacoco-report"
        assert finding.collector_version == "0.1.0"
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.pattern_tag
