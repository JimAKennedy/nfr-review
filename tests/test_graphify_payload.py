# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for Graphify payload models."""

from __future__ import annotations

import pytest

from nfr_review.collectors.payloads.graphify import (
    CommunityStats,
    GodNodeEntry,
    GraphEdge,
    GraphifyPayload,
    GraphNode,
)


class TestGraphNode:
    def test_parse_minimal(self) -> None:
        node = GraphNode(
            id="fn_main",
            label="main()",
            file_type="code",
            source_file="src/main.py",
        )
        assert node.id == "fn_main"
        assert node.community is None

    def test_parse_with_community(self) -> None:
        node = GraphNode(
            id="cls_engine",
            label="Engine",
            file_type="code",
            source_file="src/engine.py",
            community=3,
            community_name="Core Engine",
        )
        assert node.community == 3
        assert node.community_name == "Core Engine"

    def test_extra_fields_ignored(self) -> None:
        node = GraphNode(
            id="n1",
            label="N1",
            file_type="code",
            source_file="a.py",
            _origin="ast",
            norm_label="n1",
        )
        assert node.id == "n1"

    def test_frozen(self) -> None:
        node = GraphNode(id="n1", label="N", file_type="code", source_file="a.py")
        with pytest.raises(ValueError):
            node.id = "changed"  # type: ignore[misc]


class TestGraphEdge:
    def test_parse_minimal(self) -> None:
        edge = GraphEdge(
            source="a",
            target="b",
            relation="calls",
            source_file="src/a.py",
        )
        assert edge.confidence == "EXTRACTED"
        assert edge.weight == 1.0

    def test_parse_with_all_fields(self) -> None:
        edge = GraphEdge(
            source="a",
            target="b",
            relation="imports_from",
            confidence="INFERRED",
            confidence_score=0.5,
            context="dependency",
            source_file="src/a.py",
            source_location="L42",
            weight=0.5,
        )
        assert edge.confidence_score == 0.5


class TestGraphifyPayload:
    def test_accepts_links_key(self) -> None:
        payload = GraphifyPayload.model_validate(
            {
                "node_count": 2,
                "edge_count": 1,
                "community_count": 1,
                "median_degree": 1.0,
                "god_node_threshold": 2,
                "cross_community_ratio": 0.0,
                "nodes": [
                    {"id": "a", "label": "A", "file_type": "code", "source_file": "a.py"},
                    {"id": "b", "label": "B", "file_type": "code", "source_file": "b.py"},
                ],
                "links": [
                    {
                        "source": "a",
                        "target": "b",
                        "relation": "calls",
                        "source_file": "a.py",
                    }
                ],
            }
        )
        assert len(payload.edges) == 1
        assert payload.edge_count == 1

    def test_accepts_edges_key(self) -> None:
        payload = GraphifyPayload.model_validate(
            {
                "node_count": 1,
                "edge_count": 0,
                "community_count": 0,
                "median_degree": 0.0,
                "god_node_threshold": 1,
                "cross_community_ratio": 0.0,
                "edges": [],
            }
        )
        assert payload.edges == []

    def test_frozen(self) -> None:
        payload = GraphifyPayload(
            node_count=0,
            edge_count=0,
            community_count=0,
            median_degree=0.0,
            god_node_threshold=1,
            cross_community_ratio=0.0,
        )
        with pytest.raises(ValueError):
            payload.node_count = 99  # type: ignore[misc]

    def test_god_nodes_list(self) -> None:
        gn = GodNodeEntry(
            node_id="big",
            label="BigClass",
            source_file="src/big.py",
            in_degree=50,
            out_degree=40,
            total_degree=90,
            community=1,
        )
        payload = GraphifyPayload(
            node_count=100,
            edge_count=200,
            community_count=5,
            median_degree=4.0,
            god_node_threshold=8,
            cross_community_ratio=0.2,
            god_nodes=[gn],
        )
        assert len(payload.god_nodes) == 1
        assert payload.god_nodes[0].total_degree == 90

    def test_community_stats(self) -> None:
        cs = CommunityStats(
            community_id=0,
            community_name="Core",
            node_count=10,
            internal_edges=30,
            cross_boundary_edges=10,
            cross_boundary_ratio=0.25,
        )
        assert cs.cross_boundary_ratio == 0.25
