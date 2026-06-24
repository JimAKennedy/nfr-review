# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-test-agent: flags repos where test profiles don't attach the OTel agent."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.otel import OtelSdkConfigPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding


class OTelTestAgentRule(FieldRule[OtelSdkConfigPayload]):
    """Flag repos where test profiles lack OTel agent attachment."""

    id = "otel-test-agent"
    collector_name = "otel"
    evidence_kind = "otel-sdk-config"
    payload_type = OtelSdkConfigPayload
    pattern_tag = "otel-test-agent"
    required_tech: list[str] = []
    default_confidence = 0.9
    all_clear_summary = "OTel agent attachment detected in project configuration."
    all_clear_recommendation = "No action required."

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

        any_agent = any(self._coerce(e.payload).agent_attached for e in relevant)

        first = relevant[0]
        if any_agent:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_finding(
                        rule_id=self.id,
                        ev=first,
                        pattern_tag=self.pattern_tag,
                        default_confidence=0.85,
                        hit=Hit(
                            rag="green",
                            summary="OTel agent attachment detected in project configuration.",
                            recommendation="No action required.",
                            locator=first.locator,
                        ),
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_finding(
                    rule_id=self.id,
                    ev=first,
                    pattern_tag=self.pattern_tag,
                    default_confidence=0.8,
                    hit=Hit(
                        rag="amber",
                        severity="medium",
                        summary="No OTel agent attachment detected in test profiles.",
                        recommendation=(
                            "Attach the OTel Java agent to test JVM args "
                            "(-javaagent:opentelemetry-javaagent.jar) in Maven "
                            "surefire/failsafe or Gradle test tasks. For Python, "
                            "add opentelemetry-instrumentation to test dependencies. "
                            "For CI, set OTEL_* env vars in test workflow steps."
                        ),
                        locator=first.locator,
                        confidence=0.8,
                    ),
                )
            ],
        )


__all__ = ["OTelTestAgentRule"]
