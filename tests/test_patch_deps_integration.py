"""Integration tests for PATCH-DEPS rules through the full Engine.run() pipeline.

Runs against deps-blast-radius fixture repos and verifies that:
- deps-blast-radius-bad produces amber findings for missing declarations and shared fate.
- deps-blast-radius-good produces green findings for declarations and shared fate,
  but amber for cross-ring dependency direction (ring 2 → ring 1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.k8s_manifest import K8sManifestCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.patch_deps import (
    CrossRingDependencyRule,
    DependencyDeclarationRule,
    SharedFateIndicatorRule,
)

FIXTURES = Path(__file__).parent / "fixtures"
BAD_REPO = FIXTURES / "deps-blast-radius-bad"
GOOD_REPO = FIXTURES / "deps-blast-radius-good"

PATCH_DEPS_RULE_IDS = {
    "PATCH-DEPS-001",
    "PATCH-DEPS-002",
    "PATCH-DEPS-003",
}


def _deps_registries() -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("k8s-manifest", K8sManifestCollector())

    rregistry.register("PATCH-DEPS-001", DependencyDeclarationRule())
    rregistry.register("PATCH-DEPS-002", SharedFateIndicatorRule())
    rregistry.register("PATCH-DEPS-003", CrossRingDependencyRule())

    return cregistry, rregistry


def _run_engine(target: Path) -> RunResult:
    cregistry, rregistry = _deps_registries()
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
# Bad repo: no annotations, shared node pool, shared DB host
# ---------------------------------------------------------------------------


class TestBadRepoFindings:
    """deps-blast-radius-bad should trigger amber findings for 001 and 002."""

    @pytest.fixture(scope="class")
    def result(self) -> RunResult:
        return _run_engine(BAD_REPO)

    def test_no_rules_skipped(self, result: RunResult) -> None:
        rr_map = _rule_results_by_id(result)
        for rule_id in PATCH_DEPS_RULE_IDS:
            assert rule_id in rr_map, f"Rule {rule_id} missing from results"
            assert not rr_map[rule_id].skipped, (
                f"Rule {rule_id} was unexpectedly skipped: {rr_map[rule_id].skip_reason}"
            )

    def test_all_rules_produce_findings(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        for rule_id in PATCH_DEPS_RULE_IDS:
            assert rule_id in by_rule, f"No findings from {rule_id}"

    def test_dependency_declaration_amber(self, result: RunResult) -> None:
        """Both workloads lack dependency annotations → 2 amber findings."""
        by_rule = _findings_by_rule(result)
        findings_001 = by_rule["PATCH-DEPS-001"]
        ambers = [f for f in findings_001 if f.rag == "amber"]
        assert len(ambers) == 2, (
            f"Expected 2 amber for 001, got {[(f.rag, f.summary) for f in findings_001]}"
        )

    def test_shared_fate_amber(self, result: RunResult) -> None:
        """Shared nodeSelector and shared DB_HOST → at least 2 amber findings."""
        by_rule = _findings_by_rule(result)
        findings_002 = by_rule["PATCH-DEPS-002"]
        ambers = [f for f in findings_002 if f.rag == "amber"]
        assert len(ambers) >= 2, (
            f"Expected >=2 amber for 002, got {[(f.rag, f.summary) for f in findings_002]}"
        )

    def test_shared_fate_mentions_node_selector(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        findings_002 = by_rule["PATCH-DEPS-002"]
        node_findings = [f for f in findings_002 if "nodeSelector" in f.summary]
        assert len(node_findings) >= 1

    def test_shared_fate_mentions_database(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        findings_002 = by_rule["PATCH-DEPS-002"]
        db_findings = [f for f in findings_002 if "database" in f.summary.lower()]
        assert len(db_findings) >= 1

    def test_cross_ring_info_no_ring_labels(self, result: RunResult) -> None:
        """Bad repo has no ring labels → green/info finding."""
        by_rule = _findings_by_rule(result)
        findings_003 = by_rule["PATCH-DEPS-003"]
        assert all(f.rag == "green" for f in findings_003), (
            f"Expected all green for 003, got {[(f.rag, f.summary) for f in findings_003]}"
        )
        assert any("no ring labels" in f.summary.lower() for f in findings_003)

    def test_has_non_green_findings(self, result: RunResult) -> None:
        non_green = [f for f in result.findings if f.rag in ("red", "amber")]
        assert len(non_green) >= 4, (
            f"Expected at least 4 non-green findings, got {len(non_green)}"
        )

    def test_findings_have_valid_metadata(self, result: RunResult) -> None:
        for f in result.findings:
            assert f.rule_id in PATCH_DEPS_RULE_IDS
            assert f.evidence_locator
            assert f.pattern_tag.startswith("patch-deps-")

    def test_no_engine_warnings(self, result: RunResult) -> None:
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Good repo: annotations present, separate pools/DBs, ring labels with
# cross-ring dependency (ring 2 → ring 1)
# ---------------------------------------------------------------------------


class TestGoodRepoFindings:
    """deps-blast-radius-good should produce green for 001/002 but amber for 003."""

    @pytest.fixture(scope="class")
    def result(self) -> RunResult:
        return _run_engine(GOOD_REPO)

    def test_no_rules_skipped(self, result: RunResult) -> None:
        rr_map = _rule_results_by_id(result)
        for rule_id in PATCH_DEPS_RULE_IDS:
            assert rule_id in rr_map, f"Rule {rule_id} missing from results"
            assert not rr_map[rule_id].skipped, (
                f"Rule {rule_id} was unexpectedly skipped: {rr_map[rule_id].skip_reason}"
            )

    def test_all_rules_produce_findings(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        for rule_id in PATCH_DEPS_RULE_IDS:
            assert rule_id in by_rule, f"No findings from {rule_id}"

    def test_dependency_declaration_green(self, result: RunResult) -> None:
        """Both workloads have dependency annotations → all green."""
        by_rule = _findings_by_rule(result)
        findings_001 = by_rule["PATCH-DEPS-001"]
        assert all(f.rag == "green" for f in findings_001), (
            f"Expected all green for 001, got {[(f.rag, f.summary) for f in findings_001]}"
        )
        assert len(findings_001) == 2

    def test_shared_fate_green(self, result: RunResult) -> None:
        """Separate node pools and DB hosts → green."""
        by_rule = _findings_by_rule(result)
        findings_002 = by_rule["PATCH-DEPS-002"]
        assert all(f.rag == "green" for f in findings_002), (
            f"Expected all green for 002, got {[(f.rag, f.summary) for f in findings_002]}"
        )

    def test_cross_ring_amber(self, result: RunResult) -> None:
        """payment-service (ring 2) depends on order-service (ring 1) → amber."""
        by_rule = _findings_by_rule(result)
        findings_003 = by_rule["PATCH-DEPS-003"]
        ambers = [f for f in findings_003 if f.rag == "amber"]
        assert len(ambers) >= 1, (
            f"Expected amber for 003, got {[(f.rag, f.summary) for f in findings_003]}"
        )
        assert any("payment-service" in f.summary for f in ambers)
        assert any("order-service" in f.summary for f in ambers)

    def test_findings_have_valid_metadata(self, result: RunResult) -> None:
        for f in result.findings:
            assert f.rule_id in PATCH_DEPS_RULE_IDS
            assert f.evidence_locator
            assert f.pattern_tag.startswith("patch-deps-")

    def test_no_engine_warnings(self, result: RunResult) -> None:
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Cross-cutting: rule-result structure
# ---------------------------------------------------------------------------


class TestRuleResultStructure:
    @pytest.fixture(scope="class")
    def bad_result(self) -> RunResult:
        return _run_engine(BAD_REPO)

    @pytest.fixture(scope="class")
    def good_result(self) -> RunResult:
        return _run_engine(GOOD_REPO)

    def test_rule_result_count(self, bad_result: RunResult, good_result: RunResult) -> None:
        assert len(bad_result.rule_results) == 3
        assert len(good_result.rule_results) == 3

    def test_run_metadata_present(self, bad_result: RunResult, good_result: RunResult) -> None:
        assert bad_result.run_metadata is not None
        assert good_result.run_metadata is not None

    def test_run_metadata_has_rules_run(
        self, bad_result: RunResult, good_result: RunResult
    ) -> None:
        for result in (bad_result, good_result):
            run_ids = set(result.run_metadata.rules_run)
            assert PATCH_DEPS_RULE_IDS <= run_ids
