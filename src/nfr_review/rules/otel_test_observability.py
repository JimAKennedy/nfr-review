# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-test-observability: flags test configs missing OTel agent attachment."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.otel import OtelSdkConfigPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding


class OTelTestObservabilityRule(FieldRule[OtelSdkConfigPayload]):
    """Flag test configs that don't produce OTel traces.

    Bridges S01 (agent exists) and S02 (tests exercise endpoints) by
    ensuring test runs actually emit the traces Band 3 needs.
    """

    id = "otel-test-observability"
    collector_name = "otel"
    evidence_kind = "otel-sdk-config"
    payload_type = OtelSdkConfigPayload
    pattern_tag = "otel-test-observability"
    required_tech: list[str] = []
    default_confidence = 0.8
    all_clear_summary = (
        "Test configurations include OTel agent attachment. "
        "Test runs will produce traces for dynamic analysis."
    )
    all_clear_recommendation = "No action required."

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ci_evidence = [
            e
            for e in evidence
            if e.collector_name == "ci-artifact" and e.kind == "ci-pipeline"
        ]
        sdk_evidence = [
            e for e in evidence if e.collector_name == "otel" and e.kind == "otel-sdk-config"
        ]

        if not ci_evidence and not sdk_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no CI pipeline or otel-sdk-config evidence available",
            )

        first = (sdk_evidence or ci_evidence)[0]

        has_test_steps = any(e.payload.has_test_step for e in ci_evidence)
        has_otel_in_tests = any(e.payload.agent_attached for e in sdk_evidence)

        if not has_test_steps:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no test steps detected in CI pipelines",
            )

        if has_otel_in_tests:
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
                            summary=(
                                "Test configurations include OTel agent attachment. "
                                "Test runs will produce traces for dynamic analysis."
                            ),
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
                    default_confidence=0.75,
                    hit=Hit(
                        rag="amber",
                        severity="medium",
                        summary=(
                            "Tests exist but OTel agent is not wired into the test "
                            "runner. Test runs will not produce traces for Band 3 "
                            "dynamic analysis."
                        ),
                        recommendation=(
                            "Wire OTel into test configurations: add "
                            "-javaagent:opentelemetry-javaagent.jar to Maven "
                            "surefire/failsafe argLine, set OTEL_TRACES_EXPORTER=otlp "
                            "and OTEL_SERVICE_NAME in CI test step env vars, or add "
                            "opentelemetry-instrumentation to Python test deps."
                        ),
                        locator=first.locator,
                        confidence=0.75,
                    ),
                )
            ],
        )


__all__ = ["OTelTestObservabilityRule"]
