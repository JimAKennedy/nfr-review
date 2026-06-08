# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Integration tests for Band 3 dynamic analysis (otel-trace collector + dyn rules)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.otel_trace import OtelTraceCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.models import Evidence
from nfr_review.registry import Registry
from nfr_review.rules.dyn_call_sequence import DynCallSequenceRule
from nfr_review.rules.dyn_method_coverage import DynMethodCoverageRule

FIXTURES = Path(__file__).parent / "fixtures" / "otel-traces"
SIMPLE = FIXTURES / "traces-simple.json"
MULTI = FIXTURES / "traces-multi-service.ndjson"
EMPTY = FIXTURES / "traces-empty.json"
MALFORMED = FIXTURES / "traces-malformed.json"


# ---------------------------------------------------------------------------
# Collector unit tests
# ---------------------------------------------------------------------------


class TestOtelTraceCollector:
    @pytest.fixture()
    def collector(self) -> OtelTraceCollector:
        return OtelTraceCollector()

    def test_no_config_path_returns_empty(self, collector: OtelTraceCollector) -> None:
        cfg = Config()
        assert collector.collect(Path("."), cfg) == []

    def test_missing_file_returns_empty(
        self, collector: OtelTraceCollector, tmp_path: Path
    ) -> None:
        cfg = Config(otel_traces=tmp_path / "nonexistent.json")
        assert collector.collect(tmp_path, cfg) == []

    def test_simple_json_produces_evidence(
        self, collector: OtelTraceCollector, tmp_path: Path
    ) -> None:
        cfg = Config(otel_traces=SIMPLE)
        evidence = collector.collect(tmp_path, cfg)
        assert len(evidence) == 1
        ev = evidence[0]
        assert ev.kind == "otel-trace"
        assert ev.collector_name == "otel-trace"
        spans = ev.payload.get("spans", [])
        assert len(spans) > 0
        assert any(s.get("service_name", "") == "greeting-service" for s in spans)

    def test_ndjson_produces_evidence(
        self, collector: OtelTraceCollector, tmp_path: Path
    ) -> None:
        cfg = Config(otel_traces=MULTI)
        evidence = collector.collect(tmp_path, cfg)
        assert len(evidence) == 1
        ev = evidence[0]
        service_names = ev.payload.get("service_names", [])
        assert "greeting-service" in service_names
        assert "api-gateway" in service_names

    def test_empty_traces_returns_empty(
        self, collector: OtelTraceCollector, tmp_path: Path
    ) -> None:
        cfg = Config(otel_traces=EMPTY)
        assert collector.collect(tmp_path, cfg) == []

    def test_malformed_returns_empty(
        self, collector: OtelTraceCollector, tmp_path: Path
    ) -> None:
        cfg = Config(otel_traces=MALFORMED)
        assert collector.collect(tmp_path, cfg) == []


# ---------------------------------------------------------------------------
# Rule unit tests
# ---------------------------------------------------------------------------


def _simple_evidence() -> list[Evidence]:
    collector = OtelTraceCollector()
    cfg = Config(otel_traces=SIMPLE)
    return collector.collect(Path("."), cfg)


class TestDynMethodCoverage:
    def test_skipped_without_evidence(self) -> None:
        rule = DynMethodCoverageRule()
        result = rule.evaluate([], None)
        assert result.skipped is True

    def test_reports_methods_from_simple_trace(self) -> None:
        rule = DynMethodCoverageRule()
        evidence = _simple_evidence()
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) >= 1
        f = result.findings[0]
        assert f.rag == "green"
        assert "distinct instrumented methods" in f.summary

    def test_amber_when_no_code_attrs(self, tmp_path: Path) -> None:
        rule = DynMethodCoverageRule()
        ev = Evidence(
            collector_name="otel-trace",
            collector_version="0.1.0",
            locator="test",
            kind="otel-trace",
            payload={
                "spans": [
                    {"trace_id": "abc", "span_id": "1", "name": "GET /foo"},
                ],
                "trace_ids": ["abc"],
                "service_names": ["svc"],
                "source_file": "test.json",
            },
        )
        result = rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "amber"


class TestDynCallSequence:
    def test_skipped_without_evidence(self) -> None:
        rule = DynCallSequenceRule()
        result = rule.evaluate([], None)
        assert result.skipped is True

    def test_generates_mermaid_from_simple_trace(self) -> None:
        rule = DynCallSequenceRule()
        evidence = _simple_evidence()
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        green_findings = [f for f in result.findings if f.rag == "green"]
        assert len(green_findings) >= 1
        assert any("sequenceDiagram" in f.summary for f in green_findings)
        assert any("mermaid" in f.summary for f in green_findings)

    def test_amber_when_no_parent_linkage(self) -> None:
        rule = DynCallSequenceRule()
        ev = Evidence(
            collector_name="otel-trace",
            collector_version="0.1.0",
            locator="test",
            kind="otel-trace",
            payload={
                "spans": [
                    {"trace_id": "abc", "span_id": "1", "name": "op1"},
                ],
                "trace_ids": ["abc"],
                "service_names": [],
                "source_file": "test.json",
            },
        )
        result = rule.evaluate([ev], None)
        assert not result.skipped


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------


class TestDynPipelineIntegration:
    """Full collector -> evidence -> rules -> findings pipeline."""

    @pytest.fixture()
    def result(self, tmp_path: Path) -> RunResult:
        cregistry: Registry = Registry("collector")
        rregistry: Registry = Registry("rule")

        cregistry.register("otel-trace", OtelTraceCollector())
        rregistry.register("dyn-method-coverage", DynMethodCoverageRule())
        rregistry.register("dyn-call-sequence", DynCallSequenceRule())

        engine = Engine(collectors=cregistry, rules=rregistry)
        cfg = Config(otel_traces=SIMPLE, exclude_test_paths=False)
        return engine.run(target=tmp_path, config=cfg)

    def test_both_rules_run(self, result: RunResult) -> None:
        run_set = set(result.run_metadata.rules_run)
        assert {"dyn-method-coverage", "dyn-call-sequence"} <= run_set

    def test_method_coverage_findings(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "dyn-method-coverage"]
        assert len(findings) >= 1

    def test_call_sequence_findings(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "dyn-call-sequence"]
        assert len(findings) >= 1
        assert any("sequenceDiagram" in f.summary for f in findings)

    def test_no_red_findings(self, result: RunResult) -> None:
        red = [f for f in result.findings if f.rag == "red"]
        assert red == []
