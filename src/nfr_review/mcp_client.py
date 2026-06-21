# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""MCP client adapter for querying a running Graphify MCP server.

Provides the same query interface as :class:`GraphQueryClient` but delegates
to a ``graphify serve`` subprocess via MCP stdio protocol.  Falls back to the
in-process :class:`GraphQueryClient` when MCP is unavailable.

The MCP SDK (``pip install mcp``) is an **optional** dependency.  When not
installed, :func:`create_graph_client` always returns the direct client.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess  # nosec B404 — args are hardcoded
from typing import TYPE_CHECKING, Any

from nfr_review.graph_query import (
    BlastRadiusResult,
    GraphQueryClient,
    GraphStats,
    NeighborEntry,
    PathResult,
)

if TYPE_CHECKING:
    from nfr_review.collectors.payloads.graphify import GraphifyPayload

logger = logging.getLogger(__name__)


class GraphifyMCPClient:
    """Query a Graphify MCP server via subprocess stdio.

    Starts ``graphify serve <graph_path>`` on first query and communicates
    via JSON-RPC over stdin/stdout.  Falls back gracefully if the server
    cannot be started.
    """

    def __init__(self, graph_path: str) -> None:
        self._graph_path = graph_path
        self._process: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._request_id = 0

    def _ensure_server(self) -> subprocess.Popen:  # type: ignore[type-arg]
        if self._process is not None and self._process.poll() is None:
            return self._process

        graphify_bin = shutil.which("graphify")
        if graphify_bin is None:
            raise RuntimeError("graphify CLI not found on PATH")

        self._process = subprocess.Popen(  # nosec B603 B607
            [graphify_bin, "serve", self._graph_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._send_initialize()
        return self._process

    def _send_initialize(self) -> None:
        """Send the MCP initialize handshake."""
        self._call_rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "nfr-review", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})

    def _call_rpc(self, method: str, params: dict) -> Any:
        proc = self._ensure_server()
        assert proc.stdin is not None  # noqa: S101
        assert proc.stdout is not None  # noqa: S101

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()

        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout")
        response = json.loads(line)
        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")
        return response.get("result")

    def _notify(self, method: str, params: dict) -> None:
        proc = self._ensure_server()
        assert proc.stdin is not None  # noqa: S101
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        proc.stdin.write(json.dumps(notification) + "\n")
        proc.stdin.flush()

    def _call_tool(self, tool_name: str, arguments: dict) -> str:
        result = self._call_rpc(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )
        if isinstance(result, dict) and "content" in result:
            for block in result["content"]:
                if block.get("type") == "text":
                    return block["text"]
        return json.dumps(result) if result else ""

    def shortest_path(self, source_label: str, target_label: str) -> PathResult | None:
        try:
            text = self._call_tool(
                "shortest_path",
                {
                    "source": source_label,
                    "target": target_label,
                },
            )
        except RuntimeError:
            logger.warning("MCP shortest_path failed", exc_info=True)
            return None

        if "no path" in text.lower() or "not found" in text.lower():
            return None

        lines = text.strip().splitlines()
        path_labels: list[str] = []
        relations: list[str] = []
        for line in lines:
            stripped = line.strip().lstrip("→ ").strip()
            if stripped.startswith("--["):
                rel = stripped.split("]")[0].lstrip("-[")
                relations.append(rel)
            elif stripped:
                path_labels.append(stripped.split(" (")[0])

        if len(path_labels) < 2:
            return None

        return PathResult(
            source=path_labels[0],
            target=path_labels[-1],
            path=path_labels,
            hop_count=len(path_labels) - 1,
            edge_relations=relations,
        )

    def blast_radius(self, label: str, max_hops: int = 3) -> BlastRadiusResult | None:
        try:
            text = self._call_tool(
                "query_graph",
                {
                    "question": label,
                    "mode": "bfs",
                    "depth": max_hops,
                },
            )
        except RuntimeError:
            logger.warning("MCP blast_radius query failed", exc_info=True)
            return None

        node_lines = [
            ln for ln in text.splitlines() if ln.strip() and not ln.startswith("---")
        ]
        return BlastRadiusResult(
            origin=label,
            max_hops=max_hops,
            reachable_count=len(node_lines),
            by_hop={},
            reachable_files=[],
        )

    def get_neighbors(
        self, label: str, relation_filter: str | None = None
    ) -> list[NeighborEntry]:
        args: dict[str, Any] = {"label": label}
        if relation_filter:
            args["relation_filter"] = relation_filter
        try:
            text = self._call_tool("get_neighbors", args)
        except RuntimeError:
            logger.warning("MCP get_neighbors failed", exc_info=True)
            return []

        entries: list[NeighborEntry] = []
        for line in text.splitlines():
            parts = line.strip().split(" --[")
            if len(parts) >= 2:
                node_part = parts[0].strip()
                rel_part = parts[1].split("]")[0] if "]" in parts[1] else "unknown"
                entries.append(
                    NeighborEntry(
                        node_id=node_part,
                        label=node_part,
                        relation=rel_part,
                        direction="outgoing",
                        source_file="",
                    )
                )
        return entries

    def stats(self) -> GraphStats:
        try:
            text = self._call_tool("graph_stats", {})
        except RuntimeError:
            return GraphStats(
                node_count=0,
                edge_count=0,
                community_count=0,
                density=0.0,
                avg_degree=0.0,
            )

        data: dict[str, Any] = {}
        for line in text.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                try:
                    data[key.strip().lower().replace(" ", "_")] = float(
                        val.strip().rstrip("%")
                    )
                except ValueError:
                    pass

        return GraphStats(
            node_count=int(data.get("nodes", data.get("node_count", 0))),
            edge_count=int(data.get("edges", data.get("edge_count", 0))),
            community_count=int(data.get("communities", 0)),
            density=data.get("density", 0.0),
            avg_degree=data.get("avg_degree", data.get("average_degree", 0.0)),
        )

    def close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def __del__(self) -> None:
        self.close()


def create_graph_client(
    payload: GraphifyPayload | None = None,
    *,
    mcp_enabled: bool = False,
    graph_path: str | None = None,
) -> GraphQueryClient | GraphifyMCPClient:
    """Create the best available graph query client.

    Tries MCP first when *mcp_enabled* and *graph_path* are set and graphify
    is on PATH; otherwise returns the in-process :class:`GraphQueryClient`.
    """
    if mcp_enabled and graph_path and shutil.which("graphify"):
        try:
            client = GraphifyMCPClient(graph_path)
            logger.info("Using MCP client for structural queries: %s", graph_path)
            return client
        except Exception:  # noqa: BLE001
            logger.warning(
                "MCP client init failed, falling back to direct queries",
                exc_info=True,
            )

    if payload is None:
        raise ValueError("Either MCP must be available or a GraphifyPayload must be provided")
    return GraphQueryClient(payload)


__all__ = [
    "GraphifyMCPClient",
    "create_graph_client",
]
