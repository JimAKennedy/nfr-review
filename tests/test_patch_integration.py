"""Integration tests for the full Engine.run() pipeline against PATCH-* rule fixtures.

Verifies that the k8s-patch-unready fixture produces non-green findings for all 11
PATCH rules, and the k8s-patch-ready fixture produces only green findings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.ci_artifact import CiArtifactCollector
from nfr_review.collectors.k8s_manifest import K8sManifestCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.patch_arch_graceful import GracefulShutdownMissingRule
from nfr_review.rules.patch_arch_pdb import PdbCoverageRule
from nfr_review.rules.patch_arch_singleton import SingletonDeploymentRule
from nfr_review.rules.patch_arch_strategy import UpdateStrategyRule
from nfr_review.rules.patch_forward_migration import ForwardOnlyMigrationRule
from nfr_review.rules.patch_health_probes import PatchingProbePresenceRule
from nfr_review.rules.patch_health_startup import StartupProbeMissingRule
from nfr_review.rules.patch_health_termination import TerminationGracePeriodRule
from nfr_review.rules.patch_health_trivial_probe import TrivialProbeRule
from nfr_review.rules.patch_rollback_ci import CiRollbackStageMissingRule
from nfr_review.rules.patch_rollback_docs import RollbackDocsMissingRule

FIXTURES = Path(__file__).parent / "fixtures"
UNREADY_REPO = FIXTURES / "k8s-patch-unready"
READY_REPO = FIXTURES / "k8s-patch-ready"

ALL_PATCH_RULE_IDS = {
    # PATCH-ARCH
    "PATCH-ARCH-001",
    "PATCH-ARCH-002",
    "PATCH-ARCH-003",
    "PATCH-ARCH-004",
    # PATCH-HEALTH
    "PATCH-HEALTH-001",
    "PATCH-HEALTH-002",
    "PATCH-HEALTH-003",
    "PATCH-HEALTH-004",
    # PATCH-ROLL
    "PATCH-ROLL-001",
    "PATCH-ROLL-002",
    "PATCH-ROLL-003",
}

ARCH_PREFIX = "PATCH-ARCH"
HEALTH_PREFIX = "PATCH-HEALTH"
ROLL_PREFIX = "PATCH-ROLL"


def _patch_registries() -> tuple[Registry, Registry]:
    """Build registries with the 3 collectors and 11 PATCH rules needed."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("k8s-manifest", K8sManifestCollector())
    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("ci-artifact", CiArtifactCollector())

    rregistry.register("PATCH-ARCH-001", SingletonDeploymentRule())
    rregistry.register("PATCH-ARCH-002", GracefulShutdownMissingRule())
    rregistry.register("PATCH-ARCH-003", UpdateStrategyRule())
    rregistry.register("PATCH-ARCH-004", PdbCoverageRule())
    rregistry.register("PATCH-HEALTH-001", PatchingProbePresenceRule())
    rregistry.register("PATCH-HEALTH-002", TrivialProbeRule())
    rregistry.register("PATCH-HEALTH-003", StartupProbeMissingRule())
    rregistry.register("PATCH-HEALTH-004", TerminationGracePeriodRule())
    rregistry.register("PATCH-ROLL-001", RollbackDocsMissingRule())
    rregistry.register("PATCH-ROLL-002", CiRollbackStageMissingRule())
    rregistry.register("PATCH-ROLL-003", ForwardOnlyMigrationRule())

    return cregistry, rregistry


def _run_engine(target: Path) -> RunResult:
    """Run the engine with kubernetes tech enabled against the target."""
    cregistry, rregistry = _patch_registries()
    engine = Engine(collectors=cregistry, rules=rregistry)
    cfg = Config(tech={"kubernetes": True})
    return engine.run(target=target, config=cfg)


def _findings_by_rule(result: RunResult) -> dict[str, list]:
    """Group findings by rule_id."""
    by_rule: dict[str, list] = {}
    for f in result.findings:
        by_rule.setdefault(f.rule_id, []).append(f)
    return by_rule


def _rule_results_by_id(result: RunResult) -> dict[str, object]:
    """Index rule results by rule_id."""
    return {rr.rule_id: rr for rr in result.rule_results}


# ---------------------------------------------------------------------------
# Unready fixture: should produce non-green findings
# ---------------------------------------------------------------------------


class TestUnreadyFixture:
    """k8s-patch-unready fixture must trigger findings from all 11 PATCH rules."""

    @pytest.fixture(scope="class")
    def result(self) -> RunResult:
        return _run_engine(UNREADY_REPO)

    def test_no_rules_skipped(self, result: RunResult) -> None:
        """All 11 rules should evaluate (none skipped)."""
        rr_map = _rule_results_by_id(result)
        for rule_id in ALL_PATCH_RULE_IDS:
            assert rule_id in rr_map, f"Rule {rule_id} missing from results"
            assert not rr_map[rule_id].skipped, (
                f"Rule {rule_id} was unexpectedly skipped: {rr_map[rule_id].skip_reason}"
            )

    def test_all_patch_rules_produce_findings(self, result: RunResult) -> None:
        """Every PATCH rule must produce at least one finding."""
        by_rule = _findings_by_rule(result)
        for rule_id in ALL_PATCH_RULE_IDS:
            assert rule_id in by_rule, f"No findings from {rule_id}"
            assert len(by_rule[rule_id]) >= 1, f"No findings from {rule_id}"

    def test_arch_prefix_findings_present(self, result: RunResult) -> None:
        """There should be findings with PATCH-ARCH prefix."""
        arch_findings = [f for f in result.findings if f.rule_id.startswith(ARCH_PREFIX)]
        assert len(arch_findings) >= 4, (
            f"Expected at least 4 PATCH-ARCH findings, got {len(arch_findings)}"
        )

    def test_health_prefix_findings_present(self, result: RunResult) -> None:
        """There should be findings with PATCH-HEALTH prefix."""
        health_findings = [f for f in result.findings if f.rule_id.startswith(HEALTH_PREFIX)]
        assert len(health_findings) >= 4, (
            f"Expected at least 4 PATCH-HEALTH findings, got {len(health_findings)}"
        )

    def test_roll_prefix_findings_present(self, result: RunResult) -> None:
        """There should be findings with PATCH-ROLL prefix."""
        roll_findings = [f for f in result.findings if f.rule_id.startswith(ROLL_PREFIX)]
        assert len(roll_findings) >= 3, (
            f"Expected at least 3 PATCH-ROLL findings, got {len(roll_findings)}"
        )

    def test_unready_has_non_green_findings(self, result: RunResult) -> None:
        """The unready fixture should have at least one red or amber finding per prefix."""
        by_rule = _findings_by_rule(result)
        for prefix in (ARCH_PREFIX, HEALTH_PREFIX, ROLL_PREFIX):
            prefix_findings = [
                f for rule_id, fs in by_rule.items() if rule_id.startswith(prefix) for f in fs
            ]
            non_green = [f for f in prefix_findings if f.rag in ("red", "amber")]
            assert len(non_green) >= 1, (
                f"Expected at least 1 non-green finding for {prefix}, "
                f"got rags: {[f.rag for f in prefix_findings]}"
            )

    def test_findings_have_correct_rule_ids(self, result: RunResult) -> None:
        """Every finding's rule_id must be one of the known PATCH IDs."""
        for f in result.findings:
            assert f.rule_id in ALL_PATCH_RULE_IDS, f"Unexpected rule_id: {f.rule_id}"

    def test_findings_have_valid_rag_ratings(self, result: RunResult) -> None:
        """Every finding must have a valid RAG rating."""
        valid_rags = {"red", "amber", "green", "skipped"}
        for f in result.findings:
            assert f.rag in valid_rags, f"Invalid rag '{f.rag}' on {f.rule_id}"

    def test_findings_have_evidence_locators(self, result: RunResult) -> None:
        """Every finding must have a non-empty evidence_locator."""
        for f in result.findings:
            assert f.evidence_locator, f"Empty evidence_locator on finding from {f.rule_id}"

    def test_no_engine_warnings(self, result: RunResult) -> None:
        """The engine should not produce warnings (all collectors should succeed)."""
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Ready fixture: should produce only green findings for all PATCH rules
# ---------------------------------------------------------------------------


class TestReadyFixture:
    """k8s-patch-ready fixture must produce only GREEN findings for all PATCH rules."""

    @pytest.fixture(scope="class")
    def result(self) -> RunResult:
        return _run_engine(READY_REPO)

    def test_no_rules_skipped(self, result: RunResult) -> None:
        """All 11 rules should evaluate (none skipped)."""
        rr_map = _rule_results_by_id(result)
        for rule_id in ALL_PATCH_RULE_IDS:
            assert rule_id in rr_map, f"Rule {rule_id} missing from results"
            assert not rr_map[rule_id].skipped, (
                f"Rule {rule_id} was unexpectedly skipped: {rr_map[rule_id].skip_reason}"
            )

    def test_all_patch_rules_produce_findings(self, result: RunResult) -> None:
        """Every PATCH rule must produce at least one finding."""
        by_rule = _findings_by_rule(result)
        for rule_id in ALL_PATCH_RULE_IDS:
            assert rule_id in by_rule, f"No findings from {rule_id}"

    def test_all_findings_are_green(self, result: RunResult) -> None:
        """Every finding should be GREEN for the ready fixture."""
        non_green = [f for f in result.findings if f.rag != "green"]
        if non_green:
            details = [(f.rule_id, f.rag, f.summary) for f in non_green]
            pytest.fail(
                f"Expected all green findings, but got {len(non_green)} non-green: {details}"
            )

    def test_findings_have_correct_rule_ids(self, result: RunResult) -> None:
        """Every finding's rule_id must be one of the known PATCH IDs."""
        for f in result.findings:
            assert f.rule_id in ALL_PATCH_RULE_IDS, f"Unexpected rule_id: {f.rule_id}"

    def test_findings_have_valid_rag_ratings(self, result: RunResult) -> None:
        """Every finding must have a valid RAG rating."""
        for f in result.findings:
            assert f.rag == "green", f"Expected green, got '{f.rag}' on {f.rule_id}"

    def test_findings_have_evidence_locators(self, result: RunResult) -> None:
        """Every finding must have a non-empty evidence_locator."""
        for f in result.findings:
            assert f.evidence_locator, f"Empty evidence_locator on finding from {f.rule_id}"

    def test_no_engine_warnings(self, result: RunResult) -> None:
        """The engine should not produce warnings (all collectors should succeed)."""
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Cross-cutting: rule-result structure integrity
# ---------------------------------------------------------------------------


class TestRuleResultStructure:
    """Validate the structure of rule results from both fixtures."""

    @pytest.fixture(scope="class")
    def unready_result(self) -> RunResult:
        return _run_engine(UNREADY_REPO)

    @pytest.fixture(scope="class")
    def ready_result(self) -> RunResult:
        return _run_engine(READY_REPO)

    def test_rule_result_count_matches(
        self, unready_result: RunResult, ready_result: RunResult
    ) -> None:
        """Both fixtures should have exactly 11 rule results."""
        assert len(unready_result.rule_results) == 11
        assert len(ready_result.rule_results) == 11

    def test_run_metadata_present(
        self, unready_result: RunResult, ready_result: RunResult
    ) -> None:
        """Both runs should produce run metadata."""
        assert unready_result.run_metadata is not None
        assert ready_result.run_metadata is not None

    def test_run_metadata_has_rules_run(
        self, unready_result: RunResult, ready_result: RunResult
    ) -> None:
        """Run metadata should list all 11 PATCH rules as run (not skipped)."""
        for result in (unready_result, ready_result):
            assert hasattr(result.run_metadata, "rules_run")
            run_ids = set(result.run_metadata.rules_run)
            assert ALL_PATCH_RULE_IDS <= run_ids, (
                f"Missing rules from metadata: {ALL_PATCH_RULE_IDS - run_ids}"
            )
