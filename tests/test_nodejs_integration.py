"""Node.js integration tests — full NodejsAstCollector -> rules -> Engine pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.nodejs_ast import NodejsAstCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.ast_bare_except import BareExceptCatchAllRule
from nfr_review.rules.ast_logging_stdout import LoggingToStdoutRule
from nfr_review.rules.nodejs_callback_error_ignored import NodejsCallbackErrorIgnoredRule
from nfr_review.rules.nodejs_floating_promise import NodejsFloatingPromiseRule
from nfr_review.rules.nodejs_promise_no_catch import NodejsPromiseNoCatchRule
from nfr_review.rules.nodejs_sync_fs_api import NodejsSyncFsApiRule

FIXTURES = Path(__file__).parent / "fixtures"
NODEJS_REPO = FIXTURES / "nodejs-sample-repo"
PYTHON_REPO = FIXTURES / "python-sample-repo"

NODEJS_SPECIFIC_RULES = [
    ("nodejs-floating-promise", NodejsFloatingPromiseRule),
    ("nodejs-sync-fs-api", NodejsSyncFsApiRule),
    ("nodejs-callback-error-ignored", NodejsCallbackErrorIgnoredRule),
    ("nodejs-promise-no-catch", NodejsPromiseNoCatchRule),
]

CROSS_LANGUAGE_RULES = [
    ("bare-except-catch-all", BareExceptCatchAllRule),
    ("logging-to-stdout", LoggingToStdoutRule),
]

ALL_NODEJS_RULE_IDS = {r[0] for r in NODEJS_SPECIFIC_RULES + CROSS_LANGUAGE_RULES}

R007_FIELDS = {
    "rule_id",
    "rag",
    "severity",
    "summary",
    "recommendation",
    "evidence_locator",
    "collector_name",
    "collector_version",
    "confidence",
    "pattern_tag",
}


def _nodejs_registries() -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    cregistry.register("nodejs-ast", NodejsAstCollector())
    for rule_id, rule_cls in NODEJS_SPECIFIC_RULES + CROSS_LANGUAGE_RULES:
        rregistry.register(rule_id, rule_cls())
    return cregistry, rregistry


def _no_nodejs_registries() -> tuple[Registry, Registry]:
    """Registries with Node.js rules but NO nodejs-ast collector."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    for rule_id, rule_cls in NODEJS_SPECIFIC_RULES + CROSS_LANGUAGE_RULES:
        rregistry.register(rule_id, rule_cls())
    return cregistry, rregistry


def _findings_by_rule(result: RunResult, rule_id: str) -> list:
    return [f for f in result.findings if f.rule_id == rule_id]


def _findings_by_file(result: RunResult, filename: str) -> list:
    return [f for f in result.findings if filename in (f.evidence_locator or "")]


# ---------------------------------------------------------------------------
# Full engine pipeline
# ---------------------------------------------------------------------------


class TestEngineIntegration:
    @pytest.fixture()
    def full_result(self) -> RunResult:
        cregistry, rregistry = _nodejs_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        return engine.run(target=NODEJS_REPO, config=Config(tech={}))

    def test_engine_produces_findings_for_bad_code(self, full_result: RunResult) -> None:
        fired_rule_ids = {f.rule_id for f in full_result.findings}
        for rule_id, _ in NODEJS_SPECIFIC_RULES:
            assert rule_id in fired_rule_ids, f"{rule_id} produced no findings"
        for rule_id, _ in CROSS_LANGUAGE_RULES:
            assert rule_id in fired_rule_ids, f"{rule_id} produced no findings"

    def test_engine_green_for_good_code(self) -> None:
        cregistry, rregistry = _nodejs_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        good_only = NODEJS_REPO / "good_code.js"
        assert good_only.exists()
        result = engine.run(target=NODEJS_REPO, config=Config(tech={}))
        good_findings = [
            f
            for f in result.findings
            if "good_code.js" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(good_findings) == 0, (
            f"good_code.js should have no amber/red findings, got: {good_findings}"
        )

    def test_nodejs_rules_skip_without_nodejs_files(self) -> None:
        cregistry, rregistry = _nodejs_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=PYTHON_REPO, config=Config(tech={}))
        skipped_ids = {e["rule_id"] for e in result.run_metadata.rules_skipped}
        for rule_id, _ in NODEJS_SPECIFIC_RULES:
            assert rule_id in skipped_ids, (
                f"{rule_id} should be skipped when no .js files present"
            )

    def test_nodejs_collector_registered(self) -> None:
        from nfr_review.registry import collector_registry

        assert "nodejs-ast" in collector_registry

    def test_all_nodejs_rules_registered(self) -> None:
        from nfr_review.registry import rule_registry

        for rule_id, _ in NODEJS_SPECIFIC_RULES:
            assert rule_id in rule_registry, f"{rule_id} not in rule_registry"

    def test_evidence_payload_structure(self, full_result: RunResult) -> None:
        cregistry, _ = _nodejs_registries()
        engine_evidence: list = []
        collector = cregistry.get("nodejs-ast")
        produced = collector.collect(NODEJS_REPO, Config(tech={}))
        engine_evidence.extend(produced)
        assert len(engine_evidence) > 0
        for ev in engine_evidence:
            assert ev.kind == "nodejs-ast-file"
            assert ev.collector_name == "nodejs-ast"
            assert "file_path" in ev.payload
            assert "catch_blocks" in ev.payload
            assert "log_statements" in ev.payload
            assert "functions" in ev.payload
            assert "await_expressions" in ev.payload
            assert "promise_chains" in ev.payload
            assert "sync_calls" in ev.payload
            assert "callback_patterns" in ev.payload

    def test_finding_field_compliance(self, full_result: RunResult) -> None:
        assert len(full_result.findings) > 0
        for finding in full_result.findings:
            finding_dict = finding.model_dump()
            for field in R007_FIELDS:
                assert field in finding_dict, f"Missing R007 field: {field}"
                assert finding_dict[field] is not None, f"R007 field {field} is None"

    def test_no_rules_skipped_with_nodejs_evidence(self, full_result: RunResult) -> None:
        ran = set(full_result.run_metadata.rules_run)
        assert ALL_NODEJS_RULE_IDS <= ran


# ---------------------------------------------------------------------------
# Cross-language rules with Node.js evidence
# ---------------------------------------------------------------------------


class TestCrossLanguageWithNodejs:
    @pytest.fixture()
    def full_result(self) -> RunResult:
        cregistry, rregistry = _nodejs_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        return engine.run(target=NODEJS_REPO, config=Config(tech={}))

    def test_bare_except_detects_bare_catch(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "bare-except-catch-all")
        amber = [f for f in findings if f.rag == "amber"]
        assert len(amber) >= 1, "Expected amber finding for bare catch in JS"

    def test_logging_stdout_detects_console_log(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "logging-to-stdout")
        amber = [f for f in findings if f.rag == "amber"]
        assert len(amber) >= 1, "Expected amber finding for console.log"

    def test_cross_language_rules_still_work_for_python(self) -> None:
        from nfr_review.collectors.python_ast import PythonAstCollector

        cregistry: Registry = Registry("collector")
        rregistry: Registry = Registry("rule")
        cregistry.register("python-ast", PythonAstCollector())
        rregistry.register("bare-except-catch-all", BareExceptCatchAllRule())
        rregistry.register("logging-to-stdout", LoggingToStdoutRule())
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=PYTHON_REPO, config=Config(tech={}))
        findings = result.findings
        assert len(findings) > 0, "Cross-language rules should produce Python findings"

    def test_cross_language_rules_still_work_for_go(self) -> None:
        from nfr_review.collectors.go_ast import GoAstCollector

        go_repo = FIXTURES / "go-sample-repo"
        if not go_repo.exists():
            pytest.skip("go-sample-repo fixture not available")
        cregistry: Registry = Registry("collector")
        rregistry: Registry = Registry("rule")
        cregistry.register("go-ast", GoAstCollector())
        rregistry.register("bare-except-catch-all", BareExceptCatchAllRule())
        rregistry.register("logging-to-stdout", LoggingToStdoutRule())
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=go_repo, config=Config(tech={}))
        findings = result.findings
        assert len(findings) > 0, "Cross-language rules should produce Go findings"


# ---------------------------------------------------------------------------
# Tech-gating — Node.js rules skip when no .js files / no collector
# ---------------------------------------------------------------------------


class TestTechGating:
    def test_rules_skip_when_no_js_files(self) -> None:
        cregistry, rregistry = _nodejs_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=PYTHON_REPO, config=Config(tech={}))
        skipped_ids = {e["rule_id"] for e in result.run_metadata.rules_skipped}
        for rule_id, _ in NODEJS_SPECIFIC_RULES:
            assert rule_id in skipped_ids, (
                f"{rule_id} should be skipped for a Python-only repo"
            )

    def test_rules_fire_when_js_files_present(self) -> None:
        cregistry, rregistry = _nodejs_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=NODEJS_REPO, config=Config(tech={}))
        ran = set(result.run_metadata.rules_run)
        for rule_id, _ in NODEJS_SPECIFIC_RULES:
            assert rule_id in ran, f"{rule_id} should have run for Node.js repo"

    def test_skip_reason_mentions_nodejs_ast(self) -> None:
        cregistry, rregistry = _no_nodejs_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=NODEJS_REPO, config=Config(tech={}))
        for entry in result.run_metadata.rules_skipped:
            if entry["rule_id"] in {r[0] for r in NODEJS_SPECIFIC_RULES}:
                assert "nodejs-ast" in entry["reason"]

    def test_no_findings_without_collector(self) -> None:
        cregistry, rregistry = _no_nodejs_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=NODEJS_REPO, config=Config(tech={}))
        nodejs_findings = [
            f for f in result.findings if f.rule_id in {r[0] for r in NODEJS_SPECIFIC_RULES}
        ]
        assert len(nodejs_findings) == 0
