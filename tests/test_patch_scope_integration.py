"""Integration tests for PATCH-SCOPE rules through the full Engine.run() pipeline.

Runs against patch-scope fixture repos and verifies that:
- patch-scope-good produces green findings (config present, accelerated cadence declared).
- patch-scope-bad produces info-level findings (no config files detected).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.patch_scope import (
    AcceleratedCadenceRule,
    PatchClassSoakConfigRule,
)

FIXTURES = Path(__file__).parent / "fixtures"
GOOD_REPO = FIXTURES / "patch-scope-good"
BAD_REPO = FIXTURES / "patch-scope-bad"

PATCH_SCOPE_RULE_IDS = {
    "PATCH-SCOPE-001",
    "PATCH-SCOPE-002",
}


def _scope_registries() -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("repo-structure", RepoStructureCollector())

    rregistry.register("PATCH-SCOPE-001", PatchClassSoakConfigRule())
    rregistry.register("PATCH-SCOPE-002", AcceleratedCadenceRule())

    return cregistry, rregistry


def _run_engine(target: Path) -> RunResult:
    cregistry, rregistry = _scope_registries()
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
# Good repo: patching-policy.yaml with 5 patch classes incl. critical-security
# ---------------------------------------------------------------------------


class TestGoodRepoFindings:
    """patch-scope-good has config present → green findings for both rules."""

    @pytest.fixture(scope="class")
    def result(self) -> RunResult:
        return _run_engine(GOOD_REPO)

    def test_no_rules_skipped(self, result: RunResult) -> None:
        rr_map = _rule_results_by_id(result)
        for rule_id in PATCH_SCOPE_RULE_IDS:
            assert rule_id in rr_map, f"Rule {rule_id} missing from results"
            assert not rr_map[rule_id].skipped, (
                f"Rule {rule_id} was unexpectedly skipped: {rr_map[rule_id].skip_reason}"
            )

    def test_all_rules_produce_findings(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        for rule_id in PATCH_SCOPE_RULE_IDS:
            assert rule_id in by_rule, f"No findings from {rule_id}"

    def test_soak_config_green(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        findings_001 = by_rule["PATCH-SCOPE-001"]
        assert all(f.rag == "green" for f in findings_001), (
            f"Expected all green for 001, got {[(f.rag, f.summary) for f in findings_001]}"
        )
        assert any("patching-policy" in f.summary.lower() for f in findings_001)

    def test_accelerated_cadence_green(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        findings_002 = by_rule["PATCH-SCOPE-002"]
        assert all(f.rag == "green" for f in findings_002), (
            f"Expected all green for 002, got {[(f.rag, f.summary) for f in findings_002]}"
        )

    def test_findings_have_valid_metadata(self, result: RunResult) -> None:
        for f in result.findings:
            assert f.rule_id in PATCH_SCOPE_RULE_IDS
            assert f.evidence_locator
            assert f.pattern_tag.startswith("patch-scope-")

    def test_no_engine_warnings(self, result: RunResult) -> None:
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Bad repo: no config files → info-level green findings
# ---------------------------------------------------------------------------


class TestBadRepoFindings:
    """patch-scope-bad has no config → info-level findings for both rules."""

    @pytest.fixture(scope="class")
    def result(self) -> RunResult:
        return _run_engine(BAD_REPO)

    def test_no_rules_skipped(self, result: RunResult) -> None:
        rr_map = _rule_results_by_id(result)
        for rule_id in PATCH_SCOPE_RULE_IDS:
            assert rule_id in rr_map, f"Rule {rule_id} missing from results"
            assert not rr_map[rule_id].skipped, (
                f"Rule {rule_id} was unexpectedly skipped: {rr_map[rule_id].skip_reason}"
            )

    def test_all_rules_produce_findings(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        for rule_id in PATCH_SCOPE_RULE_IDS:
            assert rule_id in by_rule, f"No findings from {rule_id}"

    def test_soak_config_info(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        findings_001 = by_rule["PATCH-SCOPE-001"]
        assert all(f.rag == "green" for f in findings_001)
        assert all(f.severity == "info" for f in findings_001)
        assert any("no patch-class" in f.summary.lower() for f in findings_001)

    def test_accelerated_cadence_info(self, result: RunResult) -> None:
        by_rule = _findings_by_rule(result)
        findings_002 = by_rule["PATCH-SCOPE-002"]
        assert all(f.rag == "green" for f in findings_002)
        assert all(f.severity == "info" for f in findings_002)
        assert any("not applicable" in f.summary.lower() for f in findings_002)

    def test_no_amber_or_red_findings(self, result: RunResult) -> None:
        non_green = [f for f in result.findings if f.rag in ("red", "amber")]
        assert len(non_green) == 0, (
            f"Expected no non-green findings, got {[(f.rag, f.summary) for f in non_green]}"
        )

    def test_findings_have_valid_metadata(self, result: RunResult) -> None:
        for f in result.findings:
            assert f.rule_id in PATCH_SCOPE_RULE_IDS
            assert f.evidence_locator
            assert f.pattern_tag.startswith("patch-scope-")

    def test_no_engine_warnings(self, result: RunResult) -> None:
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Cross-cutting: rule-result structure
# ---------------------------------------------------------------------------


class TestRuleResultStructure:
    @pytest.fixture(scope="class")
    def good_result(self) -> RunResult:
        return _run_engine(GOOD_REPO)

    @pytest.fixture(scope="class")
    def bad_result(self) -> RunResult:
        return _run_engine(BAD_REPO)

    def test_rule_result_count(self, good_result: RunResult, bad_result: RunResult) -> None:
        assert len(good_result.rule_results) == 2
        assert len(bad_result.rule_results) == 2

    def test_run_metadata_has_rules_run(
        self, good_result: RunResult, bad_result: RunResult
    ) -> None:
        for result in (good_result, bad_result):
            run_ids = set(result.run_metadata.rules_run)
            assert PATCH_SCOPE_RULE_IDS <= run_ids
