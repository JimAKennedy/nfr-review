"""Polyglot integration tests — all AST collectors + cross-language rules in one scan."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.csharp_ast import CSharpAstCollector
from nfr_review.collectors.go_ast import GoAstCollector
from nfr_review.collectors.java_ast import JavaAstCollector
from nfr_review.collectors.nodejs_ast import NodejsAstCollector
from nfr_review.collectors.python_ast import PythonAstCollector
from nfr_review.collectors.repo_structure import RepoStructureCollector
from nfr_review.config import Config
from nfr_review.detect import detect_technologies
from nfr_review.engine import Engine, RunResult
from nfr_review.registry import Registry
from nfr_review.rules.ast_bare_except import BareExceptCatchAllRule
from nfr_review.rules.ast_logging_stdout import LoggingToStdoutRule
from nfr_review.rules.csharp_async_void import CSharpAsyncVoidRule
from nfr_review.rules.csharp_blocking_async import CSharpBlockingAsyncRule
from nfr_review.rules.go_defer_in_loop import GoDeferInLoopRule
from nfr_review.rules.go_error_ignored import GoErrorIgnoredRule
from nfr_review.rules.java_exception import ExceptionHandlingAntipatternRule
from nfr_review.rules.nodejs_floating_promise import NodejsFloatingPromiseRule
from nfr_review.rules.nodejs_sync_fs_api import NodejsSyncFsApiRule
from nfr_review.rules.python_broad_except_silent import PythonBroadExceptSilentRule
from nfr_review.rules.python_mutable_default import PythonMutableDefaultRule

FIXTURES = Path(__file__).parent / "fixtures"
POLYGLOT = FIXTURES / "polyglot-sample-repo"

AST_COLLECTOR_NAMES = {"java-ast", "python-ast", "go-ast", "csharp-ast", "nodejs-ast"}


def _polyglot_registries() -> tuple[Registry, Registry]:
    """Build registries with all 5 AST collectors, cross-language + language-specific rules."""
    cregistry: Registry = Registry("collector")
    rregistry: Registry = Registry("rule")

    cregistry.register("repo-structure", RepoStructureCollector())
    cregistry.register("java-ast", JavaAstCollector())
    cregistry.register("python-ast", PythonAstCollector())
    cregistry.register("go-ast", GoAstCollector())
    cregistry.register("csharp-ast", CSharpAstCollector())
    cregistry.register("nodejs-ast", NodejsAstCollector())

    rregistry.register("bare-except-catch-all", BareExceptCatchAllRule())
    rregistry.register("logging-to-stdout", LoggingToStdoutRule())
    rregistry.register("exception-handling-antipattern", ExceptionHandlingAntipatternRule())
    rregistry.register("python-broad-except-silent", PythonBroadExceptSilentRule())
    rregistry.register("python-mutable-default", PythonMutableDefaultRule())
    rregistry.register("go-error-ignored", GoErrorIgnoredRule())
    rregistry.register("go-defer-in-loop", GoDeferInLoopRule())
    rregistry.register("csharp-async-void", CSharpAsyncVoidRule())
    rregistry.register("csharp-blocking-async", CSharpBlockingAsyncRule())
    rregistry.register("nodejs-floating-promise", NodejsFloatingPromiseRule())
    rregistry.register("nodejs-sync-fs-api", NodejsSyncFsApiRule())

    return cregistry, rregistry


class TestPolyglotTechDetection:
    """detect_technologies() identifies all 5 language techs from the polyglot fixture."""

    def test_java_detected(self) -> None:
        tech = detect_technologies(POLYGLOT)
        assert tech.get("java") is True

    def test_python_detected(self) -> None:
        tech = detect_technologies(POLYGLOT)
        assert tech.get("python") is True

    def test_csharp_detected(self) -> None:
        tech = detect_technologies(POLYGLOT)
        assert tech.get("csharp") is True

    def test_nodejs_detected(self) -> None:
        tech = detect_technologies(POLYGLOT)
        assert tech.get("nodejs") is True

    def test_go_detected(self) -> None:
        tech = detect_technologies(POLYGLOT)
        assert tech.get("go") is True

    def test_all_five_detected_at_once(self) -> None:
        tech = detect_technologies(POLYGLOT)
        for key in ("java", "python", "csharp", "nodejs", "go"):
            assert tech.get(key) is True, f"tech[{key!r}] not detected"


class TestPolyglotEngineRun:
    """Engine.run() produces findings from all AST collectors in a single scan."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _polyglot_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        tech = detect_technologies(POLYGLOT)
        cfg = Config(tech=tech)
        return engine.run(target=POLYGLOT, config=cfg)

    def test_engine_returns_successfully(self, result: RunResult) -> None:
        assert result is not None
        assert result.run_metadata is not None

    def test_java_ast_produces_findings(self, result: RunResult) -> None:
        java_findings = [f for f in result.findings if f.collector_name == "java-ast"]
        assert len(java_findings) >= 1

    def test_python_ast_produces_findings(self, result: RunResult) -> None:
        python_findings = [f for f in result.findings if f.collector_name == "python-ast"]
        assert len(python_findings) >= 1

    def test_go_ast_produces_findings(self, result: RunResult) -> None:
        go_findings = [f for f in result.findings if f.collector_name == "go-ast"]
        assert len(go_findings) >= 1

    def test_csharp_ast_produces_findings(self, result: RunResult) -> None:
        csharp_findings = [f for f in result.findings if f.collector_name == "csharp-ast"]
        assert len(csharp_findings) >= 1

    def test_nodejs_ast_produces_findings(self, result: RunResult) -> None:
        nodejs_findings = [f for f in result.findings if f.collector_name == "nodejs-ast"]
        assert len(nodejs_findings) >= 1

    def test_all_five_ast_collectors_produce_findings(self, result: RunResult) -> None:
        collector_names = {f.collector_name for f in result.findings}
        assert AST_COLLECTOR_NAMES <= collector_names

    def test_at_least_five_distinct_rule_ids(self, result: RunResult) -> None:
        rule_ids = {f.rule_id for f in result.findings}
        assert len(rule_ids) >= 5


class TestCrossLanguageRules:
    """Cross-language rules fire for multiple languages in the polyglot scan."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _polyglot_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        tech = detect_technologies(POLYGLOT)
        cfg = Config(tech=tech)
        return engine.run(target=POLYGLOT, config=cfg)

    def test_bare_except_fires(self, result: RunResult) -> None:
        bare_findings = [f for f in result.findings if f.rule_id == "bare-except-catch-all"]
        assert len(bare_findings) >= 1

    def test_bare_except_fires_for_multiple_languages(self, result: RunResult) -> None:
        bare_findings = [
            f
            for f in result.findings
            if f.rule_id == "bare-except-catch-all" and f.rag != "green"
        ]
        collectors_hit = {f.collector_name for f in bare_findings}
        assert len(collectors_hit) >= 2, (
            f"bare-except should fire for >=2 collectors, got {collectors_hit}"
        )

    def test_logging_stdout_fires(self, result: RunResult) -> None:
        log_findings = [f for f in result.findings if f.rule_id == "logging-to-stdout"]
        assert len(log_findings) >= 1

    def test_logging_stdout_fires_for_multiple_languages(self, result: RunResult) -> None:
        log_findings = [
            f for f in result.findings if f.rule_id == "logging-to-stdout" and f.rag != "green"
        ]
        collectors_hit = {f.collector_name for f in log_findings}
        assert len(collectors_hit) >= 2, (
            f"logging-to-stdout should fire for >=2 collectors, got {collectors_hit}"
        )


class TestNoCrossContamination:
    """Each collector's findings reference only that collector's name."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _polyglot_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        tech = detect_technologies(POLYGLOT)
        cfg = Config(tech=tech)
        return engine.run(target=POLYGLOT, config=cfg)

    def test_java_findings_use_java_collector(self, result: RunResult) -> None:
        for f in result.findings:
            if f.evidence_locator and f.evidence_locator.endswith(".java"):
                assert f.collector_name == "java-ast", (
                    f"Java file finding used collector {f.collector_name}"
                )

    def test_python_findings_use_python_collector(self, result: RunResult) -> None:
        for f in result.findings:
            if f.evidence_locator and f.evidence_locator.endswith(".py"):
                assert f.collector_name == "python-ast", (
                    f"Python file finding used collector {f.collector_name}"
                )

    def test_go_findings_use_go_collector(self, result: RunResult) -> None:
        for f in result.findings:
            if f.evidence_locator and f.evidence_locator.endswith(".go"):
                assert f.collector_name == "go-ast", (
                    f"Go file finding used collector {f.collector_name}"
                )

    def test_csharp_findings_use_csharp_collector(self, result: RunResult) -> None:
        for f in result.findings:
            if f.evidence_locator and f.evidence_locator.endswith(".cs"):
                assert f.collector_name == "csharp-ast", (
                    f"C# file finding used collector {f.collector_name}"
                )

    def test_nodejs_findings_use_nodejs_collector(self, result: RunResult) -> None:
        for f in result.findings:
            if f.evidence_locator and f.evidence_locator.endswith(".js"):
                assert f.collector_name == "nodejs-ast", (
                    f"Node.js file finding used collector {f.collector_name}"
                )


class TestLanguageSpecificRules:
    """Language-specific rules fire for their respective languages."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _polyglot_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        tech = detect_technologies(POLYGLOT)
        cfg = Config(tech=tech)
        return engine.run(target=POLYGLOT, config=cfg)

    def test_java_exception_rule_fires(self, result: RunResult) -> None:
        findings = [
            f for f in result.findings if f.rule_id == "exception-handling-antipattern"
        ]
        assert len(findings) >= 1

    def test_python_broad_except_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "python-broad-except-silent"]
        assert len(findings) >= 1

    def test_python_mutable_default_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "python-mutable-default"]
        assert len(findings) >= 1

    def test_go_error_ignored_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "go-error-ignored"]
        assert len(findings) >= 1

    def test_go_defer_in_loop_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "go-defer-in-loop"]
        assert len(findings) >= 1

    def test_csharp_async_void_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "csharp-async-void"]
        non_green = [f for f in findings if f.rag != "green"]
        assert len(non_green) >= 1

    def test_csharp_blocking_async_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "csharp-blocking-async"]
        non_green = [f for f in findings if f.rag != "green"]
        assert len(non_green) >= 1

    def test_nodejs_floating_promise_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "nodejs-floating-promise"]
        non_green = [f for f in findings if f.rag != "green"]
        assert len(non_green) >= 1

    def test_nodejs_sync_fs_fires(self, result: RunResult) -> None:
        findings = [f for f in result.findings if f.rule_id == "nodejs-sync-fs-api"]
        non_green = [f for f in findings if f.rag != "green"]
        assert len(non_green) >= 1

    def test_language_specific_rules_only_reference_their_collector(
        self, result: RunResult
    ) -> None:
        for f in result.findings:
            if f.rule_id == "exception-handling-antipattern":
                assert f.collector_name == "java-ast"
            elif f.rule_id in ("python-broad-except-silent", "python-mutable-default"):
                assert f.collector_name == "python-ast"
            elif f.rule_id in ("go-error-ignored", "go-defer-in-loop"):
                assert f.collector_name == "go-ast"
            elif f.rule_id in ("csharp-async-void", "csharp-blocking-async"):
                assert f.collector_name == "csharp-ast"
            elif f.rule_id in ("nodejs-floating-promise", "nodejs-sync-fs-api"):
                assert f.collector_name == "nodejs-ast"


class TestGoodCodeGreen:
    """Good-code files produce only green findings (no amber/red)."""

    @pytest.fixture()
    def result(self) -> RunResult:
        cregistry, rregistry = _polyglot_registries()
        engine = Engine(collectors=cregistry, rules=rregistry)
        tech = detect_technologies(POLYGLOT)
        cfg = Config(tech=tech)
        return engine.run(target=POLYGLOT, config=cfg)

    def test_good_java_no_non_green(self, result: RunResult) -> None:
        bad = [
            f
            for f in result.findings
            if f.evidence_locator
            and "GoodService.java" in f.evidence_locator
            and f.rag != "green"
        ]
        assert len(bad) == 0, f"GoodService.java has non-green findings: {bad}"

    def test_good_python_no_non_green(self, result: RunResult) -> None:
        bad = [
            f
            for f in result.findings
            if f.evidence_locator and "good_code.py" in f.evidence_locator and f.rag != "green"
        ]
        assert len(bad) == 0, f"good_code.py has non-green findings: {bad}"

    def test_good_go_no_non_green(self, result: RunResult) -> None:
        bad = [
            f
            for f in result.findings
            if f.evidence_locator and "good_code.go" in f.evidence_locator and f.rag != "green"
        ]
        assert len(bad) == 0, f"good_code.go has non-green findings: {bad}"

    def test_good_csharp_no_non_green(self, result: RunResult) -> None:
        bad = [
            f
            for f in result.findings
            if f.evidence_locator and "GoodCode.cs" in f.evidence_locator and f.rag != "green"
        ]
        assert len(bad) == 0, f"GoodCode.cs has non-green findings: {bad}"

    def test_good_js_no_non_green(self, result: RunResult) -> None:
        bad = [
            f
            for f in result.findings
            if f.evidence_locator and "good_code.js" in f.evidence_locator and f.rag != "green"
        ]
        assert len(bad) == 0, f"good_code.js has non-green findings: {bad}"
