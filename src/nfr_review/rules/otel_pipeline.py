# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-pipeline-completeness: flags incomplete signal coverage."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.framework import register
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_ALL_SIGNAL_TYPES = frozenset({"traces", "metrics", "logs"})


@register
class OTelPipelineCompletenessRule:
    """Flag OTel Collector configs where not all signal types have pipelines."""

    id = "otel-pipeline-completeness"
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

        all_pipelines: dict[str, Any] = {}
        all_receivers: set[str] = set()
        all_exporters: set[str] = set()
        for ev in otel_evidence:
            pipelines = ev.payload.pipelines
            if isinstance(pipelines, dict):
                all_pipelines.update(pipelines)
            all_receivers.update(ev.payload.receivers)
            all_exporters.update(ev.payload.exporters)

        if not all_pipelines:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary="No pipelines defined in OTel Collector configuration.",
                        recommendation=(
                            "Define pipelines under service.pipelines for traces,"
                            " metrics, and logs to route telemetry data."
                        ),
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.95,
                        pattern_tag="otel-pipeline-completeness",
                    )
                ],
            )

        undefined_refs = self._find_undefined_references(
            all_pipelines, all_receivers, all_exporters
        )
        if undefined_refs:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=(
                            "Pipeline references undefined components: "
                            + ", ".join(sorted(undefined_refs))
                            + "."
                        ),
                        recommendation=(
                            "Ensure all receivers, processors, and exporters"
                            " referenced in pipelines are defined in the"
                            " corresponding top-level sections."
                        ),
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.9,
                        pattern_tag="otel-pipeline-completeness",
                    )
                ],
            )

        configured_signals = set()
        for pipeline_name in all_pipelines:
            base = pipeline_name.split("/")[0]
            if base in _ALL_SIGNAL_TYPES:
                configured_signals.add(base)

        missing = _ALL_SIGNAL_TYPES - configured_signals
        if missing:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            "Incomplete signal coverage. Missing pipelines for: "
                            + ", ".join(sorted(missing))
                            + "."
                        ),
                        recommendation=(
                            "Add pipelines for all three signal types (traces,"
                            " metrics, logs) for comprehensive observability."
                        ),
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.85,
                        pattern_tag="otel-pipeline-completeness",
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_green_finding(
                    self.id,
                    "otel-pipeline-completeness",
                    first,
                    summary=(
                        "All three signal types (traces, metrics, logs)"
                        " have pipelines configured."
                    ),
                    confidence=0.9,
                    evidence_locator=first.locator,
                )
            ],
        )

    @staticmethod
    def _find_undefined_references(
        pipelines: dict[str, Any],
        defined_receivers: set[str],
        defined_exporters: set[str],
    ) -> set[str]:
        undefined: set[str] = set()
        for _name, cfg in pipelines.items():
            if not isinstance(cfg, dict):
                continue
            for receiver in cfg.get("receivers", []):
                if receiver not in defined_receivers:
                    undefined.add(f"receiver:{receiver}")
            for exporter in cfg.get("exporters", []):
                if exporter not in defined_exporters:
                    undefined.add(f"exporter:{exporter}")
        return undefined


__all__ = ["OTelPipelineCompletenessRule"]
