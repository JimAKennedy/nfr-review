# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Graphify collector — runs graphify CLI to extract a knowledge graph and
computes structural metrics (god nodes, community boundary stats).
"""

from __future__ import annotations

import json
import logging
import shutil
import statistics
import subprocess  # nosec B404 — args are hardcoded, not user input
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.graphify import (
    CommunityStats,
    GodNodeEntry,
    GraphEdge,
    GraphifyPayload,
    GraphNode,
)
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger(__name__)

_GOD_NODE_MULTIPLIER = 2


def _run_graphify(repo_path: Path) -> Path | None:
    """Run graphify update + cluster-only; return graph.json path or None."""
    graphify_out = repo_path / "graphify-out"
    graph_json = graphify_out / "graph.json"

    if graph_json.is_file():
        logger.info("Reusing existing graph.json at %s", graph_json)
        return graph_json

    try:
        subprocess.run(  # nosec B603 B607
            ["graphify", "update", str(repo_path), "--no-cluster"],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "graphify update failed (exit %d): %s", exc.returncode, exc.stderr[:500]
        )
        return None
    except subprocess.SubprocessError as exc:
        logger.warning("graphify update error: %s", exc)
        return None

    try:
        subprocess.run(  # nosec B603 B607
            ["graphify", "cluster-only", str(repo_path), "--no-viz", "--no-label"],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "graphify cluster-only failed (exit %d): %s", exc.returncode, exc.stderr[:500]
        )
    except subprocess.SubprocessError as exc:
        logger.warning("graphify cluster-only error: %s", exc)

    if not graph_json.is_file():
        logger.warning("graphify ran but graph.json not found at %s", graph_json)
        return None

    return graph_json


def _compute_metrics(
    nodes: list[GraphNode], edges: list[GraphEdge]
) -> tuple[list[GodNodeEntry], list[CommunityStats], float, float, int]:
    """Compute structural metrics from parsed graph data.

    Returns (god_nodes, community_stats, cross_community_ratio, median_degree, god_threshold).
    """
    in_degree: Counter[str] = Counter()
    out_degree: Counter[str] = Counter()
    for edge in edges:
        out_degree[edge.source] += 1
        in_degree[edge.target] += 1

    node_map = {n.id: n for n in nodes}
    total_degrees: dict[str, int] = {}
    for nid in node_map:
        total_degrees[nid] = in_degree.get(nid, 0) + out_degree.get(nid, 0)

    degree_values = list(total_degrees.values()) or [0]
    median_deg = statistics.median(degree_values)
    god_threshold = max(int(median_deg * _GOD_NODE_MULTIPLIER), 1)

    god_nodes: list[GodNodeEntry] = []
    for nid, deg in sorted(total_degrees.items(), key=lambda x: -x[1]):
        if deg <= god_threshold:
            break
        n = node_map[nid]
        god_nodes.append(
            GodNodeEntry(
                node_id=n.id,
                label=n.label,
                source_file=n.source_file,
                in_degree=in_degree.get(nid, 0),
                out_degree=out_degree.get(nid, 0),
                total_degree=deg,
                community=n.community,
            )
        )

    community_internal: Counter[int] = Counter()
    community_cross: Counter[int] = Counter()
    total_cross = 0

    for edge in edges:
        src_node = node_map.get(edge.source)
        tgt_node = node_map.get(edge.target)
        if src_node is None or tgt_node is None:
            continue
        src_comm = src_node.community
        tgt_comm = tgt_node.community
        if src_comm is None or tgt_comm is None:
            continue
        if src_comm == tgt_comm:
            community_internal[src_comm] += 1
        else:
            community_cross[src_comm] += 1
            community_cross[tgt_comm] += 1
            total_cross += 1

    community_nodes: defaultdict[int, int] = defaultdict(int)
    community_names: dict[int, str | None] = {}
    for n in nodes:
        if n.community is not None:
            community_nodes[n.community] += 1
            if n.community not in community_names:
                community_names[n.community] = n.community_name

    community_stats: list[CommunityStats] = []
    for cid in sorted(community_nodes):
        internal = community_internal.get(cid, 0)
        cross = community_cross.get(cid, 0)
        total = internal + cross
        ratio = cross / total if total > 0 else 0.0
        community_stats.append(
            CommunityStats(
                community_id=cid,
                community_name=community_names.get(cid),
                node_count=community_nodes[cid],
                internal_edges=internal,
                cross_boundary_edges=cross,
                cross_boundary_ratio=round(ratio, 4),
            )
        )

    total_edges_with_communities = sum(community_internal.values()) + total_cross
    cross_ratio = (
        total_cross / total_edges_with_communities if total_edges_with_communities > 0 else 0.0
    )

    return god_nodes, community_stats, round(cross_ratio, 4), median_deg, god_threshold


class GraphifyCollector:
    """Runs graphify CLI and emits structural evidence."""

    name = "graphify"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        if not shutil.which("graphify"):
            logger.info("graphify not installed — skipping structural analysis")
            return []

        graph_json_path = _run_graphify(repo_path)
        if graph_json_path is None:
            return []

        try:
            raw = json.loads(graph_json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read graph.json: %s", exc)
            return []

        raw_nodes = raw.get("nodes", [])
        raw_edges = raw.get("links", raw.get("edges", []))

        nodes = [GraphNode.model_validate(n) for n in raw_nodes]
        edges = [GraphEdge.model_validate(e) for e in raw_edges]

        communities = {n.community for n in nodes if n.community is not None}

        god_nodes, community_stats, cross_ratio, median_deg, threshold = _compute_metrics(
            nodes, edges
        )

        payload = GraphifyPayload(
            node_count=len(nodes),
            edge_count=len(edges),
            community_count=len(communities),
            median_degree=round(median_deg, 2),
            god_node_threshold=threshold,
            cross_community_ratio=cross_ratio,
            god_nodes=god_nodes,
            community_stats=community_stats,
            nodes=nodes,
            edges=edges,
        )

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="graphify-analysis",
                payload=payload,
            )
        ]


def _register() -> None:
    if "graphify" not in collector_registry:
        collector_registry.register("graphify", GraphifyCollector())


_register()

__all__ = ["GraphifyCollector"]
