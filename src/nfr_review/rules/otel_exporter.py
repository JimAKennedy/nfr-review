# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: otel-exporter-config — flags OTel Collector configs without production exporters."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.otel import OtelAnalysisPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding

_PRODUCTION_EXPORTERS = frozenset(
    {
        "otlp",
        "otlphttp",
        "jaeger",
        "zipkin",
        "prometheus",
        "prometheusremotewrite",
        "elasticsearch",
        "datadog",
        "splunk_hec",
        "googlecloud",
        "awsxray",
        "azuremonitor",
    }
)

_DEV_ONLY_EXPORTERS = frozenset({"logging", "debug", "nop", "file"})


class OTelExporterConfigRule(FieldRule[OtelAnalysisPayload]):
    """Flag OTel Collector configs where no production exporter is configured."""

    id = "otel-exporter-config"
    collector_name = "otel"
    evidence_kind = "otel-analysis"
    payload_type = OtelAnalysisPayload
    pattern_tag = "otel-exporter-config"
    required_tech = ["otel"]
    default_confidence = 0.9
    all_clear_summary = "Production exporters configured."
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
        all_exporters: set[str] = set()
        for ev in relevant:
            payload = self._coerce(ev.payload)
            all_exporters.update(payload.exporters)

        base_names = {e.split("/")[0] for e in all_exporters}

        prod_exporters = base_names & _PRODUCTION_EXPORTERS
        dev_exporters = base_names & _DEV_ONLY_EXPORTERS

        if not prod_exporters and (not base_names or base_names <= _DEV_ONLY_EXPORTERS):
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_finding(
                        rule_id=self.id,
                        ev=first,
                        pattern_tag=self.pattern_tag,
                        default_confidence=0.9,
                        hit=Hit(
                            rag="red",
                            severity="high",
                            summary=(
                                "No production exporter configured."
                                " Only dev/debug exporters found: "
                                + ", ".join(sorted(dev_exporters))
                                + "."
                                if dev_exporters
                                else "No production exporter configured. No exporters found."
                            ),
                            recommendation=(
                                "Add a production exporter (otlp, jaeger, zipkin,"
                                " prometheus) to send telemetry data to a backend."
                            ),
                            locator=first.locator,
                        ),
                    )
                ],
            )

        if prod_exporters and len(prod_exporters) == 1:
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
                            summary=(
                                "Production exporter configured ("
                                + ", ".join(sorted(prod_exporters))
                                + ") but no fallback/redundancy."
                            ),
                            recommendation=(
                                "Consider adding a secondary exporter for redundancy"
                                " in case the primary backend is unavailable."
                            ),
                            locator=first.locator,
                            confidence=0.8,
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
                    default_confidence=0.9,
                    hit=Hit(
                        rag="green",
                        summary=(
                            "Production exporters configured: "
                            + ", ".join(sorted(prod_exporters))
                            + "."
                        ),
                        recommendation="No action required.",
                        locator=first.locator,
                    ),
                )
            ],
        )


__all__ = ["OTelExporterConfigRule"]
