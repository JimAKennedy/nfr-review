# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""dyn-call-sequence: generate Mermaid sequence diagrams from trace trees."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_DEFAULT_MAX_DIAGRAMS = 10


class DynCallSequenceRule:
    """Generate Mermaid sequenceDiagram blocks from trace span trees."""

    id = "dyn-call-sequence"
    band: Band = 3
    required_collectors: list[str] = ["otel-trace"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        trace_evidence = [
            e for e in evidence if e.collector_name == "otel-trace" and e.kind == "otel-trace"
        ]
        if not trace_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no otel-trace evidence available",
            )

        all_spans: list[dict[str, Any]] = []
        for ev in trace_evidence:
            for span in ev.payload.get("spans", []):
                if isinstance(span, dict):
                    all_spans.append(span)
                else:
                    all_spans.append(
                        {f: getattr(span, f, "") for f in type(span).model_fields}
                    )

        if not all_spans:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="trace evidence contains no spans",
            )

        traces: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for span in all_spans:
            tid = span.get("trace_id", "")
            if tid:
                traces[tid].append(span)

        sorted_traces = sorted(traces.items(), key=lambda kv: len(kv[1]), reverse=True)
        max_diagrams = _DEFAULT_MAX_DIAGRAMS
        if hasattr(context, "max_diagrams"):
            max_diagrams = context.max_diagrams

        findings: list[Finding] = []
        first = trace_evidence[0]

        for trace_id, spans in sorted_traces[:max_diagrams]:
            mermaid = _build_sequence_diagram(trace_id, spans)
            if mermaid:
                root_span = _find_root_span(spans)
                root_name = root_span.get("name", trace_id[:8]) if root_span else trace_id[:8]
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(
                            f"Call sequence for trace {trace_id[:16]}... "
                            f"(entry: {root_name}, {len(spans)} spans):\n"
                            f"```mermaid\n{mermaid}\n```"
                        ),
                        recommendation="No action required.",
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.9,
                        pattern_tag="dyn-call-sequence",
                    )
                )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="low",
                    summary=(
                        "Trace data available but no sequence diagrams could be "
                        "generated (spans may lack parent-child relationships)."
                    ),
                    recommendation=(
                        "Ensure trace spans have proper parent_span_id linkages "
                        "for sequence diagram generation."
                    ),
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.6,
                    pattern_tag="dyn-call-sequence-no-tree",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _find_root_span(spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    for span in spans:
        parent = span.get("parent_span_id", "")
        if not parent:
            return span
    return spans[0] if spans else None


def _participant_name(span: dict[str, Any]) -> str:
    svc = span.get("service_name", "")
    ns = span.get("code_namespace", "")
    if svc and ns:
        short_ns = ns.rsplit(".", 1)[-1]
        return f"{svc}/{short_ns}"
    if svc:
        return svc
    if ns:
        return ns.rsplit(".", 1)[-1]
    return "unknown"


def _build_sequence_diagram(trace_id: str, spans: list[dict[str, Any]]) -> str:
    if not spans:
        return ""

    span_map: dict[str, dict[str, Any]] = {}
    for s in spans:
        sid = s.get("span_id", "")
        if sid:
            span_map[sid] = s

    sorted_spans = sorted(spans, key=lambda s: s.get("start_time_unix_nano", 0))

    participants: dict[str, None] = {}
    messages: list[str] = []

    for span in sorted_spans:
        parent_id = span.get("parent_span_id", "")
        caller = _participant_name(span_map[parent_id]) if parent_id in span_map else "Client"
        callee = _participant_name(span)
        span_name = span.get("name", "?")

        if caller not in participants:
            participants[caller] = None
        if callee not in participants:
            participants[callee] = None

        if caller != callee:
            messages.append(f"    {caller}->>+{callee}: {span_name}")
            messages.append(f"    {callee}-->>-{caller}: return")
        else:
            messages.append(f"    {callee}->>+{callee}: {span_name}")
            messages.append(f"    {callee}-->>-{callee}: return")

    if not messages:
        return ""

    lines = ["sequenceDiagram"]
    for p in participants:
        safe = p.replace('"', "'")
        lines.append(f"    participant {safe}")
    lines.extend(messages)
    return "\n".join(lines)


def _register() -> None:
    if "dyn-call-sequence" not in rule_registry:
        rule_registry.register("dyn-call-sequence", DynCallSequenceRule())


_register()

__all__ = ["DynCallSequenceRule"]
