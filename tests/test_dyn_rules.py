# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for Band 3 quantitative runtime rules (S04)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.otel_trace import OtelTraceCollector
from nfr_review.config import Config, NfrTargetsConfig
from nfr_review.rules.dyn_correlation_propagation import DynCorrelationPropagationRule
from nfr_review.rules.dyn_latency_p95 import DynLatencyP95Rule
from nfr_review.rules.dyn_n_plus_1 import DynNPlus1Rule

FIXTURES = Path(__file__).parent / "fixtures" / "otel-traces"
LATENCY = FIXTURES / "traces-latency-mixed.json"
N_PLUS_1 = FIXTURES / "traces-n-plus-1.json"
CORRELATION = FIXTURES / "traces-correlation-broken.json"
SIMPLE = FIXTURES / "traces-simple.json"


@pytest.fixture()
def collector() -> OtelTraceCollector:
    return OtelTraceCollector()


def _collect(path: Path, collector: OtelTraceCollector):
    cfg = Config(otel_traces=path)
    return collector.collect(Path("."), cfg)


# ---------------------------------------------------------------------------
# dyn-latency-p95
# ---------------------------------------------------------------------------


class TestDynLatencyP95:
    def test_skips_without_evidence(self) -> None:
        rule = DynLatencyP95Rule()
        result = rule.evaluate([], Config())
        assert result.skipped is True

    def test_no_target_reports_info(self, collector: OtelTraceCollector) -> None:
        evidence = _collect(LATENCY, collector)
        rule = DynLatencyP95Rule()
        result = rule.evaluate(evidence, Config())
        assert not result.skipped
        orders_findings = [f for f in result.findings if "/api/orders" in f.pattern_tag]
        assert len(orders_findings) >= 1
        assert orders_findings[0].rag == "green"
        assert "No target declared" in orders_findings[0].summary

    def test_target_within_reports_green(self, collector: OtelTraceCollector) -> None:
        evidence = _collect(LATENCY, collector)
        cfg = Config(
            nfr_targets=NfrTargetsConfig(latency_p95_ms={"/api/health": 5000}),
        )
        rule = DynLatencyP95Rule()
        result = rule.evaluate(evidence, cfg)
        health_findings = [
            f
            for f in result.findings
            if "/api/health" in f.pattern_tag and "pass" in f.pattern_tag
        ]
        assert len(health_findings) == 1
        assert health_findings[0].rag == "green"

    def test_target_exceeded_reports_amber_or_red(self, collector: OtelTraceCollector) -> None:
        evidence = _collect(LATENCY, collector)
        cfg = Config(
            nfr_targets=NfrTargetsConfig(latency_p95_ms={"/api/orders": 200}),
        )
        rule = DynLatencyP95Rule()
        result = rule.evaluate(evidence, cfg)
        orders_findings = [f for f in result.findings if "/api/orders" in f.pattern_tag]
        assert len(orders_findings) >= 1
        assert orders_findings[0].rag in ("amber", "red")

    def test_sample_size_reported(self, collector: OtelTraceCollector) -> None:
        evidence = _collect(LATENCY, collector)
        rule = DynLatencyP95Rule()
        result = rule.evaluate(evidence, Config())
        for f in result.findings:
            assert "sample=" in f.summary

    def test_multiple_routes_reported(self, collector: OtelTraceCollector) -> None:
        evidence = _collect(LATENCY, collector)
        rule = DynLatencyP95Rule()
        result = rule.evaluate(evidence, Config())
        routes = {f.pattern_tag for f in result.findings}
        assert any("/api/orders" in r for r in routes)
        assert any("/api/health" in r for r in routes)


# ---------------------------------------------------------------------------
# dyn-correlation-propagation
# ---------------------------------------------------------------------------


class TestDynCorrelationPropagation:
    def test_skips_without_evidence(self) -> None:
        rule = DynCorrelationPropagationRule()
        result = rule.evaluate([], Config())
        assert result.skipped is True

    def test_broken_propagation_detected(self, collector: OtelTraceCollector) -> None:
        evidence = _collect(CORRELATION, collector)
        rule = DynCorrelationPropagationRule()
        result = rule.evaluate(evidence, Config())
        assert not result.skipped
        broken = [
            f for f in result.findings if f.pattern_tag == "dyn-correlation-propagation-broken"
        ]
        assert len(broken) == 1
        assert broken[0].rag in ("amber", "red")
        assert "Broken" in broken[0].summary

    def test_good_propagation_on_simple_traces(self, collector: OtelTraceCollector) -> None:
        evidence = _collect(SIMPLE, collector)
        rule = DynCorrelationPropagationRule()
        result = rule.evaluate(evidence, Config())
        assert not result.skipped
        unconfigured = [
            f
            for f in result.findings
            if f.pattern_tag == "dyn-correlation-propagation-unconfigured"
        ]
        assert len(unconfigured) >= 1


# ---------------------------------------------------------------------------
# dyn-n-plus-1
# ---------------------------------------------------------------------------


class TestDynNPlus1:
    def test_skips_without_evidence(self) -> None:
        rule = DynNPlus1Rule()
        result = rule.evaluate([], Config())
        assert result.skipped is True

    def test_detects_n_plus_1_pattern(self, collector: OtelTraceCollector) -> None:
        evidence = _collect(N_PLUS_1, collector)
        rule = DynNPlus1Rule()
        result = rule.evaluate(evidence, Config())
        assert not result.skipped
        n_plus_1 = [f for f in result.findings if f.rag in ("amber", "red")]
        assert len(n_plus_1) >= 1
        assert "N+1" in n_plus_1[0].summary
        assert "25" in n_plus_1[0].summary

    def test_clean_trace_no_findings(self, collector: OtelTraceCollector) -> None:
        evidence = _collect(SIMPLE, collector)
        rule = DynNPlus1Rule()
        result = rule.evaluate(evidence, Config())
        assert not result.skipped
        clean = [f for f in result.findings if f.pattern_tag == "dyn-n-plus-1-clean"]
        assert len(clean) == 1
        assert clean[0].rag == "green"

    def test_threshold_applied(self, collector: OtelTraceCollector) -> None:
        evidence = _collect(N_PLUS_1, collector)
        rule = DynNPlus1Rule()
        result = rule.evaluate(evidence, Config())
        red = [f for f in result.findings if f.rag == "red"]
        assert len(red) >= 1
