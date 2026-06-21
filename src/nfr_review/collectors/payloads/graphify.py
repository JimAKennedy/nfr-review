# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the Graphify knowledge-graph collector.

Mirrors the graph.json schema produced by ``graphify extract`` / ``graphify update``
plus computed structural metrics (god nodes, community boundary stats).
"""

from __future__ import annotations

from pydantic import ConfigDict, Field, model_validator

from nfr_review.models import BasePayload

__all__ = [
    "CommunityStats",
    "GodNodeEntry",
    "GraphEdge",
    "GraphNode",
    "GraphifyPayload",
]


class GraphNode(BasePayload):
    """Single node from a Graphify knowledge graph."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    label: str
    file_type: str
    source_file: str
    source_location: str | None = None
    community: int | None = None
    community_name: str | None = None


class GraphEdge(BasePayload):
    """Single edge from a Graphify knowledge graph."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    source: str
    target: str
    relation: str
    confidence: str = "EXTRACTED"
    confidence_score: float = 1.0
    context: str | None = None
    source_file: str
    source_location: str | None = None
    weight: float = 1.0


class GodNodeEntry(BasePayload):
    """A node whose total degree exceeds the god-node threshold."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    node_id: str
    label: str
    source_file: str
    in_degree: int
    out_degree: int
    total_degree: int
    community: int | None = None


class CommunityStats(BasePayload):
    """Boundary metrics for a single Leiden community."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    community_id: int
    community_name: str | None = None
    node_count: int
    internal_edges: int
    cross_boundary_edges: int
    cross_boundary_ratio: float = Field(ge=0.0, le=1.0)


class GraphifyPayload(BasePayload):
    """Whole-repo structural analysis from Graphify.

    Accepts both ``links`` and ``edges`` as the edge array key in graph.json.
    Computed metrics (god_nodes, community_stats, cross_community_ratio) are
    populated by the collector, not read from graph.json directly.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    node_count: int
    edge_count: int
    community_count: int
    median_degree: float
    god_node_threshold: int
    cross_community_ratio: float = Field(ge=0.0, le=1.0)
    god_nodes: list[GodNodeEntry] = Field(default_factory=list)
    community_stats: list[CommunityStats] = Field(default_factory=list)
    nodes: list[GraphNode] = Field(default_factory=list, exclude=True)
    edges: list[GraphEdge] = Field(default_factory=list, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _normalise_edge_key(cls, data: dict) -> dict:  # type: ignore[override]
        if isinstance(data, dict) and "links" in data and "edges" not in data:
            data["edges"] = data.pop("links")
        return data
