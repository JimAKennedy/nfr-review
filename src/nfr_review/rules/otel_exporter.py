# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: otel-exporter-config — flags OTel Collector configs without production exporters."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

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


class OTelExporterConfigRule:
    """Flag OTel Collector configs where no production exporter is configured."""

    id = "otel-exporter-config"
    band: Band = 1
    required_collectors: list[str] = ["otel"]
    required_tech: list[str] = ["otel"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        otel_evidence = filter_evidence(evidence, "otel", "otel-analysis")
        if not otel_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no otel-analysis evidence available",
            )

        first = otel_evidence[0]
        all_exporters: set[str] = set()
        for ev in otel_evidence:
            all_exporters.update(ev.payload.get("exporters", []))

        base_names = {e.split("/")[0] for e in all_exporters}

        prod_exporters = base_names & _PRODUCTION_EXPORTERS
        dev_exporters = base_names & _DEV_ONLY_EXPORTERS

        if not prod_exporters and (not base_names or base_names <= _DEV_ONLY_EXPORTERS):
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
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
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.9,
                        pattern_tag="otel-exporter-config",
                    )
                ],
            )

        if prod_exporters and len(prod_exporters) == 1:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
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
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.8,
                        pattern_tag="otel-exporter-config",
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_green_finding(
                    self.id,
                    "otel-exporter-config",
                    first,
                    summary=(
                        "Production exporters configured: "
                        + ", ".join(sorted(prod_exporters))
                        + "."
                    ),
                    confidence=0.9,
                    evidence_locator=first.locator,
                )
            ],
        )


def _register() -> None:
    if "otel-exporter-config" not in rule_registry:
        rule_registry.register("otel-exporter-config", OTelExporterConfigRule())


_register()

__all__ = ["OTelExporterConfigRule"]
