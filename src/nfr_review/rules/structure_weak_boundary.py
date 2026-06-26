# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: structure-weak-boundary — flags communities with leaky boundaries."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.graphify import GraphifyPayload
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding
from nfr_review.rules.rule_helpers import make_green_finding

_CROSS_BOUNDARY_THRESHOLD = 0.40
_MIN_EDGES_FOR_SIGNAL = 5
_MAX_FINDINGS = 10


class StructureWeakBoundaryRule(FieldRule[GraphifyPayload]):
    """Flag communities where cross-boundary edges exceed 40% of total."""

    id = "structure-weak-boundary"
    collector_name = "graphify"
    evidence_kind = "graphify-analysis"
    payload_type = GraphifyPayload
    pattern_tag = "structure-weak-boundary"
    required_tech: list[str] = []
    default_confidence = 0.75
    all_clear_summary = (
        "All communities have strong boundaries — "
        "cross-boundary edge ratio is within threshold."
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
        stats = payload.community_stats

        findings: list[Finding] = []
        for cs in stats:
            total = cs.internal_edges + cs.cross_boundary_edges
            if total < _MIN_EDGES_FOR_SIGNAL:
                continue
            if cs.cross_boundary_ratio <= _CROSS_BOUNDARY_THRESHOLD:
                continue

            cname = cs.community_name or f"Community {cs.community_id}"
            pct = round(cs.cross_boundary_ratio * 100, 1)
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
                            f"'{cname}' has {pct}% cross-boundary edges "
                            f"({cs.cross_boundary_edges}/{total}) — weak module boundary."
                        ),
                        recommendation=(
                            f"Review the cross-boundary dependencies of "
                            f"'{cname}' and consider extracting a clearer "
                            f"interface or merging tightly-coupled clusters."
                        ),
                        locator=f"community:{cs.community_id}",
                        confidence=0.75,
                    ),
                )
            )

        findings.sort(key=lambda f: f.summary, reverse=True)
        findings = findings[:_MAX_FINDINGS]

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "structure-weak-boundary",
                    ev,
                    summary=(
                        "All communities have strong boundaries — "
                        "cross-boundary edge ratio is within threshold."
                    ),
                    confidence=0.75,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


__all__ = ["StructureWeakBoundaryRule"]
