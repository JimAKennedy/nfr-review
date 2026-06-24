# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-resource-attrs: flags repos without required OTel resource attributes."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.framework import register
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_REQUIRED_ATTRS = frozenset({"service.name", "service.version"})


@register
class OTelResourceAttrsRule:
    """Flag repos without required OTel resource attributes (service.name, service.version)."""

    id = "otel-resource-attrs"
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
        all_attrs: set[str] = set()
        for ev in sdk_evidence:
            resource_attrs = ev.payload.resource_attributes
            if isinstance(resource_attrs, dict):
                all_attrs.update(resource_attrs.keys())

        missing = _REQUIRED_ATTRS - all_attrs

        if not missing:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "otel-resource-attrs",
                        first,
                        summary=(
                            "Required OTel resource attributes (service.name, "
                            "service.version) are configured."
                        ),
                        confidence=0.9,
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
                        "Missing OTel resource attributes: " + ", ".join(sorted(missing)) + "."
                    ),
                    recommendation=(
                        "Set OTEL_RESOURCE_ATTRIBUTES="
                        "service.name=<name>,service.version=<version> "
                        "or use OTEL_SERVICE_NAME for service.name. For Spring Boot, "
                        "set spring.application.name in application.yml. These "
                        "attributes are essential for trace correlation and "
                        "the dyn-adr-drift rule."
                    ),
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.85,
                    pattern_tag="otel-resource-attrs",
                )
            ],
        )


__all__ = ["OTelResourceAttrsRule"]
