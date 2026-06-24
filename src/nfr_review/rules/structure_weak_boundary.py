# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: structure-weak-boundary — flags communities with leaky boundaries."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.framework import register
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_CROSS_BOUNDARY_THRESHOLD = 0.40
_MIN_EDGES_FOR_SIGNAL = 5
_MAX_FINDINGS = 10


@register
class StructureWeakBoundaryRule:
    """Flag communities where cross-boundary edges exceed 40% of total."""

    id = "structure-weak-boundary"
    band: Band = 1
    required_collectors: list[str] = ["graphify"]
    required_tech: list[str] = []

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        gf_evidence = filter_evidence(evidence, "graphify", "graphify-analysis")
        if not gf_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no graphify-analysis evidence available",
            )

        ev = gf_evidence[0]
        stats = ev.payload.get("community_stats", [])

        findings: list[Finding] = []
        for cs in stats:
            internal = cs.get("internal_edges", 0)
            cross = cs.get("cross_boundary_edges", 0)
            total = internal + cross
            if total < _MIN_EDGES_FOR_SIGNAL:
                continue
            ratio = cs.get("cross_boundary_ratio", 0.0)
            if ratio <= _CROSS_BOUNDARY_THRESHOLD:
                continue

            cid = cs.get("community_id", "?")
            cname = cs.get("community_name") or f"Community {cid}"
            pct = round(ratio * 100, 1)
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"'{cname}' has {pct}% cross-boundary edges "
                        f"({cross}/{total}) — weak module boundary."
                    ),
                    recommendation=(
                        f"Review the cross-boundary dependencies of "
                        f"'{cname}' and consider extracting a clearer "
                        f"interface or merging tightly-coupled clusters."
                    ),
                    evidence_locator=f"community:{cid}",
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.75,
                    pattern_tag="structure-weak-boundary",
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
