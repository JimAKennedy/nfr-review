# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the Graphify collector."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from nfr_review.collectors.graphify import GraphifyCollector, _compute_metrics
from nfr_review.collectors.payloads.graphify import GraphEdge, GraphNode
from nfr_review.config import Config, GraphifyConfig


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


_WHICH = "nfr_review.collectors.graphify.shutil.which"
_RUN = "nfr_review.collectors.graphify.subprocess.run"

_STALE_NODES = [
    {"id": "stale-1", "label": "Stale1", "file_type": "code", "source_file": "s1.py"},
    {"id": "stale-2", "label": "Stale2", "file_type": "code", "source_file": "s2.py"},
]


def _write_graph(
    path: Path, nodes: list[dict] | None = None, edges: list[dict] | None = None
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _make_graph_json(
        _simple_nodes() if nodes is None else nodes,
        _simple_edges() if edges is None else edges,
    )
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _seed_stale_graph(repo: Path) -> None:
    """Leave a two-node graph.json where the old collector used to reuse it."""
    _write_graph(repo / "graphify-out" / "graph.json", nodes=_STALE_NODES, edges=[])


def _enabled(graph_path: str | None = None) -> Config:
    return Config(graphify=GraphifyConfig(enabled=True, graph_path=graph_path))


def _tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def _fake_graphify(calls: list[dict[str, Any]]) -> Any:
    """Stand-in for subprocess.run: ``update`` writes a graph into GRAPHIFY_OUT."""

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": list(args), **kwargs})
        if args[1] == "update":
            _write_graph(Path(kwargs["env"]["GRAPHIFY_OUT"]) / "graph.json")
        return subprocess.CompletedProcess(args, 0, "", "")

    return run


class TestGraphifyCollector:
    @pytest.mark.parametrize("config", [None, Config()], ids=["no-config", "default"])
    def test_default_config_never_invokes_graphify(
        self, tmp_path: Path, config: Config | None
    ) -> None:
        _seed_stale_graph(tmp_path)
        with patch(_WHICH, return_value="/usr/bin/graphify"), patch(_RUN) as run:
            result = GraphifyCollector().collect(tmp_path, config)
        assert result == []
        run.assert_not_called()

    def test_enabled_writes_output_to_temp_dir_and_ignores_stale_repo_graph(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _seed_stale_graph(repo)
        before = _tree(repo)
        calls: list[dict[str, Any]] = []

        with (
            patch(_WHICH, return_value="/usr/bin/graphify"),
            patch(_RUN, side_effect=_fake_graphify(calls)),
        ):
            result = GraphifyCollector().collect(repo, _enabled())

        assert [c["args"][1] for c in calls] == ["update", "cluster-only"]
        out_dirs = {Path(c["env"]["GRAPHIFY_OUT"]) for c in calls}
        assert len(out_dirs) == 1
        out_dir = out_dirs.pop()
        assert out_dir.is_absolute()
        assert out_dir.name == "graphify-out"
        assert not out_dir.is_relative_to(repo.resolve())
        cluster_args = calls[1]["args"]
        assert cluster_args[cluster_args.index("--graph") + 1] == str(out_dir / "graph.json")
        assert not out_dir.parent.exists(), "temp dir must be deleted after the read"
        assert _tree(repo) == before, "nothing may be written into the scanned repo"
        assert len(result) == 1
        assert result[0].payload.node_count == 5
        assert "stale-1" not in {n.id for n in result[0].payload.nodes}

    def test_enabled_skips_when_not_installed(self, tmp_path: Path) -> None:
        with patch(_WHICH, return_value=None), patch(_RUN) as run:
            result = GraphifyCollector().collect(tmp_path, _enabled())
        assert result == []
        run.assert_not_called()

    def test_update_failure_returns_empty_and_removes_temp_dir(self, tmp_path: Path) -> None:
        calls: list[dict[str, Any]] = []

        def failing_run(args: list[str], **kwargs: Any) -> None:
            calls.append({"args": list(args), **kwargs})
            raise subprocess.CalledProcessError(1, args, stderr="boom")

        with (
            patch(_WHICH, return_value="/usr/bin/graphify"),
            patch(_RUN, side_effect=failing_run),
        ):
            result = GraphifyCollector().collect(tmp_path, _enabled())

        assert result == []
        assert len(calls) == 1
        assert not Path(calls[0]["env"]["GRAPHIFY_OUT"]).parent.exists()

    def test_graph_path_is_read_without_running_graphify(self, tmp_path: Path) -> None:
        graph = _write_graph(tmp_path / "elsewhere" / "graph.json")
        repo = tmp_path / "repo"
        repo.mkdir()
        with patch(_WHICH, return_value=None), patch(_RUN) as run:
            result = GraphifyCollector().collect(repo, _enabled(str(graph)))
        run.assert_not_called()
        assert len(result) == 1
        ev = result[0]
        assert ev.collector_name == "graphify"
        assert ev.kind == "graphify-analysis"
        assert ev.payload.node_count == 5
        assert ev.payload.edge_count == 9
        assert len(ev.payload.god_nodes) >= 1

    def test_relative_graph_path_resolves_against_repo(self, tmp_path: Path) -> None:
        _write_graph(tmp_path / "custom" / "graph.json")
        with patch(_RUN) as run:
            result = GraphifyCollector().collect(tmp_path, _enabled("custom/graph.json"))
        run.assert_not_called()
        assert result[0].payload.node_count == 5

    def test_missing_graph_path_returns_empty(self, tmp_path: Path) -> None:
        with patch(_RUN) as run:
            result = GraphifyCollector().collect(
                tmp_path, _enabled(str(tmp_path / "missing.json"))
            )
        assert result == []
        run.assert_not_called()

    def test_returns_empty_on_bad_json(self, tmp_path: Path) -> None:
        bad = tmp_path / "graph.json"
        bad.write_text("not json at all", encoding="utf-8")
        assert GraphifyCollector().collect(tmp_path, _enabled(str(bad))) == []

    def test_handles_graph_without_communities(self, tmp_path: Path) -> None:
        nodes = [
            {"id": "x", "label": "X", "file_type": "code", "source_file": "x.py"},
            {"id": "y", "label": "Y", "file_type": "code", "source_file": "y.py"},
        ]
        edges = [
            {"source": "x", "target": "y", "relation": "calls", "source_file": "x.py"},
        ]
        graph = _write_graph(tmp_path / "graph.json", nodes=nodes, edges=edges)
        result = GraphifyCollector().collect(tmp_path, _enabled(str(graph)))
        assert len(result) == 1
        assert result[0].payload.community_count == 0
        assert result[0].payload.cross_community_ratio == 0.0


@pytest.mark.skipif(shutil.which("graphify") is None, reason="graphify CLI not installed")
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX read-only permissions")
def test_real_graphify_on_read_only_repo_writes_nothing(tmp_path: Path) -> None:
    """The real CLI, on a read-only repo holding a stale graph, as in the :ro E2E mount."""
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text("from pkg.b import g\n\n\ndef f():\n    return g()\n")
    (pkg / "b.py").write_text("def g():\n    return 1\n\n\ndef h():\n    return g()\n")
    _seed_stale_graph(repo)
    before = _tree(repo)
    read_only_dirs = [repo, pkg, repo / "graphify-out"]
    for d in read_only_dirs:
        d.chmod(0o555)
    try:
        result = GraphifyCollector().collect(repo, _enabled())
    finally:
        for d in read_only_dirs:
            d.chmod(0o755)

    assert _tree(repo) == before
    assert len(result) == 1
    node_ids = {n.id for n in result[0].payload.nodes}
    assert node_ids
    assert not node_ids & {"stale-1", "stale-2"}
