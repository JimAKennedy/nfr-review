# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: structure-god-node — flags nodes with total degree > 2x median."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_MAX_FINDINGS = 10


class StructureGodNodeRule:
    """Flag nodes whose total degree far exceeds the median (coupling hotspots)."""

    id = "structure-god-node"
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
        god_nodes = ev.payload.get("god_nodes", [])
        threshold = ev.payload.get("god_node_threshold", 0)

        findings: list[Finding] = []
        for gn in god_nodes[:_MAX_FINDINGS]:
            label = gn.get("label", gn.get("node_id", "?"))
            degree = gn.get("total_degree", 0)
            src_file = gn.get("source_file", "unknown")
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="medium",
                    summary=(
                        f"'{label}' has total degree {degree} "
                        f"(threshold {threshold}) — coupling hotspot."
                    ),
                    recommendation=(
                        f"Consider breaking '{label}' into smaller "
                        f"units or introducing a facade to reduce "
                        f"direct coupling."
                    ),
                    evidence_locator=src_file,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.8,
                    pattern_tag="structure-god-node",
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


def _register() -> None:
    if "structure-god-node" not in rule_registry:
        rule_registry.register("structure-god-node", StructureGodNodeRule())


_register()

__all__ = ["StructureGodNodeRule"]
