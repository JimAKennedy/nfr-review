"""Integration tests for PATCH-TRAFFIC rules through the full Engine.run() pipeline.

Runs against service-mesh fixture repos and verifies that:
- service-mesh-sample-repo (bad) produces amber findings for missing traffic config.
- service-mesh-good-repo (good) produces only green findings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.k8s_manifest import K8sManifestCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.collectors.service_mesh import ServiceMeshCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.patch_traffic import (
    ConnectionDrainingRule,
    FailoverDocumentationRule,
    ProgressiveTrafficShiftingRule,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_REPO = FIXTURES / "service-mesh-sample-repo"
GOOD_REPO = FIXTURES / "service-mesh-good-repo"

PATCH_TRAFFIC_RULE_IDS = {
    "PATCH-TRAFFIC-001",
    "PATCH-TRAFFIC-002",
    "PATCH-TRAFFIC-003",
}


def _traffic_registries() -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("service-mesh", ServiceMeshCollector())
    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("k8s-manifest", K8sManifestCollector())

    rregistry.register("PATCH-TRAFFIC-001", ProgressiveTrafficShiftingRule())
    rregistry.register("PATCH-TRAFFIC-002", FailoverDocumentationRule())
    rregistry.register("PATCH-TRAFFIC-003", ConnectionDrainingRule())

    return cregistry, rregistry


def _run_engine(target: Path) -> RunResult:
    cregistry, rregistry = _traffic_registries()
    engine = Engine(collectors=cregistry, rules=rregistry)
    return engine.run(target=target, config=Config())


def _findings_by_rule(result: RunResult) -> dict[str, list]:
    by_rule: dict[str, list] = {}
    for f in result.findings:
        by_rule.setdefault(f.rule_id, []).append(f)
    return by_rule


def _rule_results_by_id(result: RunResult) -> dict[str, object]:
    return {rr.rule_id: rr for rr in result.rule_results}


# ---------------------------------------------------------------------------
# Sample repo (bad): missing connection pool + missing failover docs
# ---------------------------------------------------------------------------


class TestSampleRepoFindings:
    """service-mesh-sample-repo should trigger amber findings."""

    @pytest.fixture(scope="class")
    def result(self) -> RunResult:
        return _run_engine(SAMPLE_REPO)

    def test_no_rules_skipped(self, result: RunResult) -> None:
        rr_map = _rule_results_by_id(result)
        for rule_id in PATCH_TRAFFIC_RULE_IDS:
            assert rule_id in rr_map, f"Rule {rule_id} missing from results"
            assert not rr_map[rule_id].skipped, (
                f"Rule {rule_id} was unexpectedly skipped: {rr_map[rule_id].skip_reason}"
            )

    def test_all_rules_produce_findings(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        for rule_id in PATCH_TRAFFIC_RULE_IDS:
            assert rule_id in by_rule, f"No findings from {rule_id}"

    def test_traffic_shifting_green(self, result: RunResult) -> None:
        """Sample repo has weighted VS + canary rollout steps → green."""
        by_rule = _findings_by_rule(result)
        findings_001 = by_rule["PATCH-TRAFFIC-001"]
        assert all(f.rag == "green" for f in findings_001), (
            f"Expected all green for 001, got {[(f.rag, f.summary) for f in findings_001]}"
        )

    def test_failover_docs_amber(self, result: RunResult) -> None:
        """Sample repo has no failover documentation → amber."""
        by_rule = _findings_by_rule(result)
        findings_002 = by_rule["PATCH-TRAFFIC-002"]
        assert any(f.rag == "amber" for f in findings_002)

    def test_connection_draining_amber(self, result: RunResult) -> None:
        """Sample repo DestinationRule has no connectionPool → amber."""
        by_rule = _findings_by_rule(result)
        findings_003 = by_rule["PATCH-TRAFFIC-003"]
        amber = [f for f in findings_003 if f.rag == "amber"]
        assert len(amber) >= 1, (
            f"Expected amber for 003, got {[(f.rag, f.summary) for f in findings_003]}"
        )

    def test_has_non_green_findings(self, result: RunResult) -> None:
        non_green = [f for f in result.findings if f.rag in ("red", "amber")]
        assert len(non_green) >= 2, (
            f"Expected at least 2 non-green findings, got {len(non_green)}"
        )

    def test_findings_have_valid_metadata(self, result: RunResult) -> None:
        for f in result.findings:
            assert f.rule_id in PATCH_TRAFFIC_RULE_IDS
            assert f.evidence_locator
            assert f.pattern_tag.startswith("patch-traffic-")

    def test_no_engine_warnings(self, result: RunResult) -> None:
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Good repo: weighted routing + connection pool + failover docs → all green
# ---------------------------------------------------------------------------


class TestGoodRepoFindings:
    """service-mesh-good-repo should produce only green findings."""

    @pytest.fixture(scope="class")
    def result(self) -> RunResult:
        return _run_engine(GOOD_REPO)

    def test_no_rules_skipped(self, result: RunResult) -> None:
        rr_map = _rule_results_by_id(result)
        for rule_id in PATCH_TRAFFIC_RULE_IDS:
            assert rule_id in rr_map, f"Rule {rule_id} missing from results"
            assert not rr_map[rule_id].skipped, (
                f"Rule {rule_id} was unexpectedly skipped: {rr_map[rule_id].skip_reason}"
            )

    def test_all_rules_produce_findings(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        for rule_id in PATCH_TRAFFIC_RULE_IDS:
            assert rule_id in by_rule, f"No findings from {rule_id}"

    def test_all_findings_are_green(self, result: RunResult) -> None:
        non_green = [f for f in result.findings if f.rag != "green"]
        if non_green:
            details = [(f.rule_id, f.rag, f.summary) for f in non_green]
            pytest.fail(f"Expected all green, got {len(non_green)} non-green: {details}")

    def test_traffic_shifting_green(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        findings_001 = by_rule["PATCH-TRAFFIC-001"]
        assert all(f.rag == "green" for f in findings_001)

    def test_failover_docs_green(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        findings_002 = by_rule["PATCH-TRAFFIC-002"]
        assert all(f.rag == "green" for f in findings_002)

    def test_connection_draining_green(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        findings_003 = by_rule["PATCH-TRAFFIC-003"]
        assert all(f.rag == "green" for f in findings_003)

    def test_findings_have_valid_metadata(self, result: RunResult) -> None:
        for f in result.findings:
            assert f.rule_id in PATCH_TRAFFIC_RULE_IDS
            assert f.evidence_locator
            assert f.pattern_tag.startswith("patch-traffic-")

    def test_no_engine_warnings(self, result: RunResult) -> None:
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Cross-cutting: rule-result structure
# ---------------------------------------------------------------------------


class TestRuleResultStructure:
    @pytest.fixture(scope="class")
    def sample_result(self) -> RunResult:
        return _run_engine(SAMPLE_REPO)

    @pytest.fixture(scope="class")
    def good_result(self) -> RunResult:
        return _run_engine(GOOD_REPO)

    def test_rule_result_count(self, sample_result: RunResult, good_result: RunResult) -> None:
        assert len(sample_result.rule_results) == 3
        assert len(good_result.rule_results) == 3

    def test_run_metadata_present(
        self, sample_result: RunResult, good_result: RunResult
    ) -> None:
        assert sample_result.run_metadata is not None
        assert good_result.run_metadata is not None

    def test_run_metadata_has_rules_run(
        self, sample_result: RunResult, good_result: RunResult
    ) -> None:
        for result in (sample_result, good_result):
            run_ids = set(result.run_metadata.rules_run)
            assert PATCH_TRAFFIC_RULE_IDS <= run_ids
