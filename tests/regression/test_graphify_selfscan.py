# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Regression test: run GraphifyCollector against the nfr-review codebase itself.

Validates that Graphify produces meaningful structural analysis for a real
500+ file Python project. Requires graphify to be installed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def graphify_available() -> bool:
    return shutil.which("graphify") is not None


@pytest.fixture(scope="module")
def selfscan_evidence(graphify_available: bool) -> list:
    if not graphify_available:
        pytest.skip("graphify not installed")

    from nfr_review.collectors.graphify import GraphifyCollector

    collector = GraphifyCollector()
    return collector.collect(REPO_ROOT, None)


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
