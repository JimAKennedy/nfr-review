"""Combined integration tests for ALL PATCH-* rules across all 7 guardrail areas.

Runs Engine.run() against the comprehensive fixtures with all 22 PATCH-* rules
enabled simultaneously and verifies:
- Bad fixture triggers findings from all 7 guardrail areas
- Good fixture produces all-green findings
- No duplicate findings
- Finding count sanity checks
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.ci_artifact import CiArtifactCollector
from nfr_review.collectors.k8s_manifest import K8sManifestCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.collectors.service_mesh import ServiceMeshCollector
from nfr_review.collectors.telemetry_config import TelemetryConfigCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.patch_arch_graceful import GracefulShutdownMissingRule
from nfr_review.rules.patch_arch_pdb import PdbCoverageRule
from nfr_review.rules.patch_arch_singleton import SingletonDeploymentRule
from nfr_review.rules.patch_arch_strategy import UpdateStrategyRule
from nfr_review.rules.patch_deps import (
    CrossRingDependencyRule,
    DependencyDeclarationRule,
    SharedFateIndicatorRule,
)
from nfr_review.rules.patch_forward_migration import ForwardOnlyMigrationRule
from nfr_review.rules.patch_health_probes import PatchingProbePresenceRule
from nfr_review.rules.patch_health_startup import StartupProbeMissingRule
from nfr_review.rules.patch_health_termination import TerminationGracePeriodRule
from nfr_review.rules.patch_health_trivial_probe import TrivialProbeRule
from nfr_review.rules.patch_rollback_ci import CiRollbackStageMissingRule
from nfr_review.rules.patch_rollback_docs import RollbackDocsMissingRule
from nfr_review.rules.patch_scope import (
    AcceleratedCadenceRule,
    PatchClassSoakConfigRule,
)
from nfr_review.rules.patch_telem import (
    GoldenSignalEmissionRule,
    MandatoryLabelPresenceRule,
    SyntheticTransactionConfigRule,
)
from nfr_review.rules.patch_traffic import (
    ConnectionDrainingRule,
    FailoverDocumentationRule,
    ProgressiveTrafficShiftingRule,
)

FIXTURES = Path(__file__).parent / "fixtures"
BAD_REPO = FIXTURES / "patching-comprehensive-bad"
GOOD_REPO = FIXTURES / "patching-comprehensive-good"

# All 22 PATCH-* rule IDs organized by guardrail area.
ALL_PATCH_RULE_IDS = {
    # Architecture
    "PATCH-ARCH-001",
    "PATCH-ARCH-002",
    "PATCH-ARCH-003",
    "PATCH-ARCH-004",
    # Health
    "PATCH-HEALTH-001",
    "PATCH-HEALTH-002",
    "PATCH-HEALTH-003",
    "PATCH-HEALTH-004",
    # Rollback
    "PATCH-ROLL-001",
    "PATCH-ROLL-002",
    "PATCH-ROLL-003",
    # Traffic
    "PATCH-TRAFFIC-001",
    "PATCH-TRAFFIC-002",
    "PATCH-TRAFFIC-003",
    # Dependencies
    "PATCH-DEPS-001",
    "PATCH-DEPS-002",
    "PATCH-DEPS-003",
    # Scope
    "PATCH-SCOPE-001",
    "PATCH-SCOPE-002",
    # Telemetry
    "PATCH-TELEM-001",
    "PATCH-TELEM-002",
    "PATCH-TELEM-003",
}

GUARDRAIL_PREFIXES = {
    "ARCH": "PATCH-ARCH",
    "HEALTH": "PATCH-HEALTH",
    "ROLL": "PATCH-ROLL",
    "TRAFFIC": "PATCH-TRAFFIC",
    "DEPS": "PATCH-DEPS",
    "SCOPE": "PATCH-SCOPE",
    "TELEM": "PATCH-TELEM",
}

TOTAL_RULE_COUNT = 22

# PATCH-ROLL-002 requires ci-pipeline evidence from the CiArtifactCollector.
# Neither comprehensive fixture includes CI pipeline files, so this rule
# legitimately skips.  We separate it so assertions remain precise.
EXPECTED_SKIPPED_RULES = {"PATCH-ROLL-002"}
RULES_EXPECTED_TO_RUN = ALL_PATCH_RULE_IDS - EXPECTED_SKIPPED_RULES

# In the good fixture, PATCH-DEPS-002 correctly flags that both deployments
# share the same database host (postgres-payments), producing an amber finding.
# This is intentional design: the good fixture demonstrates that shared-fate
# detection works even in a well-configured repo.
GOOD_FIXTURE_KNOWN_AMBER_RULES = {"PATCH-DEPS-002"}


def _build_registries() -> tuple[Registry, Registry]:
    """Build registries with all 5 collectors and all 22 PATCH-* rules."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    # Collectors: every collector needed by at least one PATCH rule.
    cregistry.register("k8s-manifest", K8sManifestCollector())
    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("ci-artifact", CiArtifactCollector())
    cregistry.register("service-mesh", ServiceMeshCollector())
    cregistry.register("telemetry-config", TelemetryConfigCollector())

    # Architecture (4 rules)
    rregistry.register("PATCH-ARCH-001", SingletonDeploymentRule())
    rregistry.register("PATCH-ARCH-002", GracefulShutdownMissingRule())
    rregistry.register("PATCH-ARCH-003", UpdateStrategyRule())
    rregistry.register("PATCH-ARCH-004", PdbCoverageRule())

    # Health (4 rules)
    rregistry.register("PATCH-HEALTH-001", PatchingProbePresenceRule())
    rregistry.register("PATCH-HEALTH-002", TrivialProbeRule())
    rregistry.register("PATCH-HEALTH-003", StartupProbeMissingRule())
    rregistry.register("PATCH-HEALTH-004", TerminationGracePeriodRule())

    # Rollback (3 rules)
    rregistry.register("PATCH-ROLL-001", RollbackDocsMissingRule())
    rregistry.register("PATCH-ROLL-002", CiRollbackStageMissingRule())
    rregistry.register("PATCH-ROLL-003", ForwardOnlyMigrationRule())

    # Traffic (3 rules)
    rregistry.register("PATCH-TRAFFIC-001", ProgressiveTrafficShiftingRule())
    rregistry.register("PATCH-TRAFFIC-002", FailoverDocumentationRule())
    rregistry.register("PATCH-TRAFFIC-003", ConnectionDrainingRule())

    # Dependencies (3 rules)
    rregistry.register("PATCH-DEPS-001", DependencyDeclarationRule())
    rregistry.register("PATCH-DEPS-002", SharedFateIndicatorRule())
    rregistry.register("PATCH-DEPS-003", CrossRingDependencyRule())

    # Scope (2 rules)
    rregistry.register("PATCH-SCOPE-001", PatchClassSoakConfigRule())
    rregistry.register("PATCH-SCOPE-002", AcceleratedCadenceRule())

    # Telemetry (3 rules)
    rregistry.register("PATCH-TELEM-001", GoldenSignalEmissionRule())
    rregistry.register("PATCH-TELEM-002", MandatoryLabelPresenceRule())
    rregistry.register("PATCH-TELEM-003", SyntheticTransactionConfigRule())

    return cregistry, rregistry


def _run_engine(target: Path) -> RunResult:
    """Run the engine with all collectors and all PATCH-* rules."""
    cregistry, rregistry = _build_registries()
    engine = Engine(collectors=cregistry, rules=rregistry)
    return engine.run(target=target, config=Config())


def _findings_by_rule(result: RunResult) -> dict[str, list]:
    """Group findings by rule_id."""
    by_rule: dict[str, list] = {}
    for f in result.findings:
        by_rule.setdefault(f.rule_id, []).append(f)
    return by_rule


def _rule_results_by_id(result: RunResult) -> dict[str, object]:
    """Index rule results by rule_id."""
    return {rr.rule_id: rr for rr in result.rule_results}


def _findings_for_prefix(result: RunResult, prefix: str) -> list:
    """Return findings whose rule_id starts with the given prefix."""
    return [f for f in result.findings if f.rule_id.startswith(prefix)]


# ---------------------------------------------------------------------------
# Bad fixture: should trigger findings from all guardrail areas
# ---------------------------------------------------------------------------


class TestBadFixture:
    """patching-comprehensive-bad triggers findings from all 7 guardrail areas."""

    @pytest.fixture(scope="class")
    def result(self) -> RunResult:
        return _run_engine(BAD_REPO)

    @pytest.fixture(scope="class")
    def by_rule(self, result: RunResult) -> dict[str, list]:
        return _findings_by_rule(result)

    @pytest.fixture(scope="class")
    def rr_map(self, result: RunResult) -> dict[str, object]:
        return _rule_results_by_id(result)

    # --- All 22 rules should evaluate (none skipped) ---

    def test_all_rules_present_in_results(self, rr_map: dict) -> None:
        """All 22 rules must appear in rule results."""
        for rule_id in ALL_PATCH_RULE_IDS:
            assert rule_id in rr_map, f"Rule {rule_id} missing from results"

    def test_expected_rules_not_skipped(self, rr_map: dict) -> None:
        """All PATCH rules except ROLL-002 should not be skipped."""
        for rule_id in RULES_EXPECTED_TO_RUN:
            rr = rr_map[rule_id]
            assert not rr.skipped, f"Rule {rule_id} was unexpectedly skipped: {rr.skip_reason}"

    def test_roll_002_skipped_no_ci(self, rr_map: dict) -> None:
        """PATCH-ROLL-002 should be skipped (no CI pipeline files in fixture)."""
        rr = rr_map["PATCH-ROLL-002"]
        assert rr.skipped, "PATCH-ROLL-002 should be skipped without CI files"

    def test_rule_result_count(self, result: RunResult) -> None:
        """Exactly 22 rule results should be produced."""
        assert len(result.rule_results) == TOTAL_RULE_COUNT

    # --- Every guardrail area produces at least one finding ---

    def test_all_guardrail_areas_produce_findings(self, result: RunResult) -> None:
        """Each guardrail area with running rules must produce at least one finding."""
        for area, prefix in GUARDRAIL_PREFIXES.items():
            area_findings = _findings_for_prefix(result, prefix)
            assert len(area_findings) >= 1, (
                f"No findings from guardrail area {area} (prefix {prefix})"
            )

    # --- Architecture area: non-green findings ---

    def test_arch_has_non_green_findings(self, result: RunResult) -> None:
        """ARCH area should have non-green findings (singleton, no preStop, etc.)."""
        arch = _findings_for_prefix(result, "PATCH-ARCH")
        non_green = [f for f in arch if f.rag in ("red", "amber")]
        assert len(non_green) >= 2, (
            f"Expected >=2 non-green ARCH findings, got {len(non_green)}: "
            f"{[(f.rule_id, f.rag) for f in arch]}"
        )

    def test_singleton_detected(self, by_rule: dict) -> None:
        """PATCH-ARCH-001 should flag singleton deployment (replicas=1)."""
        findings = by_rule.get("PATCH-ARCH-001", [])
        rags = [(f.rag, f.summary) for f in findings]
        assert any(f.rag in ("red", "amber") for f in findings), (
            f"Expected non-green for singleton, got {rags}"
        )

    def test_no_prestop_detected(self, by_rule: dict) -> None:
        """PATCH-ARCH-002 should flag missing preStop hook."""
        findings = by_rule.get("PATCH-ARCH-002", [])
        rags = [(f.rag, f.summary) for f in findings]
        assert any(f.rag in ("red", "amber") for f in findings), (
            f"Expected non-green for preStop, got {rags}"
        )

    def test_no_strategy_detected(self, by_rule: dict) -> None:
        """PATCH-ARCH-003 should flag missing update strategy."""
        findings = by_rule.get("PATCH-ARCH-003", [])
        rags = [(f.rag, f.summary) for f in findings]
        assert any(f.rag in ("red", "amber") for f in findings), (
            f"Expected non-green for strategy, got {rags}"
        )

    # --- Health area: non-green findings ---

    def test_health_has_non_green_findings(self, result: RunResult) -> None:
        """HEALTH area should have non-green findings."""
        health = _findings_for_prefix(result, "PATCH-HEALTH")
        non_green = [f for f in health if f.rag in ("red", "amber")]
        assert len(non_green) >= 1, (
            f"Expected >=1 non-green HEALTH findings, got {len(non_green)}: "
            f"{[(f.rule_id, f.rag) for f in health]}"
        )

    def test_trivial_probe_detected(self, by_rule: dict) -> None:
        """PATCH-HEALTH-002 should flag trivial tcpSocket readiness probe."""
        findings = by_rule.get("PATCH-HEALTH-002", [])
        rags = [(f.rag, f.summary) for f in findings]
        assert any(f.rag in ("red", "amber") for f in findings), (
            f"Expected non-green for trivial probe, got {rags}"
        )

    def test_low_grace_period_detected(self, by_rule: dict) -> None:
        """PATCH-HEALTH-004 should flag low terminationGracePeriodSeconds."""
        findings = by_rule.get("PATCH-HEALTH-004", [])
        rags = [(f.rag, f.summary) for f in findings]
        assert any(f.rag in ("red", "amber") for f in findings), (
            f"Expected non-green for grace period, got {rags}"
        )

    # --- Rollback area: findings present ---

    def test_rollback_area_findings(self, result: RunResult) -> None:
        """ROLL area should produce findings from ROLL-001 and ROLL-003 (ROLL-002 skipped)."""
        roll = _findings_for_prefix(result, "PATCH-ROLL")
        assert len(roll) >= 2, (
            f"Expected >=2 ROLL findings (ROLL-002 skipped), got {len(roll)}: "
            f"{[(f.rule_id, f.rag) for f in roll]}"
        )

    def test_no_rollback_docs(self, by_rule: dict) -> None:
        """PATCH-ROLL-001 should flag missing rollback documentation."""
        findings = by_rule.get("PATCH-ROLL-001", [])
        rags = [(f.rag, f.summary) for f in findings]
        assert any(f.rag in ("red", "amber") for f in findings), (
            f"Expected non-green for rollback docs, got {rags}"
        )

    # --- Traffic area: findings present ---

    def test_traffic_area_findings(self, result: RunResult) -> None:
        """TRAFFIC area should produce findings from all 3 rules."""
        traffic = _findings_for_prefix(result, "PATCH-TRAFFIC")
        rule_ids = {f.rule_id for f in traffic}
        assert len(rule_ids) == 3, (
            f"Expected findings from all 3 TRAFFIC rules, got {rule_ids}"
        )

    def test_failover_docs_missing(self, by_rule: dict) -> None:
        """PATCH-TRAFFIC-002 should flag missing failover documentation."""
        findings = by_rule.get("PATCH-TRAFFIC-002", [])
        assert any(f.rag == "amber" for f in findings), (
            f"Expected amber for failover docs, got {[(f.rag, f.summary) for f in findings]}"
        )

    # --- Dependencies area: non-green findings ---

    def test_deps_has_non_green_findings(self, result: RunResult) -> None:
        """DEPS area should have non-green findings."""
        deps = _findings_for_prefix(result, "PATCH-DEPS")
        non_green = [f for f in deps if f.rag in ("red", "amber")]
        assert len(non_green) >= 1, (
            f"Expected >=1 non-green DEPS findings, got {len(non_green)}: "
            f"{[(f.rule_id, f.rag) for f in deps]}"
        )

    def test_shared_fate_detected(self, by_rule: dict) -> None:
        """PATCH-DEPS-002 should flag shared nodeSelector or DB host."""
        findings = by_rule.get("PATCH-DEPS-002", [])
        assert any(f.rag == "amber" for f in findings), (
            f"Expected amber for shared fate, got {[(f.rag, f.summary) for f in findings]}"
        )

    def test_cross_ring_detected(self, by_rule: dict) -> None:
        """PATCH-DEPS-003 should detect cross-ring dependency (ring 3 -> ring 0)."""
        findings = by_rule.get("PATCH-DEPS-003", [])
        assert len(findings) >= 1, "Expected findings for cross-ring check"
        # Ring 3 payment-api depends on ring 0 config-server via env var.
        ambers = [f for f in findings if f.rag == "amber"]
        assert len(ambers) >= 1, (
            f"Expected amber for cross-ring, got {[(f.rag, f.summary) for f in findings]}"
        )

    # --- Scope area: findings present ---

    def test_scope_area_findings(self, result: RunResult) -> None:
        """SCOPE area should produce findings (info-level, no config files)."""
        scope = _findings_for_prefix(result, "PATCH-SCOPE")
        assert len(scope) >= 2, f"Expected >=2 SCOPE findings, got {len(scope)}"

    # --- Telemetry area: findings present ---

    def test_telem_area_findings(self, result: RunResult) -> None:
        """TELEM area should produce findings (info-level, no OTel config)."""
        telem = _findings_for_prefix(result, "PATCH-TELEM")
        assert len(telem) >= 3, f"Expected >=3 TELEM findings, got {len(telem)}"

    # --- Cross-cutting: no duplicate findings ---

    def test_no_duplicate_findings(self, result: RunResult) -> None:
        """No two findings should have identical (rule_id, evidence_locator, summary)."""
        seen: set[tuple[str, str, str]] = set()
        for f in result.findings:
            key = (f.rule_id, f.evidence_locator, f.summary)
            assert key not in seen, (
                f"Duplicate finding: rule_id={f.rule_id}, locator={f.evidence_locator}, "
                f"summary={f.summary}"
            )
            seen.add(key)

    # --- Cross-cutting: metadata integrity ---

    def test_findings_have_valid_rag_ratings(self, result: RunResult) -> None:
        """Every finding must have a valid RAG rating."""
        valid_rags = {"red", "amber", "green"}
        for f in result.findings:
            assert f.rag in valid_rags, f"Invalid rag '{f.rag}' on {f.rule_id}"

    def test_findings_have_evidence_locators(self, result: RunResult) -> None:
        """Every finding must have a non-empty evidence_locator."""
        for f in result.findings:
            assert f.evidence_locator, f"Empty evidence_locator on finding from {f.rule_id}"

    def test_findings_have_correct_rule_ids(self, result: RunResult) -> None:
        """Every finding's rule_id must be one of the known PATCH IDs."""
        for f in result.findings:
            assert f.rule_id in ALL_PATCH_RULE_IDS, f"Unexpected rule_id: {f.rule_id}"

    def test_finding_count_sanity(self, result: RunResult) -> None:
        """Total findings should be at least one per running rule (21)."""
        expected_min = len(RULES_EXPECTED_TO_RUN)
        assert len(result.findings) >= expected_min, (
            f"Expected at least {expected_min} findings (one per running rule), "
            f"got {len(result.findings)}"
        )

    def test_no_engine_warnings(self, result: RunResult) -> None:
        """The engine should not produce warnings (all collectors should succeed)."""
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Good fixture: should produce all-green findings (except known amber)
# ---------------------------------------------------------------------------


class TestGoodFixture:
    """patching-comprehensive-good produces GREEN findings for all running rules.

    Known exceptions:
    - PATCH-ROLL-002 skips (no CI pipeline files in fixture).
    - PATCH-DEPS-002 produces amber (shared DB host is correctly detected).
    """

    @pytest.fixture(scope="class")
    def result(self) -> RunResult:
        return _run_engine(GOOD_REPO)

    @pytest.fixture(scope="class")
    def by_rule(self, result: RunResult) -> dict[str, list]:
        return _findings_by_rule(result)

    @pytest.fixture(scope="class")
    def rr_map(self, result: RunResult) -> dict[str, object]:
        return _rule_results_by_id(result)

    # --- All 22 rules should appear; 21 run, 1 skipped ---

    def test_all_rules_present_in_results(self, rr_map: dict) -> None:
        """All 22 rules must appear in rule results."""
        for rule_id in ALL_PATCH_RULE_IDS:
            assert rule_id in rr_map, f"Rule {rule_id} missing from results"

    def test_expected_rules_not_skipped(self, rr_map: dict) -> None:
        """All PATCH rules except ROLL-002 should not be skipped."""
        for rule_id in RULES_EXPECTED_TO_RUN:
            rr = rr_map[rule_id]
            assert not rr.skipped, f"Rule {rule_id} was unexpectedly skipped: {rr.skip_reason}"

    def test_roll_002_skipped_no_ci(self, rr_map: dict) -> None:
        """PATCH-ROLL-002 should be skipped (no CI pipeline files in fixture)."""
        rr = rr_map["PATCH-ROLL-002"]
        assert rr.skipped, "PATCH-ROLL-002 should be skipped without CI files"

    def test_rule_result_count(self, result: RunResult) -> None:
        """Exactly 22 rule results should be produced."""
        assert len(result.rule_results) == TOTAL_RULE_COUNT

    # --- All findings should be green except known amber ---

    def test_findings_are_green_except_known_amber(self, result: RunResult) -> None:
        """Every finding should be GREEN except PATCH-DEPS-002 (shared DB host)."""
        unexpected_non_green = [
            f
            for f in result.findings
            if f.rag != "green" and f.rule_id not in GOOD_FIXTURE_KNOWN_AMBER_RULES
        ]
        if unexpected_non_green:
            details = [(f.rule_id, f.rag, f.summary) for f in unexpected_non_green]
            pytest.fail(
                f"Expected green findings (except known amber), "
                f"but got {len(unexpected_non_green)} unexpected non-green: {details}"
            )

    def test_deps_002_shared_db_amber(self, by_rule: dict) -> None:
        """PATCH-DEPS-002 correctly flags shared DB host as amber."""
        findings = by_rule.get("PATCH-DEPS-002", [])
        ambers = [f for f in findings if f.rag == "amber"]
        assert len(ambers) >= 1, (
            f"Expected amber for shared DB host, got {[(f.rag, f.summary) for f in findings]}"
        )
        assert any("database" in f.summary.lower() for f in ambers), (
            "DEPS-002 amber should mention database/DB"
        )

    # --- Every guardrail area produces at least one finding ---

    def test_all_guardrail_areas_produce_findings(self, result: RunResult) -> None:
        """Each guardrail area with running rules must produce at least one finding."""
        for area, prefix in GUARDRAIL_PREFIXES.items():
            area_findings = _findings_for_prefix(result, prefix)
            assert len(area_findings) >= 1, (
                f"No findings from guardrail area {area} (prefix {prefix})"
            )

    # --- Every running rule produces at least one finding ---

    def test_all_running_rules_produce_findings(self, by_rule: dict) -> None:
        """Each running PATCH rule must produce at least one finding."""
        for rule_id in RULES_EXPECTED_TO_RUN:
            assert rule_id in by_rule, f"No findings from {rule_id}"
            assert len(by_rule[rule_id]) >= 1, f"Empty findings list from {rule_id}"

    # --- Architecture area: green ---

    def test_arch_all_green(self, result: RunResult) -> None:
        """All ARCH findings should be green."""
        arch = _findings_for_prefix(result, "PATCH-ARCH")
        bad = [(f.rule_id, f.rag) for f in arch if f.rag != "green"]
        assert not bad, f"Expected all green ARCH, got {bad}"

    # --- Health area: green ---

    def test_health_all_green(self, result: RunResult) -> None:
        """All HEALTH findings should be green."""
        health = _findings_for_prefix(result, "PATCH-HEALTH")
        bad = [(f.rule_id, f.rag) for f in health if f.rag != "green"]
        assert not bad, f"Expected all green HEALTH, got {bad}"

    # --- Rollback area: green ---

    def test_rollback_all_green(self, result: RunResult) -> None:
        """All ROLL findings should be green (rollback docs present)."""
        roll = _findings_for_prefix(result, "PATCH-ROLL")
        bad = [(f.rule_id, f.rag) for f in roll if f.rag != "green"]
        assert not bad, f"Expected all green ROLL, got {bad}"

    # --- Traffic area: green ---

    def test_traffic_all_green(self, result: RunResult) -> None:
        """All TRAFFIC findings should be green."""
        traffic = _findings_for_prefix(result, "PATCH-TRAFFIC")
        bad = [(f.rule_id, f.rag) for f in traffic if f.rag != "green"]
        assert not bad, f"Expected all green TRAFFIC, got {bad}"

    # --- Dependencies area: green except DEPS-002 (shared DB) ---

    def test_deps_001_003_green(self, result: RunResult) -> None:
        """DEPS-001 and DEPS-003 should be green."""
        deps = _findings_for_prefix(result, "PATCH-DEPS")
        non_002 = [f for f in deps if f.rule_id != "PATCH-DEPS-002"]
        bad = [(f.rule_id, f.rag) for f in non_002 if f.rag != "green"]
        assert not bad, f"Expected green for DEPS-001/003, got {bad}"

    # --- Scope area: green ---

    def test_scope_all_green(self, result: RunResult) -> None:
        """All SCOPE findings should be green."""
        scope = _findings_for_prefix(result, "PATCH-SCOPE")
        bad = [(f.rule_id, f.rag) for f in scope if f.rag != "green"]
        assert not bad, f"Expected all green SCOPE, got {bad}"

    # --- Telemetry area: green ---

    def test_telem_all_green(self, result: RunResult) -> None:
        """All TELEM findings should be green."""
        telem = _findings_for_prefix(result, "PATCH-TELEM")
        bad = [(f.rule_id, f.rag) for f in telem if f.rag != "green"]
        assert not bad, f"Expected all green TELEM, got {bad}"

    # --- Cross-cutting: no duplicate findings ---

    def test_no_duplicate_findings(self, result: RunResult) -> None:
        """No two findings should have identical (rule_id, evidence_locator, summary)."""
        seen: set[tuple[str, str, str]] = set()
        for f in result.findings:
            key = (f.rule_id, f.evidence_locator, f.summary)
            assert key not in seen, (
                f"Duplicate finding: rule_id={f.rule_id}, locator={f.evidence_locator}, "
                f"summary={f.summary}"
            )
            seen.add(key)

    # --- Cross-cutting: metadata integrity ---

    def test_findings_have_valid_rag_ratings(self, result: RunResult) -> None:
        """Every finding must have a valid RAG rating."""
        valid_rags = {"red", "amber", "green"}
        for f in result.findings:
            assert f.rag in valid_rags, f"Invalid rag '{f.rag}' on {f.rule_id}"

    def test_findings_have_evidence_locators(self, result: RunResult) -> None:
        """Every finding must have a non-empty evidence_locator."""
        for f in result.findings:
            assert f.evidence_locator, f"Empty evidence_locator on finding from {f.rule_id}"

    def test_findings_have_correct_rule_ids(self, result: RunResult) -> None:
        """Every finding's rule_id must be one of the known PATCH IDs."""
        for f in result.findings:
            assert f.rule_id in ALL_PATCH_RULE_IDS, f"Unexpected rule_id: {f.rule_id}"

    def test_finding_count_sanity(self, result: RunResult) -> None:
        """Total findings should be at least one per running rule (21)."""
        expected_min = len(RULES_EXPECTED_TO_RUN)
        assert len(result.findings) >= expected_min, (
            f"Expected at least {expected_min} findings (one per running rule), "
            f"got {len(result.findings)}"
        )

    def test_no_engine_warnings(self, result: RunResult) -> None:
        """The engine should not produce warnings (all collectors should succeed)."""
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Cross-cutting: structural integrity across both fixtures
# ---------------------------------------------------------------------------


class TestCrossCuttingStructure:
    """Validate rule result and run metadata across both fixtures."""

    @pytest.fixture(scope="class")
    def bad_result(self) -> RunResult:
        return _run_engine(BAD_REPO)

    @pytest.fixture(scope="class")
    def good_result(self) -> RunResult:
        return _run_engine(GOOD_REPO)

    def test_rule_result_count_matches(
        self, bad_result: RunResult, good_result: RunResult
    ) -> None:
        """Both fixtures should have exactly 22 rule results."""
        assert len(bad_result.rule_results) == TOTAL_RULE_COUNT
        assert len(good_result.rule_results) == TOTAL_RULE_COUNT

    def test_run_metadata_present(self, bad_result: RunResult, good_result: RunResult) -> None:
        """Both runs should produce run metadata."""
        assert bad_result.run_metadata is not None
        assert good_result.run_metadata is not None

    def test_run_metadata_has_expected_rules_run(
        self, bad_result: RunResult, good_result: RunResult
    ) -> None:
        """Run metadata should list 21 PATCH rules as run (ROLL-002 skipped)."""
        for result in (bad_result, good_result):
            assert hasattr(result.run_metadata, "rules_run")
            run_ids = set(result.run_metadata.rules_run)
            assert RULES_EXPECTED_TO_RUN <= run_ids, (
                f"Missing rules from metadata: {RULES_EXPECTED_TO_RUN - run_ids}"
            )
            assert "PATCH-ROLL-002" not in run_ids, (
                "PATCH-ROLL-002 should not appear in rules_run (it is skipped)"
            )

    def test_good_fixture_fewer_non_green_than_bad(
        self, bad_result: RunResult, good_result: RunResult
    ) -> None:
        """The good fixture should have at most 1 non-green finding (DEPS-002), bad many."""
        bad_non_green = [f for f in bad_result.findings if f.rag != "green"]
        good_non_green = [f for f in good_result.findings if f.rag != "green"]
        # Good fixture: only DEPS-002 shared-DB amber expected
        assert len(good_non_green) <= len(GOOD_FIXTURE_KNOWN_AMBER_RULES), (
            f"Good fixture should have at most {len(GOOD_FIXTURE_KNOWN_AMBER_RULES)} "
            f"non-green findings, got {len(good_non_green)}: "
            f"{[(f.rule_id, f.rag) for f in good_non_green]}"
        )
        assert len(bad_non_green) >= 5, (
            f"Bad fixture should have many non-green findings, got {len(bad_non_green)}"
        )

    def test_bad_fixture_has_red_or_amber(self, bad_result: RunResult) -> None:
        """The bad fixture should have at least one red finding (singleton)."""
        reds = [f for f in bad_result.findings if f.rag == "red"]
        ambers = [f for f in bad_result.findings if f.rag == "amber"]
        assert len(reds) + len(ambers) >= 5, (
            f"Expected >=5 red/amber findings, got {len(reds)} red + {len(ambers)} amber"
        )
