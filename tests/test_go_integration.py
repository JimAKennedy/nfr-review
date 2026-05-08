"""Go integration tests — full GoAstCollector → rules → Engine pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.go_ast import GoAstCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.ast_bare_except import BareExceptCatchAllRule
from nfr_review.rules.ast_logging_stdout import LoggingToStdoutRule
from nfr_review.rules.go_defer_in_loop import GoDeferInLoopRule
from nfr_review.rules.go_error_ignored import GoErrorIgnoredRule
from nfr_review.rules.go_goroutine_leak import GoGoroutineLeakRule
from nfr_review.rules.go_http_no_timeout import GoHttpNoTimeoutRule

FIXTURES = Path(__file__).parent / "fixtures" / "go-sample-repo"

GO_SPECIFIC_RULES = [
    ("go-error-ignored", GoErrorIgnoredRule),
    ("go-goroutine-leak", GoGoroutineLeakRule),
    ("go-http-no-timeout", GoHttpNoTimeoutRule),
    ("go-defer-in-loop", GoDeferInLoopRule),
]

CROSS_LANGUAGE_RULES = [
    ("bare-except-catch-all", BareExceptCatchAllRule),
    ("logging-to-stdout", LoggingToStdoutRule),
]

ALL_GO_RULE_IDS = {r[0] for r in GO_SPECIFIC_RULES + CROSS_LANGUAGE_RULES}


def _go_registries() -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    cregistry.register("go-ast", GoAstCollector())
    for rule_id, rule_cls in GO_SPECIFIC_RULES + CROSS_LANGUAGE_RULES:
        rregistry.register(rule_id, rule_cls())
    return cregistry, rregistry


def _no_go_registries() -> tuple[Registry, Registry]:
    """Registries with Go rules but NO go-ast collector."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    for rule_id, rule_cls in GO_SPECIFIC_RULES + CROSS_LANGUAGE_RULES:
        rregistry.register(rule_id, rule_cls())
    return cregistry, rregistry


@pytest.fixture()
def full_result() -> RunResult:
    cregistry, rregistry = _go_registries()
    engine = Engine(collectors=cregistry, rules=rregistry)
    return engine.run(target=FIXTURES, config=Config(tech={}))


def _findings_by_rule(result: RunResult, rule_id: str) -> list:
    return [f for f in result.findings if f.rule_id == rule_id]


def _findings_by_file(result: RunResult, filename: str) -> list:
    return [f for f in result.findings if filename in (f.evidence_locator or "")]


# ---------------------------------------------------------------------------
# Full pipeline sanity
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_engine_produces_findings(self, full_result: RunResult) -> None:
        assert len(full_result.findings) > 0

    def test_no_rules_skipped(self, full_result: RunResult) -> None:
        skipped_ids = {e["rule_id"] for e in full_result.run_metadata.rules_skipped}
        for rule_id in ALL_GO_RULE_IDS:
            assert rule_id not in skipped_ids, f"{rule_id} was unexpectedly skipped"

    def test_all_six_rules_ran(self, full_result: RunResult) -> None:
        ran = set(full_result.run_metadata.rules_run)
        assert ALL_GO_RULE_IDS <= ran


# ---------------------------------------------------------------------------
# Per-fixture / per-rule findings
# ---------------------------------------------------------------------------


class TestErrorIgnoredFindings:
    def test_bad_errors_triggers_findings(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "go-error-ignored")
        amber = [f for f in findings if f.rag in ("amber", "red")]
        assert len(amber) >= 1

    def test_good_code_no_error_finding(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "go-error-ignored")
            if "good_code.go" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(findings) == 0


class TestGoroutineLeakFindings:
    def test_bad_goroutines_triggers_findings(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "go-goroutine-leak")
        amber = [f for f in findings if f.rag == "amber"]
        assert len(amber) >= 1

    def test_good_code_goroutine_flagged(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "go-goroutine-leak")
            if "good_code.go" in (f.evidence_locator or "") and f.rag == "amber"
        ]
        assert len(findings) >= 1


class TestHttpNoTimeoutFindings:
    def test_bad_http_triggers_red(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "go-http-no-timeout")
        red = [f for f in findings if f.rag == "red"]
        assert len(red) >= 1

    def test_bad_http_triggers_amber(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "go-http-no-timeout")
        amber = [f for f in findings if f.rag == "amber"]
        assert len(amber) >= 1

    def test_good_code_still_flags_http_get(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "go-http-no-timeout")
            if "good_code.go" in (f.evidence_locator or "") and f.rag == "red"
        ]
        assert len(findings) >= 1


class TestDeferInLoopFindings:
    def test_bad_defer_triggers_findings(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "go-defer-in-loop")
        amber = [f for f in findings if f.rag == "amber"]
        assert len(amber) >= 1

    def test_good_code_no_defer_finding(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "go-defer-in-loop")
            if "good_code.go" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(findings) == 0


class TestLoggingToStdoutFindings:
    def test_bad_logging_triggers_findings(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "logging-to-stdout")
        amber = [f for f in findings if f.rag == "amber"]
        assert len(amber) >= 1

    def test_bad_logging_detects_fmt_calls(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "logging-to-stdout")
            if "bad_logging.go" in (f.evidence_locator or "") and f.rag == "amber"
        ]
        assert len(findings) >= 1


class TestBareExceptFindings:
    def test_bad_exceptions_triggers_findings(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "bare-except-catch-all")
        non_green = [f for f in findings if f.rag in ("amber", "red")]
        assert len(non_green) >= 1

    def test_recover_without_rethrow_is_amber(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "bare-except-catch-all")
            if "bad_exceptions.go" in (f.evidence_locator or "") and f.rag == "amber"
        ]
        assert len(findings) >= 1


# ---------------------------------------------------------------------------
# Good code — only green findings
# ---------------------------------------------------------------------------


class TestGoodCodePatterns:
    def test_good_code_error_handling_green(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "go-error-ignored")
            if "good_code.go" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(findings) == 0

    def test_good_code_defer_outside_loop_green(self, full_result: RunResult) -> None:
        findings = [
            f
            for f in _findings_by_rule(full_result, "go-defer-in-loop")
            if "good_code.go" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(findings) == 0

    def test_good_code_no_defer_or_error_issues(self, full_result: RunResult) -> None:
        for rule_id in ("go-defer-in-loop", "go-error-ignored"):
            findings = [
                f
                for f in _findings_by_rule(full_result, rule_id)
                if "good_code.go" in (f.evidence_locator or "") and f.rag in ("amber", "red")
            ]
            assert len(findings) == 0, f"{rule_id} flagged good_code.go unexpectedly"


# ---------------------------------------------------------------------------
# Tech-gating — Go rules skip when go-ast collector absent
# ---------------------------------------------------------------------------


class TestTechGating:
    @pytest.fixture()
    def no_go_result(self) -> RunResult:
        cregistry, rregistry = _no_go_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        return engine.run(target=FIXTURES, config=Config(tech={}))

    def test_go_specific_rules_skipped_without_collector(
        self, no_go_result: RunResult
    ) -> None:
        skipped_ids = {e["rule_id"] for e in no_go_result.run_metadata.rules_skipped}
        for rule_id, _ in GO_SPECIFIC_RULES:
            assert rule_id in skipped_ids, f"{rule_id} should be skipped without go-ast"

    def test_skip_reason_mentions_go_ast(self, no_go_result: RunResult) -> None:
        for entry in no_go_result.run_metadata.rules_skipped:
            if entry["rule_id"] in {r[0] for r in GO_SPECIFIC_RULES}:
                assert "go-ast" in entry["reason"]

    def test_cross_language_rules_still_skipped_no_evidence(
        self, no_go_result: RunResult
    ) -> None:
        skipped_ids = {e["rule_id"] for e in no_go_result.run_metadata.rules_skipped}
        for rule_id, _ in CROSS_LANGUAGE_RULES:
            assert rule_id in skipped_ids, (
                f"{rule_id} should be skipped with no evidence from any collector"
            )

    def test_no_findings_without_collector(self, no_go_result: RunResult) -> None:
        assert len(no_go_result.findings) == 0
