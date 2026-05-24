# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: gatling-performance-thresholds — evaluates Gatling simulation results
against performance thresholds for error rate and response time percentiles."""

from __future__ import annotations

from typing import Any

from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class GatlingPerformanceThresholdsRule:
    """Evaluate Gatling evidence against performance thresholds.

    Thresholds:
    - Error rate > 5% -> red/high
    - Error rate > 1% -> amber/medium
    - p95 response time > 2000ms -> amber/medium
    - p99 response time > 5000ms -> red/high
    - All pass -> green/info
    """

    id = "gatling-performance-thresholds"
    band: Band = 2
    required_collectors: list[str] = ["gatling"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        gatling_evidence = [
            e for e in evidence if e.collector_name == "gatling" and e.kind == "gatling-result"
        ]
        if not gatling_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no gatling-result evidence available",
            )

        findings: list[Finding] = []

        for ev in gatling_evidence:
            error_rate = ev.payload.get("error_rate", 0.0)
            p95 = ev.payload.get("p95_response_time_ms", 0)
            p99 = ev.payload.get("p99_response_time_ms", 0)
            sim_dir = ev.payload.get("simulation_dir", ev.locator)

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

            findings.append(
                Finding(
                    rule_id=self.id,
                    rag=worst_rag,
                    severity=worst_severity,
                    summary=summary,
                    recommendation=recommendation,
                    evidence_locator=ev.locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.85,
                    pattern_tag="gatling-performance",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "gatling-performance-thresholds" not in rule_registry:
        rule_registry.register(
            "gatling-performance-thresholds",
            GatlingPerformanceThresholdsRule(),
        )


_register()

__all__ = ["GatlingPerformanceThresholdsRule"]
