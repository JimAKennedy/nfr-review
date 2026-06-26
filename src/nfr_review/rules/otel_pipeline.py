# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""otel-pipeline-completeness: flags incomplete signal coverage."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.otel import OtelAnalysisPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding

_ALL_SIGNAL_TYPES = frozenset({"traces", "metrics", "logs"})


class OTelPipelineCompletenessRule(FieldRule[OtelAnalysisPayload]):
    """Flag OTel Collector configs where not all signal types have pipelines."""

    id = "otel-pipeline-completeness"
    collector_name = "otel"
    evidence_kind = "otel-analysis"
    payload_type = OtelAnalysisPayload
    pattern_tag = "otel-pipeline-completeness"
    required_tech = ["otel"]
    default_confidence = 0.9
    all_clear_summary = (
        "All three signal types (traces, metrics, logs) have pipelines configured."
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

        all_pipelines: dict[str, Any] = {}
        all_receivers: set[str] = set()
        all_exporters: set[str] = set()
        for ev in relevant:
            payload = self._coerce(ev.payload)
            pipelines = payload.pipelines
            if isinstance(pipelines, dict):
                all_pipelines.update(pipelines)
            all_receivers.update(payload.receivers)
            all_exporters.update(payload.exporters)

        if not all_pipelines:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_finding(
                        rule_id=self.id,
                        ev=first,
                        pattern_tag=self.pattern_tag,
                        default_confidence=0.95,
                        hit=Hit(
                            rag="red",
                            severity="high",
                            summary="No pipelines defined in OTel Collector configuration.",
                            recommendation=(
                                "Define pipelines under service.pipelines for traces,"
                                " metrics, and logs to route telemetry data."
                            ),
                            locator=first.locator,
                            confidence=0.95,
                        ),
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
                    make_finding(
                        rule_id=self.id,
                        ev=first,
                        pattern_tag=self.pattern_tag,
                        default_confidence=0.9,
                        hit=Hit(
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
                            locator=first.locator,
                        ),
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
                    make_finding(
                        rule_id=self.id,
                        ev=first,
                        pattern_tag=self.pattern_tag,
                        default_confidence=0.85,
                        hit=Hit(
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
                    default_confidence=0.9,
                    hit=Hit(
                        rag="green",
                        summary=(
                            "All three signal types (traces, metrics, logs)"
                            " have pipelines configured."
                        ),
                        recommendation="No action required.",
                        locator=first.locator,
                    ),
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
