# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-file-exporter: flags repos without an OTLP file exporter for CI trace capture."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.otel import OtelAnalysisPayload, OtelSdkConfigPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding

_FILE_EXPORTER_KEYWORDS = frozenset({"file", "otlp/file", "file/traces"})


class OTelFileExporterRule(FieldRule[OtelAnalysisPayload]):
    """Flag repos without an OTel file exporter configured for CI trace capture."""

    id = "otel-file-exporter"
    collector_name = "otel"
    evidence_kind = "otel-analysis"
    payload_type = OtelAnalysisPayload
    pattern_tag = "otel-file-exporter"
    required_tech: list[str] = []
    default_confidence = 0.75
    all_clear_summary = "OTel file exporter configured for trace capture."
    all_clear_recommendation = "No action required."

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        sdk_evidence = [
            e for e in evidence if e.collector_name == "otel" and e.kind == "otel-sdk-config"
        ]
        collector_evidence = [
            e
            for e in evidence
            if e.collector_name == self.collector_name and e.kind == self.evidence_kind
        ]
        if not sdk_evidence and not collector_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no otel evidence available",
            )

        first = (sdk_evidence or collector_evidence)[0]

        has_file_exporter = False

        for ev in sdk_evidence:
            sdk_payload = OtelSdkConfigPayload.model_validate(
                ev.payload.model_dump() if hasattr(ev.payload, "model_dump") else ev.payload
            )
            exporter_type = sdk_payload.exporter_type
            if exporter_type and exporter_type.lower() in ("file", "otlp/file"):
                has_file_exporter = True
                break

        if not has_file_exporter:
            for ev in collector_evidence:
                payload = self._coerce(ev.payload)
                exporters = payload.exporters
                for exp in exporters:
                    base = exp.split("/")[0]
                    if base in _FILE_EXPORTER_KEYWORDS:
                        has_file_exporter = True
                        break

        if has_file_exporter:
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
                            summary="OTel file exporter configured for trace capture.",
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
                            "No OTel file exporter detected. CI-based trace capture "
                            "requires a file exporter to persist traces for analysis."
                        ),
                        recommendation=(
                            "Configure OTEL_TRACES_EXPORTER=otlp with a file-based "
                            "protocol, or add a 'file' exporter in the OTel Collector "
                            "config. This enables nfr-review's Band 3 dynamic analysis "
                            "rules to consume trace data from CI test runs."
                        ),
                        locator=first.locator,
                        confidence=0.75,
                    ),
                )
            ],
        )


__all__ = ["OTelFileExporterRule"]
