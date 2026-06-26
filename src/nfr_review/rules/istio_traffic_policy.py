# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: istio-traffic-policy -- flags DestinationRules without trafficPolicy."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from nfr_review.collectors.payloads.istio import IstioAnalysisPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit


class IstioTrafficPolicyRule(FieldRule[IstioAnalysisPayload]):
    """Flag DestinationRules that lack trafficPolicy with connectionPool settings."""

    id = "istio-traffic-policy"
    collector_name = "istio"
    evidence_kind = "istio-analysis"
    payload_type = IstioAnalysisPayload
    pattern_tag = "istio-traffic-policy"
    required_tech = ["istio"]
    default_confidence = 0.85
    all_clear_summary = (
        "All DestinationRules have trafficPolicy with connectionPool configured."
    )
    all_clear_recommendation = "No action required."

    def check(self, payload: IstioAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        dest_rules = [r for r in payload.resources if r.kind == "DestinationRule"]
        if not dest_rules:
            return

        missing_policy: list[str] = []
        for dr in dest_rules:
            traffic_policy = dr.spec.get("trafficPolicy")
            if not traffic_policy or not traffic_policy.get("connectionPool"):
                missing_policy.append(dr.name)

        if missing_policy:
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(
                    f"DestinationRule(s) missing trafficPolicy"
                    f" with connectionPool: {', '.join(missing_policy)}."
                ),
                recommendation=(
                    "Configure trafficPolicy with connectionPool limits"
                    " (tcp.maxConnections, http.http1MaxPendingRequests)"
                    " to prevent resource exhaustion."
                ),
                locator=payload.file_path,
            )

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        relevant = [
            e
            for e in evidence
            if e.collector_name == self.collector_name and e.kind == self.evidence_kind
        ]
        if not relevant:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason=f"no {self.evidence_kind} evidence available",
            )

        has_dest_rule = any(
            r.kind == "DestinationRule"
            for ev in relevant
            for r in self._coerce(ev.payload).resources
        )
        if not has_dest_rule:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no DestinationRule resources found",
            )

        return super().evaluate(evidence, context)


__all__ = ["IstioTrafficPolicyRule"]
