"""Rust integration tests — full RustAstCollector -> rules -> Engine pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.rust_ast import RustAstCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.rust_blocking_in_async import RustBlockingInAsyncRule
from nfr_review.rules.rust_http_no_timeout import RustHttpNoTimeoutRule
from nfr_review.rules.rust_mutex_lock_unwrap import RustMutexLockUnwrapRule
from nfr_review.rules.rust_unbounded_spawn_in_loop import RustUnboundedSpawnInLoopRule
from nfr_review.rules.rust_unwrap_expect import RustUnwrapExpectRule

FIXTURES = Path(__file__).parent / "fixtures" / "rust-sample-repo"

RUST_RULES = [
    ("rust-unwrap-expect", RustUnwrapExpectRule),
    ("rust-mutex-lock-unwrap", RustMutexLockUnwrapRule),
    ("rust-http-no-timeout", RustHttpNoTimeoutRule),
    ("rust-blocking-in-async", RustBlockingInAsyncRule),
    ("rust-unbounded-spawn-in-loop", RustUnboundedSpawnInLoopRule),
]

ALL_RUST_RULE_IDS = {r[0] for r in RUST_RULES}


def _rust_registries() -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    cregistry.register("rust-ast", RustAstCollector())
    for rule_id, rule_cls in RUST_RULES:
        rregistry.register(rule_id, rule_cls())
    return cregistry, rregistry


def _no_rust_registries() -> tuple[Registry, Registry]:
    """Registries with rust rules but NO rust-ast collector."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    for rule_id, rule_cls in RUST_RULES:
        rregistry.register(rule_id, rule_cls())
    return cregistry, rregistry


@pytest.fixture()
def full_result() -> RunResult:
    cregistry, rregistry = _rust_registries()
    engine = Engine(collectors=cregistry, rules=rregistry)
    return engine.run(target=FIXTURES, config=Config(tech={"rust": True}))


def _findings_by_rule(result: RunResult, rule_id: str) -> list:
    return [f for f in result.findings if f.rule_id == rule_id]


class TestFullPipeline:
    def test_engine_produces_findings(self, full_result: RunResult) -> None:
        assert len(full_result.findings) > 0

    def test_no_rules_skipped(self, full_result: RunResult) -> None:
        skipped_ids = {e["rule_id"] for e in full_result.run_metadata.rules_skipped}
        for rule_id in ALL_RUST_RULE_IDS:
            assert rule_id not in skipped_ids, f"{rule_id} was unexpectedly skipped"

    def test_all_five_rules_ran(self, full_result: RunResult) -> None:
        ran = set(full_result.run_metadata.rules_run)
        assert ALL_RUST_RULE_IDS <= ran


class TestUnwrapExpectFindings:
    def test_bad_unwrap_triggers_findings(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "rust-unwrap-expect")
        amber = [f for f in findings if f.rag == "amber"]
        assert len(amber) >= 2  # bad_unwrap.rs has 2 non-test unwrap/expect calls

    def test_good_code_no_unwrap_finding(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "rust-unwrap-expect")
            if "good_code.rs" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(findings) == 0

    def test_test_module_unwrap_not_flagged(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "rust-unwrap-expect")
            if "bad_unwrap.rs" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(findings) == 2  # not 3 — the #[test] fn's unwrap is excluded


class TestMutexLockUnwrapFindings:
    def test_bad_mutex_triggers_findings(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "rust-mutex-lock-unwrap")
        amber = [f for f in findings if f.rag == "amber"]
        assert len(amber) == 3

    def test_good_code_no_mutex_finding(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "rust-mutex-lock-unwrap")
            if "good_code.rs" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(findings) == 0


class TestHttpNoTimeoutFindings:
    def test_bad_http_triggers_red_and_amber(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "rust-http-no-timeout")
        red = [f for f in findings if f.rag == "red"]
        amber = [f for f in findings if f.rag == "amber"]
        assert len(red) >= 1
        assert len(amber) >= 1

    def test_good_code_no_http_finding(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "rust-http-no-timeout")
            if "good_code.rs" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(findings) == 0


class TestBlockingInAsyncFindings:
    def test_bad_async_blocking_triggers_findings(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "rust-blocking-in-async")
        amber = [f for f in findings if f.rag == "amber"]
        assert len(amber) == 2

    def test_good_code_no_blocking_finding(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "rust-blocking-in-async")
            if "good_code.rs" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(findings) == 0


class TestUnboundedSpawnFindings:
    def test_bad_spawn_triggers_one_finding(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "rust-unbounded-spawn-in-loop")
            if "bad_spawn.rs" in (f.evidence_locator or "") and f.rag == "amber"
        ]
        assert len(findings) == 1  # only the in-loop spawn, not spawn_once()

    def test_good_code_no_spawn_finding(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "rust-unbounded-spawn-in-loop")
            if "good_code.rs" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(findings) == 0


class TestGoodCodePatterns:
    def test_good_code_all_rules_clean(self, full_result: RunResult) -> None:
        for rule_id, _ in RUST_RULES:
            findings = [
                f
                for f in _findings_by_rule(full_result, rule_id)
                if "good_code.rs" in (f.evidence_locator or "") and f.rag in ("amber", "red")
            ]
            assert findings == [], f"{rule_id} flagged good_code.rs unexpectedly"


class TestTechGating:
    @pytest.fixture()
    def no_rust_result(self) -> RunResult:
        cregistry, rregistry = _no_rust_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        return engine.run(target=FIXTURES, config=Config(tech={"rust": True}))

    def test_rust_rules_skipped_without_collector(self, no_rust_result: RunResult) -> None:
        skipped_ids = {e["rule_id"] for e in no_rust_result.run_metadata.rules_skipped}
        for rule_id, _ in RUST_RULES:
            assert rule_id in skipped_ids, f"{rule_id} should be skipped without rust-ast"

    def test_no_findings_without_collector(self, no_rust_result: RunResult) -> None:
        assert len(no_rust_result.findings) == 0

    @pytest.fixture()
    def tech_undeclared_result(self) -> RunResult:
        cregistry, rregistry = _rust_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        return engine.run(target=FIXTURES, config=Config(tech={}))

    def test_rules_skipped_when_tech_not_declared(
        self, tech_undeclared_result: RunResult
    ) -> None:
        """required_tech=["rust"] means these rules must skip if config.tech doesn't
        declare rust, even though the rust-ast collector itself ran successfully."""
        skipped_ids = {e["rule_id"] for e in tech_undeclared_result.run_metadata.rules_skipped}
        for rule_id, _ in RUST_RULES:
            assert rule_id in skipped_ids

    def test_skip_reason_mentions_tech_not_declared(
        self, tech_undeclared_result: RunResult
    ) -> None:
        for entry in tech_undeclared_result.run_metadata.rules_skipped:
            if entry["rule_id"] in ALL_RUST_RULE_IDS:
                assert "tech not declared" in entry["reason"]
