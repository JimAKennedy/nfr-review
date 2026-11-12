# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the in-process graph query client."""

from __future__ import annotations

import pytest

from nfr_review.collectors.payloads.graphify import (
    GraphEdge,
    GraphifyPayload,
    GraphNode,
)
from nfr_review.graph_query import GraphQueryClient


def _make_node(nid: str, label: str, community: int | None = None) -> GraphNode:
    return GraphNode(
        id=nid,
        label=label,
        file_type="code",
        source_file=f"src/{nid}.py",
        community=community,
        community_name=f"Community {community}" if community is not None else None,
    )


def _make_edge(src: str, tgt: str, relation: str = "calls") -> GraphEdge:
    return GraphEdge(
        source=src,
        target=tgt,
        relation=relation,
        confidence="EXTRACTED",
        confidence_score=1.0,
        source_file=f"src/{src}.py",
        weight=1.0,
    )


@pytest.fixture()
def small_payload() -> GraphifyPayload:
    """A small graph with 5 nodes, 2 communities, 8 edges."""
    nodes = [
        _make_node("engine", "Engine", community=0),
        _make_node("config", "Config", community=0),
        _make_node("runner", "Runner", community=0),
        _make_node("report", "Report", community=1),
        _make_node("export", "Export", community=1),
    ]
    edges = [
        _make_edge("engine", "config", "uses"),
        _make_edge("engine", "runner", "calls"),
        _make_edge("runner", "report", "calls"),
        _make_edge("report", "export", "calls"),
        _make_edge("config", "runner", "uses"),
        _make_edge("export", "report", "references"),
        _make_edge("engine", "report", "uses"),
        _make_edge("runner", "config", "references"),
    ]
    return GraphifyPayload(
        node_count=5,
        edge_count=8,
        community_count=2,
        median_degree=3.0,
        god_node_threshold=6,
        cross_community_ratio=0.25,
        god_nodes=[],
        community_stats=[],
        nodes=nodes,
        edges=edges,
    )


@pytest.fixture()
def client(small_payload: GraphifyPayload) -> GraphQueryClient:
    return GraphQueryClient(small_payload)


class TestShortestPath:
    def test_direct_connection(self, client: GraphQueryClient) -> None:
        result = client.shortest_path("Engine", "Config")
        assert result is not None
        assert result.hop_count == 1
        assert result.source == "Engine"
        assert result.target == "Config"
        assert result.edge_relations == ["uses"]

    def test_multi_hop(self, client: GraphQueryClient) -> None:
        result = client.shortest_path("Config", "Export")
        assert result is not None
        assert result.hop_count >= 2
        assert result.path[0] == "Config"
        assert result.path[-1] == "Export"

    def test_missing_node_returns_none(self, client: GraphQueryClient) -> None:
        assert client.shortest_path("Engine", "NonExistent") is None

    def test_case_insensitive_lookup(self, client: GraphQueryClient) -> None:
        result = client.shortest_path("engine", "config")
        assert result is not None
        assert result.hop_count == 1

    def test_substring_match(self, client: GraphQueryClient) -> None:
        result = client.shortest_path("Eng", "Rep")
        assert result is not None


class TestBlastRadius:
    def test_single_hop(self, client: GraphQueryClient) -> None:
        result = client.blast_radius("Engine", max_hops=1)
        assert result is not None
        assert result.origin == "Engine"
        assert result.reachable_count >= 2

    def test_full_radius(self, client: GraphQueryClient) -> None:
        result = client.blast_radius("Engine", max_hops=10)
        assert result is not None
        assert result.reachable_count == 4  # all other nodes

    def test_missing_node(self, client: GraphQueryClient) -> None:
        assert client.blast_radius("NonExistent") is None

    def test_hops_breakdown(self, client: GraphQueryClient) -> None:
        result = client.blast_radius("Engine", max_hops=2)
        assert result is not None
        assert 1 in result.by_hop


class TestGetNeighbors:
    def test_all_neighbors(self, client: GraphQueryClient) -> None:
        neighbors = client.get_neighbors("Engine")
        assert len(neighbors) >= 3
        labels = {n.label for n in neighbors}
        assert "Config" in labels
        assert "Runner" in labels

    def test_relation_filter(self, client: GraphQueryClient) -> None:
        neighbors = client.get_neighbors("Engine", relation_filter="calls")
        for n in neighbors:
            assert n.relation == "calls"

    def test_missing_node_empty_list(self, client: GraphQueryClient) -> None:
        assert client.get_neighbors("NonExistent") == []

    def test_direction_field(self, client: GraphQueryClient) -> None:
        neighbors = client.get_neighbors("Runner")
        directions = {n.direction for n in neighbors}
        assert "outgoing" in directions
        assert "incoming" in directions


class TestCommunityMembers:
    def test_community_zero(self, client: GraphQueryClient) -> None:
        result = client.community_members(0)
        assert result is not None
        assert result.community_id == 0
        assert len(result.members) == 3
        assert "Engine" in result.member_labels

    def test_community_one(self, client: GraphQueryClient) -> None:
        result = client.community_members(1)
        assert result is not None
        assert len(result.members) == 2
        assert "Report" in result.member_labels

    def test_nonexistent_community(self, client: GraphQueryClient) -> None:
        assert client.community_members(99) is None


class TestCouplingBetween:
    def test_cross_community_edges(self, client: GraphQueryClient) -> None:
        result = client.coupling_between(0, 1)
        assert result.edge_count >= 2
        assert "calls" in result.relations

    def test_same_community(self, client: GraphQueryClient) -> None:
        result = client.coupling_between(0, 0)
        assert result.edge_count == 0

    def test_nonexistent_communities(self, client: GraphQueryClient) -> None:
        result = client.coupling_between(88, 99)
        assert result.edge_count == 0


class TestStats:
    def test_basic_stats(self, client: GraphQueryClient) -> None:
        s = client.stats()
        assert s.node_count == 5
        assert s.edge_count == 8
        assert s.community_count == 2
        assert s.density > 0
        assert s.avg_degree > 0


class TestGodNodes:
    def test_returns_sorted_by_degree(self, client: GraphQueryClient) -> None:
        gods = client.god_nodes(top_n=3)
        assert len(gods) == 3
        assert gods[0]["total_degree"] >= gods[1]["total_degree"]

    def test_top_n_limit(self, client: GraphQueryClient) -> None:
        gods = client.god_nodes(top_n=1)
        assert len(gods) == 1


class TestDisconnectedGraph:
    def test_no_path_between_disconnected(self) -> None:
        nodes = [
            _make_node("a", "Alpha", community=0),
            _make_node("b", "Beta", community=1),
        ]
        payload = GraphifyPayload(
            node_count=2,
            edge_count=0,
            community_count=2,
            median_degree=0.0,
            god_node_threshold=1,
            cross_community_ratio=0.0,
            nodes=nodes,
            edges=[],
        )
        c = GraphQueryClient(payload)
        assert c.shortest_path("Alpha", "Beta") is None

    def test_blast_radius_isolated(self) -> None:
        nodes = [_make_node("alone", "Alone", community=0)]
        payload = GraphifyPayload(
            node_count=1,
            edge_count=0,
            community_count=1,
            median_degree=0.0,
            god_node_threshold=1,
            cross_community_ratio=0.0,
            nodes=nodes,
            edges=[],
        )
        c = GraphQueryClient(payload)
        result = c.blast_radius("Alone", max_hops=3)
        assert result is not None
        assert result.reachable_count == 0


class TestEmptyGraph:
    def test_stats_on_empty(self) -> None:
        payload = GraphifyPayload(
            node_count=0,
            edge_count=0,
            community_count=0,
            median_degree=0.0,
            god_node_threshold=1,
            cross_community_ratio=0.0,
            nodes=[],
            edges=[],
        )
        c = GraphQueryClient(payload)
        s = c.stats()
        assert s.node_count == 0
        assert s.density == 0.0
