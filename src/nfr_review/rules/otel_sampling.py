# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: otel-sampling — flags OTel Collector configs without sampling/rate-limiting."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

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


class OTelSamplingRule:
    """Flag OTel Collector configs without sampling or rate-limiting processors."""

    id = "otel-sampling"
    band: Band = 1
    required_collectors: list[str] = ["otel"]
    required_tech: list[str] = ["otel"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        otel_evidence = [
            e for e in evidence if e.collector_name == "otel" and e.kind == "otel-analysis"
        ]
        if not otel_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no otel-analysis evidence available",
            )

        first = otel_evidence[0]

        all_processors: set[str] = set()
        pipeline_processors: set[str] = set()
        for ev in otel_evidence:
            all_processors.update(ev.payload.get("processors", []))
            for _name, cfg in ev.payload.get("pipelines", {}).items():
                if isinstance(cfg, dict):
                    pipeline_processors.update(cfg.get("processors", []))

        processor_base_names = {p.split("/")[0] for p in all_processors | pipeline_processors}

        has_sampling = bool(processor_base_names & _SAMPLING_PROCESSORS)

        has_rate_limiting = False
        if "memory_limiter" in processor_base_names:
            for ev in otel_evidence:
                processors_config = {}
                for p in ev.payload.get("processors", []):
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
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(
                            "Sampling/rate-limiting processor configured: "
                            + ", ".join(found)
                            + "."
                        ),
                        recommendation="No action required.",
                        evidence_locator=first.locator,
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.85,
                        pattern_tag="otel-sampling",
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
                        "No sampling or rate-limiting processor configured."
                        " Risk of telemetry data volume explosion in production."
                    ),
                    recommendation=(
                        "Add a sampling processor (probabilistic_sampler,"
                        " tail_sampling) or rate-limiting processor"
                        " (memory_limiter) to control data volume."
                    ),
                    evidence_locator=first.locator,
                    collector_name=first.collector_name,
                    collector_version=first.collector_version,
                    confidence=0.8,
                    pattern_tag="otel-sampling",
                )
            ],
        )


def _register() -> None:
    if "otel-sampling" not in rule_registry:
        rule_registry.register("otel-sampling", OTelSamplingRule())


_register()

__all__ = ["OTelSamplingRule"]
