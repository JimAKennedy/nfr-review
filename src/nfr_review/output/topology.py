# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Build a directed service topology graph from OTel trace evidence.

Nodes are unique ``service.name`` values.  Edges represent observed
parent→child span relationships that cross service boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nfr_review.models import Evidence

_DOT_ESCAPE_RE = re.compile(r'([\\"])')
_MERMAID_ID_RE = re.compile(r"[^a-zA-Z0-9_]")


@dataclass
class ServiceEdge:
    caller: str
    callee: str
    count: int = 0


@dataclass
class TopologyGraph:
    services: set[str] = field(default_factory=set)
    edges: dict[tuple[str, str], int] = field(default_factory=dict)

    def add_edge(self, caller: str, callee: str) -> None:
        self.services.add(caller)
        self.services.add(callee)
        key = (caller, callee)
        self.edges[key] = self.edges.get(key, 0) + 1

    def edge_list(self) -> list[ServiceEdge]:
        return [
            ServiceEdge(caller=k[0], callee=k[1], count=v)
            for k, v in sorted(self.edges.items())
        ]


def build_topology_graph(evidence: list[Evidence]) -> TopologyGraph:
    """Build a topology graph from otel-trace evidence.

    Cross-service edges are detected by matching ``parent_span_id`` to
    ``span_id`` within the same trace, where the two spans have different
    ``service_name`` values.
    """
    graph = TopologyGraph()

    trace_ev = [
        e for e in evidence if e.collector_name == "otel-trace" and e.kind == "otel-trace"
    ]
    if not trace_ev:
        return graph

    span_index: dict[str, tuple[str, str]] = {}  # span_id -> (service_name, trace_id)
    all_spans: list[tuple[str, str, str, str]] = []  # (trace_id, span_id, parent_span_id, svc)

    for ev in trace_ev:
        for span in ev.payload.spans:
            svc = (
                span.get("service_name", "")
                if hasattr(span, "get")
                else getattr(span, "service_name", "")
            )
            sid = (
                span.get("span_id", "")
                if hasattr(span, "get")
                else getattr(span, "span_id", "")
            )
            pid = (
                span.get("parent_span_id", "")
                if hasattr(span, "get")
                else getattr(span, "parent_span_id", "")
            )
            tid = (
                span.get("trace_id", "")
                if hasattr(span, "get")
                else getattr(span, "trace_id", "")
            )
            if svc:
                graph.services.add(svc)
            if sid:
                span_index[sid] = (svc, tid)
            all_spans.append((tid, sid, pid, svc))

    for tid, _sid, pid, svc in all_spans:
        if not pid or not svc:
            continue
        parent_info = span_index.get(pid)
        if parent_info and parent_info[0] and parent_info[0] != svc:
            if parent_info[1] == tid:
                graph.add_edge(parent_info[0], svc)

    return graph


def render_topology_mermaid(graph: TopologyGraph) -> str:
    """Render topology as a Mermaid graph TD diagram."""
    lines = ["graph TD"]
    if not graph.services:
        lines.append("  empty[No services observed]")
        return "\n".join(lines) + "\n"

    for svc in sorted(graph.services):
        safe_id = _MERMAID_ID_RE.sub("_", svc)
        lines.append(f'  {safe_id}["{svc}"]')

    for (caller, callee), count in sorted(graph.edges.items()):
        caller_id = _MERMAID_ID_RE.sub("_", caller)
        callee_id = _MERMAID_ID_RE.sub("_", callee)
        lines.append(f"  {caller_id} -->|{count}| {callee_id}")

    return "\n".join(lines) + "\n"


def render_topology_dot(graph: TopologyGraph) -> str:
    """Render topology as a Graphviz DOT digraph."""
    lines = [
        "digraph service_topology {",
        "  rankdir=LR;",
        '  node [shape=box, style=filled, fillcolor="#e8e8e8"];',
    ]

    if not graph.services:
        lines.append("}")
        return "\n".join(lines) + "\n"

    def _esc(v: str) -> str:
        return _DOT_ESCAPE_RE.sub(r"\\\1", v)

    def _nid(svc: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_]", "_", svc)

    for svc in sorted(graph.services):
        lines.append(f'  {_nid(svc)} [label="{_esc(svc)}"];')

    for (caller, callee), count in sorted(graph.edges.items()):
        lines.append(f'  {_nid(caller)} -> {_nid(callee)} [label="{count}"];')

    lines.append("}")
    return "\n".join(lines) + "\n"


__all__ = [
    "ServiceEdge",
    "TopologyGraph",
    "build_topology_graph",
    "render_topology_dot",
    "render_topology_mermaid",
]
