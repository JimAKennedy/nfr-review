# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""dyn-method-coverage: report which methods were exercised during a test run."""

from __future__ import annotations

from collections import Counter
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.framework import register
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


@register
class DynMethodCoverageRule:
    """Aggregate observed code.namespace + code.function spans."""

    id = "dyn-method-coverage"
    band: Band = 3
    required_collectors: list[str] = ["otel-trace"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        trace_evidence = filter_evidence(evidence, "otel-trace", "otel-trace")
        if not trace_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no otel-trace evidence available",
            )

        method_hits: Counter[str] = Counter()
        total_spans = 0

        for ev in trace_evidence:
            for span in ev.payload.spans:
                total_spans += 1
                ns = span.get("code_namespace", "")
                fn = span.get("code_function", "")
                if ns and fn:
                    method_hits[f"{ns}.{fn}"] += 1
                elif fn:
                    method_hits[fn] += 1

        first = trace_evidence[0]
        service_names = first.payload.service_names
        services_str = ", ".join(service_names) if service_names else "unknown"

        if not method_hits:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Trace data contains {total_spans} span(s) but none carry "
                            "code.namespace/code.function attributes. "
                            "Method-level coverage cannot be computed."
                        ),
                        recommendation=(
                            "Ensure OTel instrumentation emits code.namespace and "
                            "code.function attributes on spans. Most auto-instrumentation "
                            "agents include these by default for Spring, Quarkus, and "
                            "Express frameworks."
                        ),
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.7,
                        pattern_tag="dyn-method-coverage-no-attrs",
                    )
                ],
            )

        top_methods = method_hits.most_common(20)
        method_list = "\n".join(
            f"  - {method} ({count} hit{'s' if count > 1 else ''})"
            for method, count in top_methods
        )
        remaining = len(method_hits) - len(top_methods)
        if remaining > 0:
            method_list += f"\n  - ... and {remaining} more"

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_green_finding(
                    self.id,
                    "dyn-method-coverage",
                    first,
                    summary=(
                        f"Observed {len(method_hits)} distinct instrumented methods "
                        f"across {total_spans} spans from service(s): {services_str}.\n"
                        f"Sample size: {total_spans} spans, "
                        f"{len(first.payload.trace_ids)} trace(s).\n"
                        f"Top methods:\n{method_list}"
                    ),
                    evidence_locator=first.locator,
                )
            ],
        )


__all__ = ["DynMethodCoverageRule"]
