# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-resource-attrs: flags repos without required OTel resource attributes."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.otel import OtelSdkConfigPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding

_REQUIRED_ATTRS = frozenset({"service.name", "service.version"})


class OTelResourceAttrsRule(FieldRule[OtelSdkConfigPayload]):
    """Flag repos without required OTel resource attributes (service.name, service.version)."""

    id = "otel-resource-attrs"
    collector_name = "otel"
    evidence_kind = "otel-sdk-config"
    payload_type = OtelSdkConfigPayload
    pattern_tag = "otel-resource-attrs"
    required_tech: list[str] = []
    default_confidence = 0.9
    all_clear_summary = (
        "Required OTel resource attributes (service.name, service.version) are configured."
    )
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
        all_attrs: set[str] = set()
        for ev in relevant:
            payload = self._coerce(ev.payload)
            resource_attrs = payload.resource_attributes
            if isinstance(resource_attrs, dict):
                all_attrs.update(resource_attrs.keys())

        missing = _REQUIRED_ATTRS - all_attrs

        if not missing:
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
                            summary=(
                                "Required OTel resource attributes (service.name, "
                                "service.version) are configured."
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
                    default_confidence=0.85,
                    hit=Hit(
                        rag="amber",
                        severity="medium",
                        summary=(
                            "Missing OTel resource attributes: "
                            + ", ".join(sorted(missing))
                            + "."
                        ),
                        recommendation=(
                            "Set OTEL_RESOURCE_ATTRIBUTES="
                            "service.name=<name>,service.version=<version> "
                            "or use OTEL_SERVICE_NAME for service.name. For Spring Boot, "
                            "set spring.application.name in application.yml. These "
                            "attributes are essential for trace correlation and "
                            "the dyn-adr-drift rule."
                        ),
                        locator=first.locator,
                        confidence=0.85,
                    ),
                )
            ],
        )


__all__ = ["OTelResourceAttrsRule"]
