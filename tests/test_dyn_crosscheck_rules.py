"""Tests for dyn-adr-drift rule: runtime topology vs ADR-declared architecture."""

from __future__ import annotations

from nfr_review.collectors.payloads.adr import AdrDocumentPayload
from nfr_review.collectors.payloads.otel_trace import OtelTracePayload, OtelTraceSpan
from nfr_review.models import Evidence
from nfr_review.rules.dyn_adr_drift import DynAdrDriftRule


def _span(
    *,
    trace_id: str = "t1",
    span_id: str,
    parent_span_id: str = "",
    service_name: str,
    kind: int = 2,
    name: str = "op",
) -> OtelTraceSpan:
    return OtelTraceSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=name,
        service_name=service_name,
        kind=kind,
        start_time_unix_nano=0,
        end_time_unix_nano=100_000_000,
        status_code=1,
        code_namespace="",
        code_function="",
        attributes={},
    )


def _trace_evidence(spans: list[OtelTraceSpan]) -> Evidence:
    svc_names = sorted({s.service_name for s in spans if s.service_name})
    trace_ids = sorted({s.trace_id for s in spans if s.trace_id})
    return Evidence(
        collector_name="otel-trace",
        collector_version="0.1.0",
        locator="traces.json",
        kind="otel-trace",
        payload=OtelTracePayload(
            spans=spans,
            trace_ids=trace_ids,
            service_names=svc_names,
            source_file="traces.json",
        ),
    )


def _adr_evidence(title: str, body_text: str, status: str = "accepted") -> Evidence:
    return Evidence(
        collector_name="adr",
        collector_version="0.1.0",
        locator=f"docs/adr/{title}.md",
        kind="adr-document",
        payload=AdrDocumentPayload(
            file_path=f"docs/adr/{title}.md",
            title=title,
            status=status,
            body_text=body_text,
        ),
    )


def _multi_service_spans() -> list[OtelTraceSpan]:
    """3-service chain: gateway -> orders -> payments."""
    return [
        _span(span_id="s1", service_name="api-gateway"),
        _span(span_id="s2", parent_span_id="s1", service_name="api-gateway", kind=3),
        _span(span_id="s3", parent_span_id="s2", service_name="order-service"),
        _span(span_id="s4", parent_span_id="s3", service_name="order-service", kind=3),
        _span(span_id="s5", parent_span_id="s4", service_name="payment-service"),
    ]


class TestDynAdrDrift:
    def setup_method(self) -> None:
        self.rule = DynAdrDriftRule()

    def test_single_service_degradation(self) -> None:
        spans = [_span(span_id="s1", service_name="lonely-svc")]
        result = self.rule.evaluate([_trace_evidence(spans)], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "Single-service" in result.findings[0].summary
        assert result.findings[0].pattern_tag == "dyn-adr-drift-single-service"

    def test_no_adr_declarations(self) -> None:
        """Multi-service topology but no ADR evidence — reports info."""
        spans = _multi_service_spans()
        result = self.rule.evaluate([_trace_evidence(spans)], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "no ADR topology declarations" in result.findings[0].summary

    def test_topology_matches_adrs(self) -> None:
        """Observed topology exactly matches ADR declarations."""
        spans = _multi_service_spans()
        adr = _adr_evidence(
            "topology",
            "- api-gateway → order-service\n- order-service → payment-service\n",
        )
        result = self.rule.evaluate([_trace_evidence(spans), adr], context=None)
        rags = {f.rag for f in result.findings}
        assert "red" not in rags
        assert "amber" not in rags
        match_findings = [f for f in result.findings if f.pattern_tag == "dyn-adr-drift-match"]
        assert len(match_findings) == 1

    def test_undocumented_coupling(self) -> None:
        """Observed edge not declared in any ADR — red finding."""
        spans = _multi_service_spans()
        adr = _adr_evidence(
            "topology",
            "- api-gateway → order-service\n",
        )
        result = self.rule.evaluate([_trace_evidence(spans), adr], context=None)
        red = [f for f in result.findings if f.rag == "red"]
        assert len(red) == 1
        assert "order-service" in red[0].summary
        assert "payment-service" in red[0].summary

    def test_unobserved_declared(self) -> None:
        """ADR declares relationship not seen in traces — amber finding."""
        spans = _multi_service_spans()
        adr = _adr_evidence(
            "topology",
            (
                "- api-gateway → order-service\n"
                "- order-service → payment-service\n"
                "- api-gateway → inventory-service\n"
            ),
        )
        result = self.rule.evaluate([_trace_evidence(spans), adr], context=None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "inventory-service" in amber[0].summary

    def test_superseded_adr_ignored(self) -> None:
        """Superseded ADR declarations are not used for comparison."""
        spans = _multi_service_spans()
        adr = _adr_evidence(
            "old-topology",
            "- api-gateway → legacy-service\n",
            status="superseded",
        )
        result = self.rule.evaluate([_trace_evidence(spans), adr], context=None)
        assert all("legacy-service" not in f.summary for f in result.findings)

    def test_arrow_syntax_variants(self) -> None:
        """Both -> and → arrow syntaxes are parsed."""
        spans = _multi_service_spans()
        adr = _adr_evidence(
            "topology",
            "- api-gateway -> order-service\n- order-service --> payment-service\n",
        )
        result = self.rule.evaluate([_trace_evidence(spans), adr], context=None)
        rags = {f.rag for f in result.findings}
        assert "red" not in rags

    def test_no_trace_evidence_skips(self) -> None:
        """Rule skips when no otel-trace evidence is present."""
        adr = _adr_evidence("topology", "- a → b\n")
        result = self.rule.evaluate([adr], context=None)
        assert len(result.findings) == 1
        assert result.findings[0].pattern_tag == "dyn-adr-drift-single-service"

    def test_mixed_undocumented_and_unobserved(self) -> None:
        """Both undocumented and unobserved edges in the same evaluation."""
        spans = _multi_service_spans()
        adr = _adr_evidence(
            "topology",
            "- api-gateway → order-service\n- api-gateway → cache-service\n",
        )
        result = self.rule.evaluate([_trace_evidence(spans), adr], context=None)
        red = [f for f in result.findings if f.rag == "red"]
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(red) == 1  # order-service → payment-service undocumented
        assert len(amber) == 1  # api-gateway → cache-service unobserved
