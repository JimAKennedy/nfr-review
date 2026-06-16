# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-file-exporter: flags repos without an OTLP file exporter for CI trace capture."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_FILE_EXPORTER_KEYWORDS = frozenset({"file", "otlp/file", "file/traces"})


class OTelFileExporterRule:
    """Flag repos without an OTel file exporter configured for CI trace capture."""

    id = "otel-file-exporter"
    band: Band = 1
    required_collectors: list[str] = ["otel"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        sdk_evidence = filter_evidence(evidence, "otel", "otel-sdk-config")
        collector_evidence = filter_evidence(evidence, "otel", "otel-analysis")
        if not sdk_evidence and not collector_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no otel evidence available",
            )

        first = (sdk_evidence or collector_evidence)[0]

        has_file_exporter = False

        for ev in sdk_evidence:
            exporter_type = ev.payload.exporter_type
            if exporter_type and exporter_type.lower() in ("file", "otlp/file"):
                has_file_exporter = True
                break

        if not has_file_exporter:
            for ev in collector_evidence:
                exporters = ev.payload.exporters
                for exp in exporters:
                    base = exp.split("/")[0]
                    if base in _FILE_EXPORTER_KEYWORDS:
                        has_file_exporter = True
                        break

        if has_file_exporter:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "otel-file-exporter",
                        first,
                        summary="OTel file exporter configured for trace capture.",
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
                        "No OTel file exporter detected. CI-based trace capture "
                        "requires a file exporter to persist traces for analysis."
                    ),
                    recommendation=(
                        "Configure OTEL_TRACES_EXPORTER=otlp with a file-based "
                        "protocol, or add a 'file' exporter in the OTel Collector "
                        "config. This enables nfr-review's Band 3 dynamic analysis "
                        "rules to consume trace data from CI test runs."
                    ),
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.75,
                    pattern_tag="otel-file-exporter",
                )
            ],
        )


def _register() -> None:
    if "otel-file-exporter" not in rule_registry:
        rule_registry.register("otel-file-exporter", OTelFileExporterRule())


_register()

__all__ = ["OTelFileExporterRule"]
