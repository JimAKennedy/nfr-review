# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: structure-god-node — flags nodes with total degree > 2x median."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.graphify import GraphifyPayload
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding
from nfr_review.rules.rule_helpers import make_green_finding

_MAX_FINDINGS = 10


class StructureGodNodeRule(FieldRule[GraphifyPayload]):
    """Flag nodes whose total degree far exceeds the median (coupling hotspots)."""

    id = "structure-god-node"
    collector_name = "graphify"
    evidence_kind = "graphify-analysis"
    payload_type = GraphifyPayload
    pattern_tag = "structure-god-node"
    required_tech: list[str] = []
    default_confidence = 0.8
    all_clear_summary = (
        "No god nodes detected — all entities are within the coupling threshold."
    )

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
                skip_reason="no graphify-analysis evidence available",
            )

        ev = relevant[0]
        payload = self._coerce(ev.payload)
        god_nodes = payload.god_nodes
        threshold = payload.god_node_threshold

        findings: list[Finding] = []
        for gn in god_nodes[:_MAX_FINDINGS]:
            findings.append(
                make_finding(
                    rule_id=self.id,
                    ev=ev,
                    pattern_tag=self.pattern_tag,
                    default_confidence=self.default_confidence,
                    hit=Hit(
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"'{gn.label}' has total degree {gn.total_degree} "
                            f"(threshold {threshold}) — coupling hotspot."
                        ),
                        recommendation=(
                            f"Consider breaking '{gn.label}' into smaller "
                            f"units or introducing a facade to reduce "
                            f"direct coupling."
                        ),
                        locator=gn.source_file,
                        confidence=0.8,
                    ),
                )
            )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "structure-god-node",
                    ev,
                    summary=(
                        "No god nodes detected — all entities are "
                        "within the coupling threshold."
                    ),
                    confidence=0.8,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


__all__ = ["StructureGodNodeRule"]
