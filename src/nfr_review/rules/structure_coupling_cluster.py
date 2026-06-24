# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: structure-coupling-cluster — flags community pairs with
disproportionate inter-community coupling.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.framework import register
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_COUPLING_RELATIONS = frozenset({"calls", "imports_from", "imports", "uses"})
_MIN_COUPLING_EDGES = 10
_MAX_FINDINGS = 10


@register
class StructureCouplingClusterRule:
    """Flag community pairs with disproportionate coupling edges."""

    id = "structure-coupling-cluster"
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
        nodes = ev.payload.get("nodes", [])
        edges = ev.payload.get("edges", [])

        node_community: dict[str, int] = {}
        for n in nodes:
            comm = n.get("community")
            if comm is not None:
                node_community[n.get("id", "")] = comm

        community_names: dict[int, str] = {}
        for n in nodes:
            comm = n.get("community")
            cname = n.get("community_name")
            if comm is not None and cname and comm not in community_names:
                community_names[comm] = cname

        pair_counts: Counter[tuple[int, int]] = Counter()
        pair_relations: dict[tuple[int, int], Counter[str]] = {}

        for e in edges:
            rel = e.get("relation", "")
            if rel not in _COUPLING_RELATIONS:
                continue
            src_comm = node_community.get(e.get("source", ""))
            tgt_comm = node_community.get(e.get("target", ""))
            if src_comm is None or tgt_comm is None:
                continue
            if src_comm == tgt_comm:
                continue
            pair = (min(src_comm, tgt_comm), max(src_comm, tgt_comm))
            pair_counts[pair] += 1
            if pair not in pair_relations:
                pair_relations[pair] = Counter()
            pair_relations[pair][rel] += 1

        findings: list[Finding] = []
        for pair, count in pair_counts.most_common(_MAX_FINDINGS):
            if count < _MIN_COUPLING_EDGES:
                break
            c1, c2 = pair
            n1 = community_names.get(c1, f"Community {c1}")
            n2 = community_names.get(c2, f"Community {c2}")
            rels = pair_relations[pair]
            top_rel = rels.most_common(1)[0][0] if rels else "unknown"
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="amber",
                    severity="low",
                    summary=(
                        f"'{n1}' ↔ '{n2}' have {count} coupling edges (dominant: {top_rel})."
                    ),
                    recommendation=(
                        f"Consider introducing an interface or "
                        f"shared abstraction between '{n1}' and "
                        f"'{n2}' to reduce direct coupling."
                    ),
                    evidence_locator=f"community-pair:{c1}-{c2}",
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.7,
                    pattern_tag="structure-coupling-cluster",
                )
            )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "structure-coupling-cluster",
                    ev,
                    summary=("No disproportionate inter-community coupling detected."),
                    confidence=0.7,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


__all__ = ["StructureCouplingClusterRule"]
