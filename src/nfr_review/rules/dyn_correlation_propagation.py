# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""dyn-correlation-propagation: verify correlation-ID end-to-end from otel-trace evidence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

CORRELATION_KEYS = ("correlation.id", "baggage.correlation.id", "X-Correlation-ID")


class DynCorrelationPropagationRule:
    """Verify correlation/trace attribute consistency across trace spans."""

    id = "dyn-correlation-propagation"
    band: Band = 3
    required_collectors: list[str] = ["otel-trace"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        trace_ev = [
            e for e in evidence if e.collector_name == "otel-trace" and e.kind == "otel-trace"
        ]
        if not trace_ev:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no otel-trace evidence available",
            )

        traces: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for ev in trace_ev:
            for span in ev.payload.get("spans", []):
                tid = span.get("trace_id", "")
                if tid:
                    traces[tid].append(span)

        if not traces:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no traces found in otel-trace evidence",
            )

        first = trace_ev[0]
        good = 0
        broken = 0
        unconfigured = 0

        for _trace_id, spans in traces.items():
            root_spans = [s for s in spans if not s.get("parent_span_id")]
            if not root_spans:
                root_spans = spans[:1]

            root_corr = _get_correlation(root_spans[0])
            if not root_corr:
                unconfigured += 1
                continue

            child_spans = [s for s in spans if s.get("parent_span_id")]
            if not child_spans:
                good += 1
                continue

            all_propagated = all(_get_correlation(s) for s in child_spans)
            if all_propagated:
                good += 1
            else:
                broken += 1

        total = good + broken + unconfigured
        findings: list[Finding] = []

        if broken == 0 and good > 0:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        f"Correlation-ID propagation consistent across all "
                        f"{good} configured trace(s) "
                        f"(total={total}, unconfigured={unconfigured})."
                    ),
                    recommendation="No action required.",
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.85,
                    pattern_tag="dyn-correlation-propagation-pass",
                )
            )
        elif broken > 0:
            rag: Literal["red", "amber"] = "red" if good == 0 else "amber"
            severity: Literal["high", "medium"] = "high" if good == 0 else "medium"
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag=rag,
                    severity=severity,
                    summary=(
                        f"Broken correlation-ID propagation in {broken} of "
                        f"{good + broken} configured trace(s). "
                        f"Root spans carry correlation attributes but downstream "
                        f"spans do not (total={total}, unconfigured={unconfigured})."
                    ),
                    recommendation=(
                        "Ensure correlation-ID attributes are propagated via "
                        "OTel baggage or context propagation to all downstream "
                        "services. Check instrumentation middleware configuration."
                    ),
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.8,
                    pattern_tag="dyn-correlation-propagation-broken",
                )
            )

        if unconfigured > 0 and good == 0 and broken == 0:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        f"No correlation-ID attributes found on any of {unconfigured} "
                        f"trace(s). Correlation propagation may not be configured."
                    ),
                    recommendation=(
                        "Consider adding correlation-ID propagation via OTel "
                        "baggage if end-to-end request tracing is required."
                    ),
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.7,
                    pattern_tag="dyn-correlation-propagation-unconfigured",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _get_correlation(span: dict[str, Any]) -> str:
    attrs = span.get("attributes", {})
    for key in CORRELATION_KEYS:
        val = attrs.get(key, "")
        if val:
            return val
    return ""


def _register() -> None:
    if "dyn-correlation-propagation" not in rule_registry:
        rule_registry.register("dyn-correlation-propagation", DynCorrelationPropagationRule())


_register()

__all__ = ["DynCorrelationPropagationRule"]
