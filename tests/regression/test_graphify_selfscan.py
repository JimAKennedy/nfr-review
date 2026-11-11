# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Regression test: run GraphifyCollector against the nfr-review codebase itself.

Validates that Graphify produces meaningful structural analysis for a real
500+ file Python project. Requires graphify to be installed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from filelock import FileLock

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def graphify_available() -> bool:
    return shutil.which("graphify") is not None


@pytest.fixture(scope="module")
def selfscan_evidence(
    graphify_available: bool, tmp_path_factory: pytest.TempPathFactory
) -> list:
    if not graphify_available:
        pytest.skip("graphify not installed")

    from nfr_review.collectors.graphify import GraphifyCollector, _run_graphify
    from nfr_review.config import Config, GraphifyConfig

    # Build the graph once per session, outside the repo, and share it across
    # xdist workers (basetemp's parent is per-session only under xdist). The
    # collector then reads it through graphify.graph_path.
    shared_root = tmp_path_factory.getbasetemp()
    if os.environ.get("PYTEST_XDIST_WORKER"):
        shared_root = shared_root.parent
    out_dir = shared_root / "graphify-selfscan" / "graphify-out"
    graph_json = out_dir / "graph.json"
    with FileLock(shared_root / "graphify-selfscan.lock", timeout=900):
        if not graph_json.is_file():
            assert _run_graphify(REPO_ROOT, out_dir) is not None, (
                "graphify failed to build the self-scan graph"
            )

    config = Config(graphify=GraphifyConfig(enabled=True, graph_path=str(graph_json)))
    return GraphifyCollector().collect(REPO_ROOT, config)


class TestGraphifySelfScan:
    def test_produces_evidence(self, selfscan_evidence: list) -> None:
        assert len(selfscan_evidence) == 1
        assert selfscan_evidence[0].kind == "graphify-analysis"

    def test_node_count_reasonable(self, selfscan_evidence: list) -> None:
        payload = selfscan_evidence[0].payload
        assert payload.node_count > 100, (
            f"Expected >100 nodes for nfr-review, got {payload.node_count}"
        )

    def test_edge_count_reasonable(self, selfscan_evidence: list) -> None:
        payload = selfscan_evidence[0].payload
        assert payload.edge_count > 100, (
            f"Expected >100 edges for nfr-review, got {payload.edge_count}"
        )

    def test_communities_detected(self, selfscan_evidence: list) -> None:
        payload = selfscan_evidence[0].payload
        assert payload.community_count > 0, "Expected at least one community"

    def test_god_nodes_found(self, selfscan_evidence: list) -> None:
        payload = selfscan_evidence[0].payload
        assert len(payload.god_nodes) > 0, (
            "Expected at least one god node in a 500+ file project"
        )

    def test_community_stats_populated(self, selfscan_evidence: list) -> None:
        payload = selfscan_evidence[0].payload
        assert len(payload.community_stats) > 0
        for stat in payload.community_stats:
            assert stat.node_count > 0

    def test_structural_rules_fire(self, selfscan_evidence: list) -> None:
        """Verify that the structural rules produce findings against self-scan data."""
        from nfr_review.rules.structure_god_node import StructureGodNodeRule
        from nfr_review.rules.structure_weak_boundary import StructureWeakBoundaryRule

        god_result = StructureGodNodeRule().evaluate(selfscan_evidence, None)
        assert not god_result.skipped
        assert len(god_result.findings) > 0, (
            "Expected god-node findings for nfr-review's structural hubs"
        )

        boundary_result = StructureWeakBoundaryRule().evaluate(selfscan_evidence, None)
        assert not boundary_result.skipped
