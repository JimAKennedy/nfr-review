# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for dynamic diagram extraction (topology + sequence)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.models import Evidence, Finding
from nfr_review.output.diagrams import (
    build_topology_diagram,
    collect_dynamic_diagrams,
    extract_sequence_diagrams,
)

FIXTURES = Path(__file__).parent / "fixtures" / "otel-traces"


def _make_finding(summary: str) -> Finding:
    return Finding(
        rule_id="dyn-call-sequence",
        rag="green",
        severity="info",
        summary=summary,
        recommendation="No action required.",
        evidence_locator="traces.json",
        collector_name="otel-trace",
        collector_version="0.1.0",
        confidence=0.9,
        pattern_tag="dyn-call-sequence",
    )


def _load_trace_evidence(fixture_name: str) -> list[Evidence]:
    from nfr_review.collectors.otel_trace import OtelTraceCollector

    collector = OtelTraceCollector()

    class FakeConfig:
        otel_traces = str(FIXTURES / fixture_name)

    return collector.collect(FIXTURES.parent.parent, FakeConfig())


# --- extract_sequence_diagrams ---


class TestExtractSequenceDiagrams:
    def test_extracts_mermaid_from_summary(self) -> None:
        mermaid = (
            "sequenceDiagram\n    Client->>+Server: GET /api\n    Server-->>-Client: return"
        )
        f = _make_finding(f"Call sequence:\n```mermaid\n{mermaid}\n```")
        result = extract_sequence_diagrams([f])
        assert len(result) == 1
        assert "Call Sequence 1" in result
        assert "sequenceDiagram" in result["Call Sequence 1"]
        assert "Client->>+Server" in result["Call Sequence 1"]

    def test_extracts_multiple_from_multiple_findings(self) -> None:
        m1 = "sequenceDiagram\n    A->>B: call1"
        m2 = "sequenceDiagram\n    C->>D: call2"
        findings = [
            _make_finding(f"```mermaid\n{m1}\n```"),
            _make_finding(f"```mermaid\n{m2}\n```"),
        ]
        result = extract_sequence_diagrams(findings)
        assert len(result) == 2
        assert "Call Sequence 1" in result
        assert "Call Sequence 2" in result

    def test_no_mermaid_returns_empty(self) -> None:
        f = _make_finding("No diagrams here.")
        assert extract_sequence_diagrams([f]) == {}

    def test_empty_findings_returns_empty(self) -> None:
        assert extract_sequence_diagrams([]) == {}

    def test_ignores_non_sequence_mermaid(self) -> None:
        f = _make_finding("```mermaid\ngraph TD\n    A-->B\n```")
        assert extract_sequence_diagrams([f]) == {}


# --- build_topology_diagram ---


class TestBuildTopologyDiagram:
    def test_multi_service_produces_topology(self) -> None:
        evidence = _load_trace_evidence("traces-multi-service.ndjson")
        assert evidence, "fixture should load"
        result = build_topology_diagram(evidence)
        assert "Runtime Service Topology" in result
        assert "graph TD" in result["Runtime Service Topology"]

    def test_single_service_returns_empty(self) -> None:
        evidence = _load_trace_evidence("traces-simple.json")
        assert evidence, "fixture should load"
        result = build_topology_diagram(evidence)
        assert result == {}

    def test_no_evidence_returns_empty(self) -> None:
        assert build_topology_diagram([]) == {}

    def test_non_otel_evidence_ignored(self) -> None:
        ev = Evidence(
            collector_name="ci",
            collector_version="1.0",
            locator="ci.yml",
            kind="ci",
            payload={},
        )
        assert build_topology_diagram([ev]) == {}


# --- collect_dynamic_diagrams ---


class TestCollectDynamicDiagrams:
    def test_combines_topology_and_sequence(self) -> None:
        evidence = _load_trace_evidence("traces-multi-service.ndjson")
        mermaid = "sequenceDiagram\n    A->>B: call"
        findings = [_make_finding(f"```mermaid\n{mermaid}\n```")]
        result = collect_dynamic_diagrams(findings, evidence)
        assert "Runtime Service Topology" in result
        assert "Call Sequence 1" in result

    def test_empty_inputs_returns_empty(self) -> None:
        assert collect_dynamic_diagrams([], []) == {}

    def test_sequence_only_no_topology(self) -> None:
        mermaid = "sequenceDiagram\n    A->>B: call"
        findings = [_make_finding(f"```mermaid\n{mermaid}\n```")]
        result = collect_dynamic_diagrams(findings, [])
        assert "Call Sequence 1" in result
        assert "Runtime Service Topology" not in result

    def test_topology_only_no_sequence(self) -> None:
        evidence = _load_trace_evidence("traces-multi-service.ndjson")
        result = collect_dynamic_diagrams([], evidence)
        assert "Runtime Service Topology" in result
        assert len(result) == 1


# --- Integration: dyn-call-sequence rule produces extractable diagrams ---


class TestDynCallSequenceIntegration:
    def test_rule_findings_contain_extractable_mermaid(self) -> None:
        evidence = _load_trace_evidence("traces-multi-service.ndjson")
        assert evidence

        from nfr_review.rules.dyn_call_sequence import DynCallSequenceRule

        rule = DynCallSequenceRule()
        result = rule.evaluate(evidence, context=None)
        assert not result.skipped
        assert result.findings

        diagrams = extract_sequence_diagrams(result.findings)
        assert len(diagrams) >= 1
        for _title, mermaid in diagrams.items():
            assert mermaid.startswith("sequenceDiagram")

    @pytest.mark.parametrize(
        "fixture",
        ["traces-multi-service-topology.json", "traces-multi-service.ndjson"],
    )
    def test_topology_from_real_fixtures(self, fixture: str) -> None:
        evidence = _load_trace_evidence(fixture)
        result = build_topology_diagram(evidence)
        assert "Runtime Service Topology" in result
