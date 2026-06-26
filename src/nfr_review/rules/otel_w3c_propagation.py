# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-w3c-propagation: flags repos without W3C trace-context propagation configured."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.otel import OtelSdkConfigPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding

_W3C_PROPAGATOR_NAMES = frozenset({"tracecontext", "w3c", "traceparent"})


class OTelW3CPropagationRule(FieldRule[OtelSdkConfigPayload]):
    """Flag repos without W3C trace-context propagation configured."""

    id = "otel-w3c-propagation"
    collector_name = "otel"
    evidence_kind = "otel-sdk-config"
    payload_type = OtelSdkConfigPayload
    pattern_tag = "otel-w3c-propagation"
    required_tech: list[str] = []
    default_confidence = 0.9
    all_clear_summary = "W3C trace-context propagation is configured."
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

        first = relevant[0]
        all_propagators: set[str] = set()
        for ev in relevant:
            payload = self._coerce(ev.payload)
            propagators = payload.propagators
            all_propagators.update(p.lower() for p in propagators)

        has_w3c = bool(all_propagators & _W3C_PROPAGATOR_NAMES)

        if has_w3c:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_finding(
                        rule_id=self.id,
                        ev=first,
                        pattern_tag=self.pattern_tag,
                        default_confidence=0.9,
                        hit=Hit(
                            rag="green",
                            summary="W3C trace-context propagation is configured.",
                            recommendation="No action required.",
                            locator=first.locator,
                        ),
                    )
                ],
            )

        if all_propagators:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_finding(
                        rule_id=self.id,
                        ev=first,
                        pattern_tag=self.pattern_tag,
                        default_confidence=0.85,
                        hit=Hit(
                            rag="amber",
                            severity="medium",
                            summary=(
                                "Propagators configured ("
                                f"{', '.join(sorted(all_propagators))}"
                                ") but W3C tracecontext not included."
                            ),
                            recommendation=(
                                "Add 'tracecontext' to OTEL_PROPAGATORS for W3C "
                                "trace-context propagation. This is the industry standard "
                                "and required for cross-service trace correlation."
                            ),
                            locator=first.locator,
                            confidence=0.85,
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
                        summary="No trace-context propagation configured.",
                        recommendation=(
                            "Set OTEL_PROPAGATORS=tracecontext,baggage to enable "
                            "W3C trace-context propagation. For Spring Boot, configure "
                            "management.tracing.propagation.type=W3C. Without "
                            "propagation, cross-service trace correlation will not work."
                        ),
                        locator=first.locator,
                        confidence=0.8,
                    ),
                )
            ],
        )


__all__ = ["OTelW3CPropagationRule"]
