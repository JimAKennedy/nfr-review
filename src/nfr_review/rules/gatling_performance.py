# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: gatling-performance-thresholds — evaluates Gatling simulation results
against performance thresholds for error rate and response time percentiles."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.gatling import GatlingResultPayload
from nfr_review.models import RAG, Evidence, Severity
from nfr_review.rules.framework import FieldRule, Hit


class GatlingPerformanceThresholdsRule(FieldRule[GatlingResultPayload]):
    """Evaluate Gatling evidence against performance thresholds.

    Thresholds:
    - Error rate > 5% -> red/high
    - Error rate > 1% -> amber/medium
    - p95 response time > 2000ms -> amber/medium
    - p99 response time > 5000ms -> red/high
    - All pass -> green/info
    """

    id = "gatling-performance-thresholds"
    band = 2
    collector_name = "gatling"
    evidence_kind = "gatling-result"
    payload_type = GatlingResultPayload
    pattern_tag = "gatling-performance"
    default_confidence = 0.85
    all_clear_summary = "All performance thresholds pass."
    all_clear_recommendation = "No action required — performance is within thresholds."

    def check(self, payload: GatlingResultPayload, ev: Evidence) -> Iterable[Hit]:
        error_rate = payload.error_rate
        p95 = payload.p95_response_time_ms
        p99 = payload.p99_response_time_ms
        sim_dir = payload.simulation_dir

        worst_rag: RAG = "green"
        worst_severity: Severity = "info"
        issues: list[str] = []

        # Check error rate
        if error_rate > 5.0:
            worst_rag = "red"
            worst_severity = "high"
            issues.append(f"error rate {error_rate}% exceeds 5% threshold")
        elif error_rate > 1.0:
            if worst_rag != "red":
                worst_rag = "amber"
                worst_severity = "medium"
            issues.append(f"error rate {error_rate}% exceeds 1% threshold")

        # Check p99 response time
        if p99 > 5000:
            worst_rag = "red"
            worst_severity = "high"
            issues.append(f"p99 response time {p99}ms exceeds 5000ms threshold")

        # Check p95 response time
        if p95 > 2000:
            if worst_rag != "red":
                worst_rag = "amber"
                worst_severity = "medium"
            issues.append(f"p95 response time {p95}ms exceeds 2000ms threshold")

        if issues:
            summary = f"Performance issues in {sim_dir}: {'; '.join(issues)}"
            recommendation = (
                "Investigate and address performance bottlenecks. "
                "Consider optimising slow endpoints, adding caching, "
                "or tuning resource limits."
            )
        else:
            summary = (
                f"All performance thresholds pass for {sim_dir}: "
                f"error rate {error_rate}%, p95 {p95}ms, p99 {p99}ms"
            )
            recommendation = "No action required — performance is within thresholds."

        yield Hit(
            rag=worst_rag,
            severity=worst_severity,
            summary=summary,
            recommendation=recommendation,
            locator=ev.locator,
        )


__all__ = ["GatlingPerformanceThresholdsRule"]
