"""C# integration tests — full CSharpAstCollector -> rules -> Engine pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.csharp_ast import CSharpAstCollector
from nfr_review.config import Config
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.ast_bare_except import BareExceptCatchAllRule
from nfr_review.rules.ast_logging_stdout import LoggingToStdoutRule
from nfr_review.rules.csharp_async_void import CSharpAsyncVoidRule
from nfr_review.rules.csharp_blocking_async import CSharpBlockingAsyncRule
from nfr_review.rules.csharp_configure_await import CSharpConfigureAwaitRule
from nfr_review.rules.csharp_disposable_no_using import CSharpDisposableNoUsingRule

FIXTURES = Path(__file__).parent / "fixtures"
CSHARP_REPO = FIXTURES / "csharp-sample-repo"
PYTHON_REPO = FIXTURES / "python-sample-repo"

CSHARP_SPECIFIC_RULES = [
    ("csharp-async-void", CSharpAsyncVoidRule),
    ("csharp-blocking-async", CSharpBlockingAsyncRule),
    ("csharp-configure-await", CSharpConfigureAwaitRule),
    ("csharp-disposable-no-using", CSharpDisposableNoUsingRule),
]

CROSS_LANGUAGE_RULES = [
    ("bare-except-catch-all", BareExceptCatchAllRule),
    ("logging-to-stdout", LoggingToStdoutRule),
]

ALL_CSHARP_RULE_IDS = {r[0] for r in CSHARP_SPECIFIC_RULES + CROSS_LANGUAGE_RULES}

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


def _csharp_registries() -> tuple[Registry, Registry]:
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    cregistry.register("csharp-ast", CSharpAstCollector())
    for rule_id, rule_cls in CSHARP_SPECIFIC_RULES + CROSS_LANGUAGE_RULES:
        rregistry.register(rule_id, rule_cls())
    return cregistry, rregistry


def _no_csharp_registries() -> tuple[Registry, Registry]:
    """Registries with C# rules but NO csharp-ast collector."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")
    for rule_id, rule_cls in CSHARP_SPECIFIC_RULES + CROSS_LANGUAGE_RULES:
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
        cregistry, rregistry = _csharp_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        return engine.run(target=CSHARP_REPO, config=Config(tech={}))

    def test_engine_produces_findings_for_bad_code(self, full_result: RunResult) -> None:
        fired_rule_ids = {f.rule_id for f in full_result.findings}
        for rule_id, _ in CSHARP_SPECIFIC_RULES:
            assert rule_id in fired_rule_ids, f"{rule_id} produced no findings"
        for rule_id, _ in CROSS_LANGUAGE_RULES:
            assert rule_id in fired_rule_ids, f"{rule_id} produced no findings"

    def test_engine_green_for_good_code(self) -> None:
        cregistry, rregistry = _csharp_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        good_only = CSHARP_REPO / "good_code.cs"
        assert good_only.exists()
        result = engine.run(target=CSHARP_REPO, config=Config(tech={}))
        good_findings = [
            f
            for f in result.findings
            if "good_code.cs" in (f.evidence_locator or "") and f.rag in ("amber", "red")
        ]
        assert len(good_findings) == 0, (
            f"good_code.cs should have no amber/red findings, got: {good_findings}"
        )

    def test_csharp_rules_skip_without_csharp_tech(self) -> None:
        cregistry, rregistry = _csharp_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=PYTHON_REPO, config=Config(tech={}))
        skipped_ids = {e["rule_id"] for e in result.run_metadata.rules_skipped}
        for rule_id, _ in CSHARP_SPECIFIC_RULES:
            assert rule_id in skipped_ids, (
                f"{rule_id} should be skipped when no .cs files present"
            )

    def test_csharp_collector_registered(self) -> None:
        from nfr_review.registry import collector_registry

        assert "csharp-ast" in collector_registry

    def test_all_csharp_rules_registered(self) -> None:
        from nfr_review.registry import rule_registry

        for rule_id, _ in CSHARP_SPECIFIC_RULES:
            assert rule_id in rule_registry, f"{rule_id} not in rule_registry"

    def test_evidence_payload_structure(self, full_result: RunResult) -> None:
        cregistry, _ = _csharp_registries()
        engine_evidence: list = []
        collector = cregistry.get("csharp-ast")
        produced = collector.collect(CSHARP_REPO, Config(tech={}))
        engine_evidence.extend(produced)
        assert len(engine_evidence) > 0
        for ev in engine_evidence:
            assert ev.kind == "csharp-ast-file"
            assert ev.collector_name == "csharp-ast"
            assert "file_path" in ev.payload
            assert "catch_blocks" in ev.payload
            assert "log_statements" in ev.payload
            assert "methods" in ev.payload
            assert "await_expressions" in ev.payload
            assert "object_creations" in ev.payload

    def test_finding_field_compliance(self, full_result: RunResult) -> None:
        assert len(full_result.findings) > 0
        for finding in full_result.findings:
            finding_dict = finding.model_dump()
            for field in R007_FIELDS:
                assert field in finding_dict, f"Missing R007 field: {field}"
                assert finding_dict[field] is not None, f"R007 field {field} is None"

    def test_no_rules_skipped_with_csharp_evidence(self, full_result: RunResult) -> None:
        ran = set(full_result.run_metadata.rules_run)
        assert ALL_CSHARP_RULE_IDS <= ran

    def test_all_six_rules_ran(self, full_result: RunResult) -> None:
        ran = set(full_result.run_metadata.rules_run)
        assert ALL_CSHARP_RULE_IDS <= ran


# ---------------------------------------------------------------------------
# Cross-language rules with C# evidence
# ---------------------------------------------------------------------------


class TestCrossLanguageWithCSharp:
    @pytest.fixture()
    def full_result(self) -> RunResult:
        cregistry, rregistry = _csharp_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        return engine.run(target=CSHARP_REPO, config=Config(tech={}))

    def test_bare_except_detects_csharp_catch_exception(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "bare-except-catch-all")
        red = [f for f in findings if f.rag == "red"]
        assert len(red) >= 1, "Expected red finding for catch(Exception)"

    def test_bare_except_detects_csharp_bare_catch(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "bare-except-catch-all")
        amber = [f for f in findings if f.rag == "amber"]
        assert len(amber) >= 1, "Expected amber finding for bare catch"

    def test_logging_stdout_detects_console_writeline(self, full_result: RunResult) -> None:
        findings = _findings_by_rule(full_result, "logging-to-stdout")
        amber = [f for f in findings if f.rag == "amber"]
        assert len(amber) >= 1, "Expected amber finding for Console.WriteLine"

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

    def test_cross_language_rules_still_work_for_java(self) -> None:
        from nfr_review.collectors.java_ast import JavaAstCollector

        java_repo = FIXTURES / "java-sample-repo"
        if not java_repo.exists():
            pytest.skip("java-sample-repo fixture not available")
        cregistry: Registry = Registry("collector")
        rregistry: Registry = Registry("rule")
        cregistry.register("java-ast", JavaAstCollector())
        rregistry.register("bare-except-catch-all", BareExceptCatchAllRule())
        rregistry.register("logging-to-stdout", LoggingToStdoutRule())
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=java_repo, config=Config(tech={}))
        findings = result.findings
        assert len(findings) > 0, "Cross-language rules should produce Java findings"


# ---------------------------------------------------------------------------
# Tech-gating — C# rules skip when no .cs files / no collector
# ---------------------------------------------------------------------------


class TestTechGating:
    def test_rules_skip_when_no_cs_files(self) -> None:
        cregistry, rregistry = _csharp_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=PYTHON_REPO, config=Config(tech={}))
        skipped_ids = {e["rule_id"] for e in result.run_metadata.rules_skipped}
        for rule_id, _ in CSHARP_SPECIFIC_RULES:
            assert rule_id in skipped_ids, (
                f"{rule_id} should be skipped for a Python-only repo"
            )

    def test_rules_fire_when_cs_files_present(self) -> None:
        cregistry, rregistry = _csharp_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=CSHARP_REPO, config=Config(tech={}))
        ran = set(result.run_metadata.rules_run)
        for rule_id, _ in CSHARP_SPECIFIC_RULES:
            assert rule_id in ran, f"{rule_id} should have run for C# repo"

    def test_skip_reason_mentions_csharp_ast(self) -> None:
        cregistry, rregistry = _no_csharp_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=CSHARP_REPO, config=Config(tech={}))
        for entry in result.run_metadata.rules_skipped:
            if entry["rule_id"] in {r[0] for r in CSHARP_SPECIFIC_RULES}:
                assert "csharp-ast" in entry["reason"]

    def test_no_findings_without_collector(self) -> None:
        cregistry, rregistry = _no_csharp_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        result = engine.run(target=CSHARP_REPO, config=Config(tech={}))
        csharp_findings = [
            f for f in result.findings if f.rule_id in {r[0] for r in CSHARP_SPECIFIC_RULES}
        ]
        assert len(csharp_findings) == 0
