# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: otel-sampling — flags OTel Collector configs without sampling/rate-limiting."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.otel import OtelAnalysisPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding

_SAMPLING_PROCESSORS = frozenset(
    {
        "probabilistic_sampler",
        "tail_sampling",
        "filter",
    }
)

_RATE_LIMITING_PROCESSORS = frozenset(
    {
        "memory_limiter",
    }
)


class OTelSamplingRule(FieldRule[OtelAnalysisPayload]):
    """Flag OTel Collector configs without sampling or rate-limiting processors."""

    id = "otel-sampling"
    collector_name = "otel"
    evidence_kind = "otel-analysis"
    payload_type = OtelAnalysisPayload
    pattern_tag = "otel-sampling"
    required_tech = ["otel"]
    default_confidence = 0.9
    all_clear_summary = "Sampling/rate-limiting processor configured."
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

        all_processors: set[str] = set()
        pipeline_processors: set[str] = set()
        for ev in relevant:
            payload = self._coerce(ev.payload)
            all_processors.update(payload.processors)
            for _name, cfg in payload.pipelines.items():
                if isinstance(cfg, dict):
                    pipeline_processors.update(cfg.get("processors", []))

        processor_base_names = {p.split("/")[0] for p in all_processors | pipeline_processors}

        has_sampling = bool(processor_base_names & _SAMPLING_PROCESSORS)

        has_rate_limiting = False
        if "memory_limiter" in processor_base_names:
            for ev in relevant:
                payload = self._coerce(ev.payload)
                processors_config = {}
                for p in payload.processors:
                    processors_config[p] = True
            has_rate_limiting = True

        if has_sampling or has_rate_limiting:
            found = []
            if has_sampling:
                found.extend(sorted(processor_base_names & _SAMPLING_PROCESSORS))
            if has_rate_limiting:
                found.extend(sorted(processor_base_names & _RATE_LIMITING_PROCESSORS))
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
                            summary=(
                                "Sampling/rate-limiting processor configured: "
                                + ", ".join(found)
                                + "."
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
                    default_confidence=0.8,
                    hit=Hit(
                        rag="amber",
                        severity="medium",
                        summary=(
                            "No sampling or rate-limiting processor configured."
                            " Risk of telemetry data volume explosion in production."
                        ),
                        recommendation=(
                            "Add a sampling processor (probabilistic_sampler,"
                            " tail_sampling) or rate-limiting processor"
                            " (memory_limiter) to control data volume."
                        ),
                        locator=first.locator,
                        confidence=0.8,
                    ),
                )
            ],
        )


__all__ = ["OTelSamplingRule"]
