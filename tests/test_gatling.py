# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the Gatling collector and gatling-performance-thresholds rule."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.gatling import GatlingCollector
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.gatling_performance import GatlingPerformanceThresholdsRule

GOOD_FIXTURES = Path(__file__).parent / "fixtures" / "gatling-sample-repo"
BAD_FIXTURES = Path(__file__).parent / "fixtures" / "gatling-bad-repo"


# ---------------------------------------------------------------------------
# Collector tests
# ---------------------------------------------------------------------------


@pytest.fixture
def collector() -> GatlingCollector:
    return GatlingCollector()


class TestGatlingCollectorGoodRepo:
    def test_returns_evidence(self, collector: GatlingCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        result_evidence = [e for e in results if e.kind == "gatling-result"]
        summary_evidence = [e for e in results if e.kind == "gatling-summary"]
        assert len(result_evidence) == 1
        assert len(summary_evidence) == 1

    def test_result_evidence_has_correct_fields(self, collector: GatlingCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        result_ev = next(e for e in results if e.kind == "gatling-result")
        assert result_ev.collector_name == "gatling"
        assert result_ev.collector_version == "0.1.0"

        payload = result_ev.payload
        assert payload["total_requests"] == 1000
        assert payload["ok_requests"] == 995
        assert payload["ko_requests"] == 5
        assert payload["error_rate"] == 0.5
        assert payload["mean_response_time_ms"] == 150
        assert payload["p95_response_time_ms"] == 350
        assert payload["p99_response_time_ms"] == 800
        assert payload["requests_per_second"] == 50.0

    def test_summary_evidence(self, collector: GatlingCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        summary = next(e for e in results if e.kind == "gatling-summary")
        assert summary.payload["simulation_count"] == 1
        assert len(summary.payload["simulations"]) == 1

    def test_empty_dir_returns_nothing(
        self, collector: GatlingCollector, tmp_path: Path
    ) -> None:
        results = collector.collect(tmp_path, config=None)
        assert results == []


class TestGatlingCollectorBadRepo:
    def test_returns_evidence(self, collector: GatlingCollector) -> None:
        results = collector.collect(BAD_FIXTURES, config=None)
        result_evidence = [e for e in results if e.kind == "gatling-result"]
        assert len(result_evidence) == 1

    def test_high_error_rate(self, collector: GatlingCollector) -> None:
        results = collector.collect(BAD_FIXTURES, config=None)
        result_ev = next(e for e in results if e.kind == "gatling-result")
        assert result_ev.payload["error_rate"] == 10.0
        assert result_ev.payload["ko_requests"] == 50

    def test_slow_response_times(self, collector: GatlingCollector) -> None:
        results = collector.collect(BAD_FIXTURES, config=None)
        result_ev = next(e for e in results if e.kind == "gatling-result")
        assert result_ev.payload["p95_response_time_ms"] == 7500
        assert result_ev.payload["p99_response_time_ms"] == 10000


# ---------------------------------------------------------------------------
# Rule tests
# ---------------------------------------------------------------------------


def _gatling_evidence(
    error_rate: float = 0.5,
    p95: int = 350,
    p99: int = 800,
    sim_dir: str = "target/gatling/sample-sim",
) -> Evidence:
    return Evidence(
        collector_name="gatling",
        collector_version="0.1.0",
        locator=f"{sim_dir}/js/stats.json",
        kind="gatling-result",
        payload={
            "simulation_dir": sim_dir,
            "total_requests": 1000,
            "ok_requests": 995,
            "ko_requests": 5,
            "error_rate": error_rate,
            "mean_response_time_ms": 150,
            "p50_response_time_ms": 120,
            "p75_response_time_ms": 180,
            "p95_response_time_ms": p95,
            "p99_response_time_ms": p99,
            "min_response_time_ms": 10,
            "max_response_time_ms": 1500,
            "requests_per_second": 50.0,
        },
    )


class TestGatlingPerformanceRule:
    def setup_method(self) -> None:
        self.rule = GatlingPerformanceThresholdsRule()

    def test_no_evidence_skipped(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped is True
        assert result.skip_reason == "no gatling-result evidence available"

    def test_good_performance_green(self) -> None:
        ev = _gatling_evidence(error_rate=0.5, p95=350, p99=800)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].severity == "info"
        assert result.findings[0].pattern_tag == "gatling-performance"

    def test_high_error_rate_red(self) -> None:
        ev = _gatling_evidence(error_rate=10.0, p95=350, p99=800)
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"
        assert "error rate 10.0%" in result.findings[0].summary

    def test_medium_error_rate_amber(self) -> None:
        ev = _gatling_evidence(error_rate=2.5, p95=350, p99=800)
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert "error rate 2.5%" in result.findings[0].summary

    def test_slow_p95_amber(self) -> None:
        ev = _gatling_evidence(error_rate=0.1, p95=2500, p99=3000)
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert "p95 response time 2500.0ms" in result.findings[0].summary

    def test_slow_p99_red(self) -> None:
        ev = _gatling_evidence(error_rate=0.1, p95=1500, p99=6000)
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"
        assert "p99 response time 6000.0ms" in result.findings[0].summary

    def test_multiple_issues_worst_wins(self) -> None:
        ev = _gatling_evidence(error_rate=10.0, p95=3000, p99=7000)
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"
        # All issues should be mentioned
        assert "error rate" in result.findings[0].summary
        assert "p95" in result.findings[0].summary
        assert "p99" in result.findings[0].summary

    def test_ignores_non_gatling_evidence(self) -> None:
        ev = Evidence(
            collector_name="other",
            collector_version="0.1.0",
            locator="other.json",
            kind="other-result",
            payload={},
        )
        result = self.rule.evaluate([ev], None)
        assert result.skipped is True

    def test_ignores_gatling_summary_evidence(self) -> None:
        ev = Evidence(
            collector_name="gatling",
            collector_version="0.1.0",
            locator="gatling-summary",
            kind="gatling-summary",
            payload={"simulation_count": 1, "simulations": ["sim1"]},
        )
        result = self.rule.evaluate([ev], None)
        assert result.skipped is True


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_rule_protocol_compliance() -> None:
    rule = GatlingPerformanceThresholdsRule()
    assert hasattr(rule, "id")
    assert hasattr(rule, "band")
    assert hasattr(rule, "required_collectors")
    assert rule.id == "gatling-performance-thresholds"
    assert rule.band == 2
    assert rule.required_collectors == ["gatling"]
    result = rule.evaluate([], None)
    assert isinstance(result, RuleResult)
    assert result.skipped is True


def test_finding_has_all_r007_fields() -> None:
    """Verify that when the rule fires, findings have all 10 R007 fields."""
    ev = _gatling_evidence()
    rule = GatlingPerformanceThresholdsRule()
    result = rule.evaluate([ev], None)
    assert not result.skipped
    for finding in result.findings:
        assert finding.rule_id
        assert finding.rag in ("red", "amber", "green")
        assert finding.severity
        assert finding.summary
        assert finding.recommendation
        assert finding.evidence_locator
        assert finding.collector_name == "gatling"
        assert finding.collector_version == "0.1.0"
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.pattern_tag
