# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-test-agent: flags repos where test profiles don't attach the OTel agent."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class OTelTestAgentRule:
    """Flag repos where test profiles lack OTel agent attachment."""

    id = "otel-test-agent"
    band: Band = 1
    required_collectors: list[str] = ["otel"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        sdk_evidence = [
            e for e in evidence if e.collector_name == "otel" and e.kind == "otel-sdk-config"
        ]
        if not sdk_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no otel-sdk-config evidence available",
            )

        any_agent = any(e.payload.get("agent_attached") for e in sdk_evidence)

        first = sdk_evidence[0]
        if any_agent:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary="OTel agent attachment detected in project configuration.",
                        recommendation="No action required.",
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.85,
                        pattern_tag="otel-test-agent",
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=("No OTel agent attachment detected in test profiles."),
                    recommendation=(
                        "Attach the OTel Java agent to test JVM args "
                        "(-javaagent:opentelemetry-javaagent.jar) in Maven "
                        "surefire/failsafe or Gradle test tasks. For Python, "
                        "add opentelemetry-instrumentation to test dependencies. "
                        "For CI, set OTEL_* env vars in test workflow steps."
                    ),
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.8,
                    pattern_tag="otel-test-agent",
                )
            ],
        )


def _register() -> None:
    if "otel-test-agent" not in rule_registry:
        rule_registry.register("otel-test-agent", OTelTestAgentRule())


_register()

__all__ = ["OTelTestAgentRule"]
