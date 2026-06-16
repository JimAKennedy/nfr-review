# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""PATCH-TELEM rules — patching telemetry standard conformance detection.

PATCH-TELEM-001: Golden signal emission coverage.
    GREEN  if OTel pipelines cover both metrics and traces signal types
           (needed for request_rate/error_rate/saturation and latency).
    AMBER  if OTel config exists but only one signal type is configured.
    INFO   if no telemetry-config evidence available (not applicable).
    SKIPPED when no telemetry-config collector evidence at all.

PATCH-TELEM-002: Mandatory label presence.
    GREEN  if resource attributes include service, version, ring, and side.
    AMBER  if resource attributes exist but are missing one or more mandatory labels.
    INFO   if no OTel collector config detected.
    SKIPPED when no telemetry-config collector evidence at all.

PATCH-TELEM-003: Synthetic transaction config detection.
    GREEN  if synthetic test definitions are found with at least one target.
    AMBER  if OTel config exists but no synthetic transaction config found.
    INFO   if no telemetry-config evidence available (not applicable).
    SKIPPED when no telemetry-config collector evidence at all.
"""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_GOLDEN_SIGNAL_TYPES = frozenset({"metrics", "traces"})

_MANDATORY_LABELS = ("service", "version", "ring", "side")

_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "service": ("service", "service.name", "service_name"),
    "version": ("version", "service.version", "service_version", "app.version"),
    "ring": ("ring", "deployment.ring", "ring_id"),
    "side": ("side", "deployment.side", "dr.side"),
}


def _telemetry_evidence(evidence: list[Evidence]) -> list[Evidence]:
    return filter_evidence(evidence, "telemetry-config")


def _pipeline_evidence(evidence: list[Evidence]) -> list[Evidence]:
    return [e for e in evidence if e.kind == "telemetry-pipeline"]


def _summary_evidence(evidence: list[Evidence]) -> list[Evidence]:
    return [e for e in evidence if e.kind == "telemetry-config-summary"]


def _synthetic_evidence(evidence: list[Evidence]) -> list[Evidence]:
    return [e for e in evidence if e.kind == "telemetry-synthetic-config"]


def _check_label_present(attrs: dict[str, Any], label: str) -> bool:
    aliases = _LABEL_ALIASES.get(label, (label,))
    return any(a in attrs for a in aliases)


class GoldenSignalEmissionRule:
    """PATCH-TELEM-001: detect golden signal emission coverage via OTel pipeline config."""

    id = "PATCH-TELEM-001"
    band: Band = 2
    required_collectors: list[str] = ["telemetry-config"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        telem = _telemetry_evidence(evidence)
        if not telem:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no telemetry-config collector evidence available",
            )

        pipelines = _pipeline_evidence(telem)
        if not pipelines:
            summaries = _summary_evidence(telem)
            ev = summaries[0] if summaries else telem[0]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-telem-golden-signals",
                        ev,
                        summary=(
                            "No OTel collector config detected"
                            " — golden signal check not applicable"
                        ),
                        recommendation=(
                            "If this service participates in a ringed patching programme,"
                            " configure an OTel collector with metrics and traces pipelines"
                            " to emit the four golden signals (request_rate, error_rate,"
                            " latency, saturation)."
                        ),
                        confidence=0.70,
                        evidence_locator=ev.locator,
                    )
                ],
            )

        all_signals: set[str] = set()
        for ev in pipelines:
            all_signals.update(ev.payload.signal_types)

        missing = _GOLDEN_SIGNAL_TYPES - all_signals
        ref = pipelines[0]

        if not missing:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-telem-golden-signals",
                        ref,
                        summary=(
                            f"OTel collector pipelines cover both metrics and traces"
                            f" signal types across {len(pipelines)} config(s)"
                        ),
                        recommendation=(
                            "No action required — golden signal pipeline coverage is present."
                        ),
                        evidence_locator=ref.locator,
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
                        "OTel collector config missing pipeline(s) for:"
                        f" {', '.join(sorted(missing))}."
                        f" Golden signals require both metrics (request_rate, error_rate,"
                        f" saturation) and traces (latency) pipelines"
                    ),
                    recommendation=(
                        f"Add {', '.join(sorted(missing))} pipeline(s) to the OTel"
                        f" collector config to ensure all four golden signals can be emitted."
                    ),
                    evidence_locator=ref.locator,
                    collector_name=ref.collector_name,
                    collector_version=ref.collector_version,
                    confidence=0.85,
                    pattern_tag="patch-telem-golden-signals",
                )
            ],
        )


class MandatoryLabelPresenceRule:
    """PATCH-TELEM-002: detect mandatory label presence in resource attributes."""

    id = "PATCH-TELEM-002"
    band: Band = 2
    required_collectors: list[str] = ["telemetry-config"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        telem = _telemetry_evidence(evidence)
        if not telem:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no telemetry-config collector evidence available",
            )

        pipelines = _pipeline_evidence(telem)
        if not pipelines:
            summaries = _summary_evidence(telem)
            ev = summaries[0] if summaries else telem[0]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-telem-labels",
                        ev,
                        summary=(
                            "No OTel collector config detected"
                            " — mandatory label check not applicable"
                        ),
                        recommendation=(
                            "If this service participates in a ringed patching programme,"
                            " configure resource attributes with mandatory labels:"
                            " service, version, ring, side."
                        ),
                        confidence=0.70,
                        evidence_locator=ev.locator,
                    )
                ],
            )

        merged_attrs: dict[str, Any] = {}
        for ev in pipelines:
            merged_attrs.update(ev.payload.resource_attributes)

        ref = pipelines[0]
        missing = [
            label
            for label in _MANDATORY_LABELS
            if not _check_label_present(merged_attrs, label)
        ]

        if not missing:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_green_finding(
                        self.id,
                        "patch-telem-labels",
                        ref,
                        summary=(
                            "All mandatory telemetry labels present in resource attributes:"
                            f" {', '.join(_MANDATORY_LABELS)}"
                        ),
                        recommendation="No action required — mandatory labels are configured.",
                        confidence=0.90,
                        evidence_locator=ref.locator,
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
                        f"OTel resource attributes missing mandatory label(s):"
                        f" {', '.join(missing)}"
                    ),
                    recommendation=(
                        f"Add the missing label(s) ({', '.join(missing)}) to the OTel"
                        f" collector resource processor or service.telemetry.resource"
                        f" block. Per the telemetry standard, every signal must carry"
                        f" service, version, ring, and side labels."
                    ),
                    evidence_locator=ref.locator,
                    collector_name=ref.collector_name,
                    collector_version=ref.collector_version,
                    confidence=0.85,
                    pattern_tag="patch-telem-labels",
                )
            ],
        )


class SyntheticTransactionConfigRule:
    """PATCH-TELEM-003: detect synthetic transaction configuration."""

    id = "PATCH-TELEM-003"
    band: Band = 2
    required_collectors: list[str] = ["telemetry-config"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        telem = _telemetry_evidence(evidence)
        if not telem:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no telemetry-config collector evidence available",
            )

        synths = _synthetic_evidence(telem)
        pipelines = _pipeline_evidence(telem)
        has_otel = len(pipelines) > 0

        if synths:
            total_targets = sum(len(s.payload.targets) for s in synths)
            tools = sorted({s.payload.tool for s in synths})
            ref = synths[0]

            if total_targets > 0:
                return RuleResult(
                    rule_id=self.id,
                    findings=[
                        make_green_finding(
                            self.id,
                            "patch-telem-synthetic",
                            ref,
                            summary=(
                                f"Synthetic transaction config found:"
                                f" {len(synths)} definition(s) via {', '.join(tools)}"
                                f" targeting {total_targets} endpoint(s)"
                            ),
                            recommendation=(
                                "No action required — synthetic transaction"
                                " configuration is present."
                            ),
                            confidence=0.90,
                            evidence_locator=ref.locator,
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
                            f"Synthetic test definition(s) found via {', '.join(tools)}"
                            f" but no target endpoints configured"
                        ),
                        recommendation=(
                            "Add target endpoints to the synthetic test configuration"
                            " to exercise critical user journeys."
                        ),
                        evidence_locator=ref.locator,
                        collector_name=ref.collector_name,
                        collector_version=ref.collector_version,
                        confidence=0.80,
                        pattern_tag="patch-telem-synthetic",
                    )
                ],
            )

        if has_otel:
            ref = pipelines[0]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            "OTel collector config present but no synthetic"
                            " transaction configuration detected"
                        ),
                        recommendation=(
                            "Add synthetic transaction tests (e.g. Grafana Synthetic"
                            " Monitoring, Datadog Synthetics, or Checkly) that exercise"
                            " critical user journeys in every ring including production."
                        ),
                        evidence_locator=ref.locator,
                        collector_name=ref.collector_name,
                        collector_version=ref.collector_version,
                        confidence=0.80,
                        pattern_tag="patch-telem-synthetic",
                    )
                ],
            )

        summaries = _summary_evidence(telem)
        ev = summaries[0] if summaries else telem[0]
        return RuleResult(
            rule_id=self.id,
            findings=[
                make_green_finding(
                    self.id,
                    "patch-telem-synthetic",
                    ev,
                    summary=(
                        "No telemetry configuration detected"
                        " — synthetic transaction check not applicable"
                    ),
                    recommendation=(
                        "If this service participates in a ringed patching programme,"
                        " add synthetic transaction tests exercising critical user journeys."
                    ),
                    confidence=0.70,
                    evidence_locator=ev.locator,
                )
            ],
        )


def _register() -> None:
    for rule_cls in (
        GoldenSignalEmissionRule,
        MandatoryLabelPresenceRule,
        SyntheticTransactionConfigRule,
    ):
        rule = rule_cls()
        if rule.id not in rule_registry:
            rule_registry.register(rule.id, rule)


_register()

__all__ = [
    "GoldenSignalEmissionRule",
    "MandatoryLabelPresenceRule",
    "SyntheticTransactionConfigRule",
]
