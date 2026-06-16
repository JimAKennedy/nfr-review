# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-test-observability: flags test configs missing OTel agent attachment."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class OTelTestObservabilityRule:
    """Flag test configs that don't produce OTel traces.

    Bridges S01 (agent exists) and S02 (tests exercise endpoints) by
    ensuring test runs actually emit the traces Band 3 needs.
    """

    id = "otel-test-observability"
    band: Band = 1
    required_collectors: list[str] = ["otel"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ci_evidence = filter_evidence(evidence, "ci-artifact", "ci-pipeline")
        sdk_evidence = filter_evidence(evidence, "otel", "otel-sdk-config")

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
                    make_green_finding(
                        self.id,
                        "otel-test-observability",
                        first,
                        summary=(
                            "Test configurations include OTel agent attachment. "
                            "Test runs will produce traces for dynamic analysis."
                        ),
                        confidence=0.8,
                        evidence_locator=first.locator,
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
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.75,
                    pattern_tag="otel-test-observability",
                )
            ],
        )


def _register() -> None:
    if "otel-test-observability" not in rule_registry:
        rule_registry.register("otel-test-observability", OTelTestObservabilityRule())


_register()

__all__ = ["OTelTestObservabilityRule"]
