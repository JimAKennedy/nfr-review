# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: structure-coupling-cluster — flags community pairs with
disproportionate inter-community coupling.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from nfr_review.collectors.payloads.graphify import GraphifyPayload
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding
from nfr_review.rules.rule_helpers import make_green_finding

_COUPLING_RELATIONS = frozenset({"calls", "imports_from", "imports", "uses"})
_MIN_COUPLING_EDGES = 10
_MAX_FINDINGS = 10


class StructureCouplingClusterRule(FieldRule[GraphifyPayload]):
    """Flag community pairs with disproportionate coupling edges."""

    id = "structure-coupling-cluster"
    collector_name = "graphify"
    evidence_kind = "graphify-analysis"
    payload_type = GraphifyPayload
    pattern_tag = "structure-coupling-cluster"
    required_tech: list[str] = []
    default_confidence = 0.7
    all_clear_summary = "No disproportionate inter-community coupling detected."

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
        nodes = payload.nodes
        edges = payload.edges

        node_community: dict[str, int] = {}
        for n in nodes:
            if n.community is not None:
                node_community[n.id] = n.community

        community_names: dict[int, str] = {}
        for n in nodes:
            if (
                n.community is not None
                and n.community_name
                and n.community not in community_names
            ):
                community_names[n.community] = n.community_name

        pair_counts: Counter[tuple[int, int]] = Counter()
        pair_relations: dict[tuple[int, int], Counter[str]] = {}

        for e in edges:
            rel = e.relation
            if rel not in _COUPLING_RELATIONS:
                continue
            src_comm = node_community.get(e.source)
            tgt_comm = node_community.get(e.target)
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
                make_finding(
                    rule_id=self.id,
                    ev=ev,
                    pattern_tag=self.pattern_tag,
                    default_confidence=self.default_confidence,
                    hit=Hit(
                        rag="amber",
                        severity="low",
                        summary=(
                            f"'{n1}' ↔ '{n2}' have {count} coupling edges "
                            f"(dominant: {top_rel})."
                        ),
                        recommendation=(
                            f"Consider introducing an interface or "
                            f"shared abstraction between '{n1}' and "
                            f"'{n2}' to reduce direct coupling."
                        ),
                        locator=f"community-pair:{c1}-{c2}",
                        confidence=0.7,
                    ),
                )
            )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "structure-coupling-cluster",
                    ev,
                    summary="No disproportionate inter-community coupling detected.",
                    confidence=0.7,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


__all__ = ["StructureCouplingClusterRule"]
