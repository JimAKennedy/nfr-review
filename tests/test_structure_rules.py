# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for structural rules (god-node, weak-boundary, coupling-cluster)."""

from __future__ import annotations

from nfr_review.collectors.payloads.graphify import (
    CommunityStats,
    GodNodeEntry,
    GraphEdge,
    GraphifyPayload,
    GraphNode,
)
from nfr_review.models import Evidence
from nfr_review.rules.structure_coupling_cluster import StructureCouplingClusterRule
from nfr_review.rules.structure_god_node import StructureGodNodeRule
from nfr_review.rules.structure_weak_boundary import StructureWeakBoundaryRule


def _make_evidence(payload: GraphifyPayload) -> list[Evidence]:
    return [
        Evidence(
            collector_name="graphify",
            collector_version="0.1.0",
            locator=".",
            kind="graphify-analysis",
            payload=payload,
        )
    ]


def _clean_payload() -> GraphifyPayload:
    return GraphifyPayload(
        node_count=10,
        edge_count=15,
        community_count=2,
        median_degree=3.0,
        god_node_threshold=6,
        cross_community_ratio=0.05,
        god_nodes=[],
        community_stats=[
            CommunityStats(
                community_id=0,
                community_name="Core",
                node_count=5,
                internal_edges=10,
                cross_boundary_edges=1,
                cross_boundary_ratio=0.09,
            ),
            CommunityStats(
                community_id=1,
                community_name="Utils",
                node_count=5,
                internal_edges=8,
                cross_boundary_edges=1,
                cross_boundary_ratio=0.11,
            ),
        ],
    )


class TestStructureGodNodeRule:
    def test_fires_on_god_nodes(self) -> None:
        payload = GraphifyPayload(
            node_count=20,
            edge_count=50,
            community_count=3,
            median_degree=5.0,
            god_node_threshold=10,
            cross_community_ratio=0.2,
            god_nodes=[
                GodNodeEntry(
                    node_id="big_engine",
                    label="BigEngine",
                    source_file="src/engine.py",
                    in_degree=30,
                    out_degree=25,
                    total_degree=55,
                    community=0,
                ),
            ],
        )
        rule = StructureGodNodeRule()
        result = rule.evaluate(_make_evidence(payload), None)
        assert not result.skipped
        findings = [f for f in result.findings if f.rag != "green"]
        assert len(findings) == 1
        assert "BigEngine" in findings[0].summary
        assert findings[0].severity == "medium"

    def test_green_when_no_god_nodes(self) -> None:
        rule = StructureGodNodeRule()
        result = rule.evaluate(_make_evidence(_clean_payload()), None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skips_without_evidence(self) -> None:
        rule = StructureGodNodeRule()
        result = rule.evaluate([], None)
        assert result.skipped


class TestStructureWeakBoundaryRule:
    def test_fires_on_weak_boundary(self) -> None:
        payload = GraphifyPayload(
            node_count=20,
            edge_count=50,
            community_count=2,
            median_degree=5.0,
            god_node_threshold=10,
            cross_community_ratio=0.5,
            community_stats=[
                CommunityStats(
                    community_id=0,
                    community_name="Leaky Module",
                    node_count=10,
                    internal_edges=6,
                    cross_boundary_edges=8,
                    cross_boundary_ratio=0.57,
                ),
            ],
        )
        rule = StructureWeakBoundaryRule()
        result = rule.evaluate(_make_evidence(payload), None)
        findings = [f for f in result.findings if f.rag != "green"]
        assert len(findings) == 1
        assert "Leaky Module" in findings[0].summary
        assert "57.0%" in findings[0].summary

    def test_ignores_small_communities(self) -> None:
        payload = GraphifyPayload(
            node_count=5,
            edge_count=3,
            community_count=1,
            median_degree=1.0,
            god_node_threshold=2,
            cross_community_ratio=0.8,
            community_stats=[
                CommunityStats(
                    community_id=0,
                    node_count=3,
                    internal_edges=1,
                    cross_boundary_edges=2,
                    cross_boundary_ratio=0.67,
                ),
            ],
        )
        rule = StructureWeakBoundaryRule()
        result = rule.evaluate(_make_evidence(payload), None)
        assert result.findings[0].rag == "green"

    def test_green_when_strong_boundaries(self) -> None:
        rule = StructureWeakBoundaryRule()
        result = rule.evaluate(_make_evidence(_clean_payload()), None)
        assert result.findings[0].rag == "green"

    def test_skips_without_evidence(self) -> None:
        rule = StructureWeakBoundaryRule()
        result = rule.evaluate([], None)
        assert result.skipped


class TestStructureCouplingClusterRule:
    def test_fires_on_coupled_communities(self) -> None:
        nodes = [
            GraphNode(
                id=f"n{i}",
                label=f"N{i}",
                file_type="code",
                source_file=f"n{i}.py",
                community=0 if i < 5 else 1,
            )
            for i in range(10)
        ]
        edges = [
            GraphEdge(
                source=f"n{i}",
                target=f"n{5 + (i % 5)}",
                relation="calls",
                source_file=f"n{i}.py",
            )
            for i in range(5)
        ] * 3  # 15 cross-community call edges

        payload = GraphifyPayload(
            node_count=10,
            edge_count=15,
            community_count=2,
            median_degree=3.0,
            god_node_threshold=6,
            cross_community_ratio=1.0,
            nodes=nodes,
            edges=edges,
        )
        rule = StructureCouplingClusterRule()
        result = rule.evaluate(_make_evidence(payload), None)
        findings = [f for f in result.findings if f.rag != "green"]
        assert len(findings) >= 1
        assert findings[0].severity == "low"

    def test_green_when_low_coupling(self) -> None:
        nodes = [
            GraphNode(
                id=f"n{i}",
                label=f"N{i}",
                file_type="code",
                source_file=f"n{i}.py",
                community=0,
            )
            for i in range(5)
        ]
        edges = [
            GraphEdge(
                source="n0",
                target="n1",
                relation="calls",
                source_file="n0.py",
            )
        ]
        payload = GraphifyPayload(
            node_count=5,
            edge_count=1,
            community_count=1,
            median_degree=0.4,
            god_node_threshold=1,
            cross_community_ratio=0.0,
            nodes=nodes,
            edges=edges,
        )
        rule = StructureCouplingClusterRule()
        result = rule.evaluate(_make_evidence(payload), None)
        assert result.findings[0].rag == "green"

    def test_skips_without_evidence(self) -> None:
        rule = StructureCouplingClusterRule()
        result = rule.evaluate([], None)
        assert result.skipped
