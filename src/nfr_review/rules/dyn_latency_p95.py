# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""dyn-latency-p95: endpoint latency vs declared targets from otel-trace evidence."""

from __future__ import annotations

import math
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = math.ceil(0.95 * len(s)) - 1
    return s[max(idx, 0)]


class DynLatencyP95Rule:
    """Compare p95 latency per HTTP route against declared nfr_targets."""

    id = "dyn-latency-p95"
    band: Band = 3
    required_collectors: list[str] = ["otel-trace"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        trace_ev = filter_evidence(evidence, "otel-trace", "otel-trace")
        if not trace_ev:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no otel-trace evidence available",
            )

        route_durations: dict[str, list[float]] = {}
        for ev in trace_ev:
            for span in ev.payload.get("spans", []):
                if span.get("kind") != 2:
                    continue
                route = span.get("attributes", {}).get("http.route", "")
                if not route:
                    continue
                start = span.get("start_time_unix_nano", 0)
                end = span.get("end_time_unix_nano", 0)
                duration_ms = (end - start) / 1_000_000
                route_durations.setdefault(route, []).append(duration_ms)

        if not route_durations:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no server spans with http.route found in trace data",
            )

        targets: dict[str, int] = {}
        if hasattr(context, "nfr_targets"):
            targets = getattr(context.nfr_targets, "latency_p95_ms", {})
            if targets is None:
                targets = {}

        first = trace_ev[0]
        findings: list[Finding] = []

        for route, durations in sorted(route_durations.items()):
            p95_val = _p95(durations)
            sample_size = len(durations)
            target_ms = targets.get(route)

            if target_ms is None:
                findings.append(
                    make_green_finding(
                        self.id,
                        f"dyn-latency-p95-no-target:{route}",
                        first,
                        summary=(
                            f"Route {route}: observed p95={p95_val:.0f}ms "
                            f"(sample={sample_size}). No target declared."
                        ),
                        recommendation=(
                            f"Consider adding a latency target for {route} in "
                            "nfr_targets.latency_p95_ms."
                        ),
                        confidence=0.8,
                        evidence_locator=first.locator,
                    )
                )
            elif p95_val <= target_ms:
                findings.append(
                    make_green_finding(
                        self.id,
                        f"dyn-latency-p95-pass:{route}",
                        first,
                        summary=(
                            f"Route {route}: p95={p95_val:.0f}ms within target "
                            f"{target_ms}ms (sample={sample_size})."
                        ),
                        evidence_locator=first.locator,
                    )
                )
            elif p95_val <= 2 * target_ms:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Route {route}: p95={p95_val:.0f}ms exceeds target "
                            f"{target_ms}ms but within 2x (sample={sample_size})."
                        ),
                        recommendation=(
                            f"Investigate latency on {route}. The p95 is between "
                            f"1x and 2x the declared target of {target_ms}ms."
                        ),
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.85,
                        pattern_tag=f"dyn-latency-p95-amber:{route}",
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=(
                            f"Route {route}: p95={p95_val:.0f}ms exceeds 2x target "
                            f"{target_ms}ms (sample={sample_size})."
                        ),
                        recommendation=(
                            f"Route {route} latency is critically above the "
                            f"declared target of {target_ms}ms. Profile the "
                            "endpoint to identify bottlenecks."
                        ),
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.85,
                        pattern_tag=f"dyn-latency-p95-red:{route}",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "dyn-latency-p95" not in rule_registry:
        rule_registry.register("dyn-latency-p95", DynLatencyP95Rule())


_register()

__all__ = ["DynLatencyP95Rule"]
