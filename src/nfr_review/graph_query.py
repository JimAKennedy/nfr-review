# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""In-process graph query client for Graphify structural analysis.

Operates on a :class:`GraphifyPayload` already loaded by the collector,
building a networkx DiGraph lazily on first query.  Mirrors the key query
capabilities of ``graphify serve`` without requiring MCP or a subprocess.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nfr_review.collectors.payloads.graphify import GraphifyPayload

try:
    import networkx as nx
except ImportError:
    nx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PathResult:
    """Shortest path between two nodes."""

    source: str
    target: str
    path: list[str]
    hop_count: int
    edge_relations: list[str]


@dataclass(frozen=True)
class NeighborEntry:
    """A direct neighbor of a queried node."""

    node_id: str
    label: str
    relation: str
    direction: str  # "outgoing" or "incoming"
    source_file: str


@dataclass(frozen=True)
class BlastRadiusResult:
    """Nodes reachable within N hops from a starting node."""

    origin: str
    max_hops: int
    reachable_count: int
    by_hop: dict[int, int]
    reachable_files: list[str]


@dataclass(frozen=True)
class CommunityDetail:
    """Members and metadata for a single community."""

    community_id: int
    community_name: str | None
    members: list[str]
    member_labels: list[str]


@dataclass(frozen=True)
class CouplingResult:
    """Cross-community coupling between two communities."""

    community_a: int
    community_b: int
    edge_count: int
    relations: dict[str, int]


@dataclass(frozen=True)
class GraphStats:
    """Summary statistics for the loaded graph."""

    node_count: int
    edge_count: int
    community_count: int
    density: float
    avg_degree: float


class GraphQueryClient:
    """Query a Graphify knowledge graph loaded from a :class:`GraphifyPayload`.

    The networkx graph is built lazily on the first query call.
    All methods return structured dataclasses — no raw networkx objects leak out.
    """

    def __init__(self, payload: GraphifyPayload) -> None:
        self._payload = payload
        self._graph: nx.DiGraph | None = None
        self._node_labels: dict[str, str] = {}
        self._node_files: dict[str, str] = {}
        self._node_communities: dict[str, int | None] = {}

    def _ensure_graph(self) -> nx.DiGraph:
        if self._graph is not None:
            return self._graph
        if nx is None:
            raise RuntimeError("networkx is required for graph queries; pip install networkx")

        g: nx.DiGraph = nx.DiGraph()
        for node in self._payload.nodes:
            g.add_node(
                node.id,
                label=node.label,
                file_type=node.file_type,
                source_file=node.source_file,
                community=node.community,
                community_name=node.community_name,
                norm_label=(node.label or "").lower().rstrip("()"),
            )
            self._node_labels[node.id] = node.label
            self._node_files[node.id] = node.source_file
            self._node_communities[node.id] = node.community

        for edge in self._payload.edges:
            if edge.source in g and edge.target in g:
                g.add_edge(
                    edge.source,
                    edge.target,
                    relation=edge.relation,
                    confidence=edge.confidence,
                    weight=edge.weight,
                    source_file=edge.source_file,
                )

        self._graph = g
        logger.debug(
            "Built graph: %d nodes, %d edges", g.number_of_nodes(), g.number_of_edges()
        )
        return g

    def _resolve_node(self, label: str) -> str | None:
        """Find a node ID by label, ID, or substring match."""
        g = self._ensure_graph()
        if label in g:
            return label

        query = label.lower().rstrip("()")
        best_id: str | None = None
        best_score = -1

        for nid, data in g.nodes(data=True):
            norm = data.get("norm_label", "")
            nid_lower = nid.lower()

            if query == norm or query == nid_lower:
                return nid
            if norm.startswith(query) and best_score < 2:
                best_id, best_score = nid, 2
            elif query in norm and best_score < 1:
                best_id, best_score = nid, 1

        return best_id

    def shortest_path(self, source_label: str, target_label: str) -> PathResult | None:
        """Find the shortest path between two nodes by label."""
        g = self._ensure_graph()
        src = self._resolve_node(source_label)
        tgt = self._resolve_node(target_label)
        if src is None or tgt is None:
            return None

        try:
            path = nx.shortest_path(g, src, tgt)
        except nx.NetworkXNoPath:
            try:
                path = nx.shortest_path(g.to_undirected(), src, tgt)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return None
        except nx.NodeNotFound:
            return None

        relations: list[str] = []
        for i in range(len(path) - 1):
            edge_data = g.get_edge_data(path[i], path[i + 1])
            if edge_data is None:
                edge_data = g.get_edge_data(path[i + 1], path[i]) or {}
            relations.append(edge_data.get("relation", "unknown"))

        return PathResult(
            source=self._node_labels.get(src, src),
            target=self._node_labels.get(tgt, tgt),
            path=[self._node_labels.get(n, n) for n in path],
            hop_count=len(path) - 1,
            edge_relations=relations,
        )

    def blast_radius(self, label: str, max_hops: int = 3) -> BlastRadiusResult | None:
        """Count nodes reachable within *max_hops* from a starting node."""
        g = self._ensure_graph()
        start = self._resolve_node(label)
        if start is None:
            return None

        undirected = g.to_undirected()
        lengths = nx.single_source_shortest_path_length(undirected, start, cutoff=max_hops)

        by_hop: Counter[int] = Counter()
        files: set[str] = set()
        for nid, dist in lengths.items():
            if nid == start:
                continue
            by_hop[dist] += 1
            files.add(self._node_files.get(nid, ""))

        files.discard("")
        return BlastRadiusResult(
            origin=self._node_labels.get(start, start),
            max_hops=max_hops,
            reachable_count=sum(by_hop.values()),
            by_hop=dict(sorted(by_hop.items())),
            reachable_files=sorted(files),
        )

    def get_neighbors(
        self, label: str, relation_filter: str | None = None
    ) -> list[NeighborEntry]:
        """Get direct neighbors of a node with edge details."""
        g = self._ensure_graph()
        nid = self._resolve_node(label)
        if nid is None:
            return []

        results: list[NeighborEntry] = []
        for _, target, data in g.out_edges(nid, data=True):
            rel = data.get("relation", "unknown")
            if relation_filter and rel != relation_filter:
                continue
            results.append(
                NeighborEntry(
                    node_id=target,
                    label=self._node_labels.get(target, target),
                    relation=rel,
                    direction="outgoing",
                    source_file=self._node_files.get(target, ""),
                )
            )
        for source, _, data in g.in_edges(nid, data=True):
            rel = data.get("relation", "unknown")
            if relation_filter and rel != relation_filter:
                continue
            results.append(
                NeighborEntry(
                    node_id=source,
                    label=self._node_labels.get(source, source),
                    relation=rel,
                    direction="incoming",
                    source_file=self._node_files.get(source, ""),
                )
            )
        return results

    def community_members(self, community_id: int) -> CommunityDetail | None:
        """Get all nodes in a specific community."""
        g = self._ensure_graph()
        members: list[str] = []
        labels: list[str] = []
        name: str | None = None

        for nid, data in g.nodes(data=True):
            if data.get("community") == community_id:
                members.append(nid)
                labels.append(data.get("label", nid))
                if name is None:
                    name = data.get("community_name")

        if not members:
            return None

        return CommunityDetail(
            community_id=community_id,
            community_name=name,
            members=members,
            member_labels=labels,
        )

    def coupling_between(self, comm_a: int, comm_b: int) -> CouplingResult:
        """Count edges crossing between two distinct communities."""
        g = self._ensure_graph()
        relation_counts: Counter[str] = Counter()

        if comm_a == comm_b:
            return CouplingResult(
                community_a=comm_a, community_b=comm_b, edge_count=0, relations={}
            )

        for src, tgt, data in g.edges(data=True):
            src_comm = self._node_communities.get(src)
            tgt_comm = self._node_communities.get(tgt)
            if (src_comm == comm_a and tgt_comm == comm_b) or (
                src_comm == comm_b and tgt_comm == comm_a
            ):
                relation_counts[data.get("relation", "unknown")] += 1

        return CouplingResult(
            community_a=comm_a,
            community_b=comm_b,
            edge_count=sum(relation_counts.values()),
            relations=dict(relation_counts),
        )

    def stats(self) -> GraphStats:
        """Return summary statistics for the graph."""
        g = self._ensure_graph()
        n = g.number_of_nodes()
        e = g.number_of_edges()
        communities = {
            data.get("community")
            for _, data in g.nodes(data=True)
            if data.get("community") is not None
        }
        return GraphStats(
            node_count=n,
            edge_count=e,
            community_count=len(communities),
            density=nx.density(g) if n > 0 else 0.0,
            avg_degree=(2 * e / n) if n > 0 else 0.0,
        )

    def god_nodes(self, top_n: int = 10) -> list[dict[str, object]]:
        """Return the top-N most connected nodes by total degree."""
        g = self._ensure_graph()
        undirected = g.to_undirected()
        degrees = sorted(undirected.degree(), key=lambda x: x[1], reverse=True)

        results: list[dict[str, object]] = []
        for nid, deg in degrees[:top_n]:
            data = g.nodes[nid]
            results.append(
                {
                    "node_id": nid,
                    "label": data.get("label", nid),
                    "source_file": data.get("source_file", ""),
                    "total_degree": deg,
                    "community": data.get("community"),
                }
            )
        return results


__all__ = [
    "BlastRadiusResult",
    "CommunityDetail",
    "CouplingResult",
    "GraphQueryClient",
    "GraphStats",
    "NeighborEntry",
    "PathResult",
]
