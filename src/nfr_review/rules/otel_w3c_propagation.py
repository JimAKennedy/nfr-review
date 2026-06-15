# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-w3c-propagation: flags repos without W3C trace-context propagation configured."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_W3C_PROPAGATOR_NAMES = frozenset({"tracecontext", "w3c", "traceparent"})


class OTelW3CPropagationRule:
    """Flag repos without W3C trace-context propagation configured."""

    id = "otel-w3c-propagation"
    band: Band = 1
    required_collectors: list[str] = ["otel"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        sdk_evidence = filter_evidence(evidence, "otel", "otel-sdk-config")
        if not sdk_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no otel-sdk-config evidence available",
            )

        first = sdk_evidence[0]
        all_propagators: set[str] = set()
        for ev in sdk_evidence:
            propagators = ev.payload.get("propagators", [])
            all_propagators.update(p.lower() for p in propagators)

        has_w3c = bool(all_propagators & _W3C_PROPAGATOR_NAMES)

        if has_w3c:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "otel-w3c-propagation",
                        first,
                        summary="W3C trace-context propagation is configured.",
                        confidence=0.9,
                        evidence_locator=first.locator,
                    )
                ],
            )

        if all_propagators:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Propagators configured ({', '.join(sorted(all_propagators))}) "
                            "but W3C tracecontext not included."
                        ),
                        recommendation=(
                            "Add 'tracecontext' to OTEL_PROPAGATORS for W3C "
                            "trace-context propagation. This is the industry standard "
                            "and required for cross-service trace correlation."
                        ),
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.85,
                        pattern_tag="otel-w3c-propagation",
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
                    summary="No trace-context propagation configured.",
                    recommendation=(
                        "Set OTEL_PROPAGATORS=tracecontext,baggage to enable "
                        "W3C trace-context propagation. For Spring Boot, configure "
                        "management.tracing.propagation.type=W3C. Without "
                        "propagation, cross-service trace correlation will not work."
                    ),
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.8,
                    pattern_tag="otel-w3c-propagation",
                )
            ],
        )


def _register() -> None:
    if "otel-w3c-propagation" not in rule_registry:
        rule_registry.register("otel-w3c-propagation", OTelW3CPropagationRule())


_register()

__all__ = ["OTelW3CPropagationRule"]
