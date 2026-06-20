# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the MCP client adapter and factory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nfr_review.collectors.payloads.graphify import (
    GraphEdge,
    GraphifyPayload,
    GraphNode,
)
from nfr_review.graph_query import GraphQueryClient
from nfr_review.mcp_client import GraphifyMCPClient, create_graph_client


def _make_payload() -> GraphifyPayload:
    return GraphifyPayload(
        node_count=2,
        edge_count=1,
        community_count=1,
        median_degree=1.0,
        god_node_threshold=2,
        cross_community_ratio=0.0,
        nodes=[
            GraphNode(
                id="a",
                label="Alpha",
                file_type="code",
                source_file="src/a.py",
                community=0,
            ),
            GraphNode(
                id="b",
                label="Beta",
                file_type="code",
                source_file="src/b.py",
                community=0,
            ),
        ],
        edges=[
            GraphEdge(
                source="a",
                target="b",
                relation="calls",
                source_file="src/a.py",
            ),
        ],
    )


class TestCreateGraphClient:
    def test_returns_direct_client_when_mcp_disabled(self) -> None:
        payload = _make_payload()
        client = create_graph_client(payload, mcp_enabled=False)
        assert isinstance(client, GraphQueryClient)

    def test_returns_direct_client_when_no_graph_path(self) -> None:
        payload = _make_payload()
        client = create_graph_client(payload, mcp_enabled=True, graph_path=None)
        assert isinstance(client, GraphQueryClient)

    def test_returns_direct_client_when_graphify_not_on_path(self) -> None:
        payload = _make_payload()
        with patch("nfr_review.mcp_client.shutil.which", return_value=None):
            client = create_graph_client(
                payload, mcp_enabled=True, graph_path="/tmp/graph.json"
            )
        assert isinstance(client, GraphQueryClient)

    def test_raises_when_no_payload_and_no_mcp(self) -> None:
        with pytest.raises(ValueError, match="GraphifyPayload must be provided"):
            create_graph_client(None, mcp_enabled=False)

    def test_falls_back_on_mcp_init_failure(self) -> None:
        payload = _make_payload()
        with (
            patch("nfr_review.mcp_client.shutil.which", return_value="/usr/bin/graphify"),
            patch(
                "nfr_review.mcp_client.GraphifyMCPClient",
                side_effect=RuntimeError("boom"),
            ),
        ):
            client = create_graph_client(
                payload, mcp_enabled=True, graph_path="/tmp/graph.json"
            )
        assert isinstance(client, GraphQueryClient)


class TestGraphifyMCPClientInit:
    def test_constructor_stores_path(self) -> None:
        client = GraphifyMCPClient("/tmp/graph.json")
        assert client._graph_path == "/tmp/graph.json"
        assert client._process is None

    def test_close_noop_when_no_process(self) -> None:
        client = GraphifyMCPClient("/tmp/graph.json")
        client.close()  # should not raise
