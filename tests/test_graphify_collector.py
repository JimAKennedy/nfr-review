# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the Graphify collector."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from nfr_review.collectors.graphify import GraphifyCollector, _compute_metrics
from nfr_review.collectors.payloads.graphify import GraphEdge, GraphNode


def _make_graph_json(
    nodes: list[dict],
    edges: list[dict],
) -> dict:
    return {
        "directed": False,
        "multigraph": False,
        "graph": {},
        "nodes": nodes,
        "links": edges,
    }


def _simple_nodes() -> list[dict]:
    return [
        {"id": "a", "label": "A", "file_type": "code", "source_file": "a.py", "community": 0},
        {"id": "b", "label": "B", "file_type": "code", "source_file": "b.py", "community": 0},
        {"id": "c", "label": "C", "file_type": "code", "source_file": "c.py", "community": 1},
        {"id": "d", "label": "D", "file_type": "code", "source_file": "d.py", "community": 1},
        {
            "id": "hub",
            "label": "Hub",
            "file_type": "code",
            "source_file": "hub.py",
            "community": 0,
        },
    ]


def _simple_edges() -> list[dict]:
    return [
        {"source": "hub", "target": "a", "relation": "calls", "source_file": "hub.py"},
        {"source": "hub", "target": "b", "relation": "calls", "source_file": "hub.py"},
        {"source": "hub", "target": "c", "relation": "calls", "source_file": "hub.py"},
        {"source": "hub", "target": "d", "relation": "calls", "source_file": "hub.py"},
        {"source": "a", "target": "hub", "relation": "uses", "source_file": "a.py"},
        {"source": "b", "target": "hub", "relation": "uses", "source_file": "b.py"},
        {"source": "c", "target": "hub", "relation": "uses", "source_file": "c.py"},
        {"source": "d", "target": "hub", "relation": "uses", "source_file": "d.py"},
        {"source": "a", "target": "b", "relation": "calls", "source_file": "a.py"},
    ]


class TestComputeMetrics:
    def test_god_node_detection(self) -> None:
        nodes = [GraphNode.model_validate(n) for n in _simple_nodes()]
        edges = [GraphEdge.model_validate(e) for e in _simple_edges()]

        god_nodes, _, _, median_deg, threshold = _compute_metrics(nodes, edges)

        assert len(god_nodes) >= 1
        assert god_nodes[0].label == "Hub"
        assert god_nodes[0].total_degree == 8

    def test_cross_community_ratio(self) -> None:
        nodes = [GraphNode.model_validate(n) for n in _simple_nodes()]
        edges = [GraphEdge.model_validate(e) for e in _simple_edges()]

        _, community_stats, cross_ratio, _, _ = _compute_metrics(nodes, edges)

        assert cross_ratio > 0
        assert len(community_stats) == 2

    def test_empty_graph(self) -> None:
        god_nodes, stats, cross_ratio, median_deg, threshold = _compute_metrics([], [])
        assert god_nodes == []
        assert stats == []
        assert cross_ratio == 0.0
        assert threshold >= 1


class TestGraphifyCollector:
    def test_skips_when_not_installed(self, tmp_path: Path) -> None:
        collector = GraphifyCollector()
        with patch("nfr_review.collectors.graphify.shutil.which", return_value=None):
            result = collector.collect(tmp_path, None)
        assert result == []

    def test_collects_from_existing_graph_json(self, tmp_path: Path) -> None:
        collector = GraphifyCollector()
        graphify_out = tmp_path / "graphify-out"
        graphify_out.mkdir()

        graph_data = _make_graph_json(_simple_nodes(), _simple_edges())
        (graphify_out / "graph.json").write_text(json.dumps(graph_data))

        with patch(
            "nfr_review.collectors.graphify.shutil.which", return_value="/usr/bin/graphify"
        ):
            result = collector.collect(tmp_path, None)

        assert len(result) == 1
        ev = result[0]
        assert ev.collector_name == "graphify"
        assert ev.kind == "graphify-analysis"
        assert ev.payload.node_count == 5
        assert ev.payload.edge_count == 9
        assert len(ev.payload.god_nodes) >= 1

    def test_returns_empty_on_bad_json(self, tmp_path: Path) -> None:
        collector = GraphifyCollector()
        graphify_out = tmp_path / "graphify-out"
        graphify_out.mkdir()
        (graphify_out / "graph.json").write_text("not json at all")

        with patch(
            "nfr_review.collectors.graphify.shutil.which", return_value="/usr/bin/graphify"
        ):
            result = collector.collect(tmp_path, None)
        assert result == []

    def test_handles_graph_without_communities(self, tmp_path: Path) -> None:
        collector = GraphifyCollector()
        graphify_out = tmp_path / "graphify-out"
        graphify_out.mkdir()

        nodes = [
            {"id": "x", "label": "X", "file_type": "code", "source_file": "x.py"},
            {"id": "y", "label": "Y", "file_type": "code", "source_file": "y.py"},
        ]
        edges = [
            {"source": "x", "target": "y", "relation": "calls", "source_file": "x.py"},
        ]
        graph_data = _make_graph_json(nodes, edges)
        (graphify_out / "graph.json").write_text(json.dumps(graph_data))

        with patch(
            "nfr_review.collectors.graphify.shutil.which", return_value="/usr/bin/graphify"
        ):
            result = collector.collect(tmp_path, None)

        assert len(result) == 1
        assert result[0].payload.community_count == 0
        assert result[0].payload.cross_community_ratio == 0.0
