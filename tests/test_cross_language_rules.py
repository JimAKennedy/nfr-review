"""Tests for cross-language AST rules (bare-except-catch-all, logging-to-stdout).

These rules use D021 ANY-match semantics — required_collectors=[] and
required_tech=[] — so the engine always runs them. They filter evidence
internally by iterating LanguageRuleConfig entries.
"""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.rules.ast_bare_except import BareExceptCatchAllRule
from nfr_review.rules.ast_logging_stdout import LoggingToStdoutRule


def _make_evidence(
    collector_name: str,
    kind: str,
    payload: dict,
    locator: str = "test-file",
    version: str = "0.1.0",
) -> Evidence:
    return Evidence(
        collector_name=collector_name,
        collector_version=version,
        locator=locator,
        kind=kind,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# BareExceptCatchAllRule
# ---------------------------------------------------------------------------


class TestBareExceptCatchAllRule:
    def setup_method(self) -> None:
        self.rule = BareExceptCatchAllRule()

    # --- Python evidence ---

    def test_python_bare_except_amber(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "app.py",
                "catch_blocks": [{"caught_type": "", "rethrows": False, "line": 5}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "Bare except" in f.summary
        assert f.evidence_locator == "app.py:5"

    def test_python_broad_exception_red(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "app.py",
                "catch_blocks": [{"caught_type": "Exception", "rethrows": False, "line": 10}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "high"
        assert "Exception" in f.summary

    def test_python_base_exception_red(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "app.py",
                "catch_blocks": [
                    {"caught_type": "BaseException", "rethrows": False, "line": 3}
                ],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"

    def test_python_rethrow_no_finding(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "app.py",
                "catch_blocks": [{"caught_type": "Exception", "rethrows": True, "line": 7}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_python_specific_exception_green(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "app.py",
                "catch_blocks": [{"caught_type": "ValueError", "rethrows": False, "line": 4}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    # --- Java evidence ---

    def test_java_broad_exception_red(self) -> None:
        ev = _make_evidence(
            "java-ast",
            "java-ast-file",
            {
                "file_path": "App.java",
                "catch_blocks": [{"caught_type": "Exception", "rethrows": False, "line": 15}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "high"
        assert "Exception" in f.summary
        assert f.collector_name == "java-ast"

    def test_java_throwable_red(self) -> None:
        ev = _make_evidence(
            "java-ast",
            "java-ast-file",
            {
                "file_path": "App.java",
                "catch_blocks": [{"caught_type": "Throwable", "rethrows": False, "line": 20}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"

    def test_java_rethrow_no_finding(self) -> None:
        ev = _make_evidence(
            "java-ast",
            "java-ast-file",
            {
                "file_path": "App.java",
                "catch_blocks": [{"caught_type": "Exception", "rethrows": True, "line": 25}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_java_specific_exception_green(self) -> None:
        ev = _make_evidence(
            "java-ast",
            "java-ast-file",
            {
                "file_path": "App.java",
                "catch_blocks": [
                    {"caught_type": "IOException", "rethrows": False, "line": 12}
                ],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    # --- Go evidence ---

    def test_go_recover_bare_catch_amber(self) -> None:
        ev = _make_evidence(
            "go-ast",
            "go-ast-file",
            {
                "file_path": "handler.go",
                "catch_blocks": [{"caught_type": "", "rethrows": False, "line": 12}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert f.collector_name == "go-ast"
        assert f.evidence_locator == "handler.go:12"

    def test_go_recover_rethrow_no_finding(self) -> None:
        ev = _make_evidence(
            "go-ast",
            "go-ast-file",
            {
                "file_path": "handler.go",
                "catch_blocks": [{"caught_type": "", "rethrows": True, "line": 20}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    # --- C# evidence ---

    def test_csharp_broad_exception_red(self) -> None:
        ev = _make_evidence(
            "csharp-ast",
            "csharp-ast-file",
            {
                "file_path": "Service.cs",
                "catch_blocks": [{"caught_type": "Exception", "rethrows": False, "line": 10}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "high"
        assert "Exception" in f.summary
        assert f.collector_name == "csharp-ast"

    def test_csharp_system_exception_red(self) -> None:
        ev = _make_evidence(
            "csharp-ast",
            "csharp-ast-file",
            {
                "file_path": "Service.cs",
                "catch_blocks": [
                    {"caught_type": "SystemException", "rethrows": False, "line": 15}
                ],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"

    def test_csharp_bare_catch_amber(self) -> None:
        ev = _make_evidence(
            "csharp-ast",
            "csharp-ast-file",
            {
                "file_path": "Service.cs",
                "catch_blocks": [{"caught_type": "", "rethrows": False, "line": 20}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "Bare except" in f.summary

    def test_csharp_rethrow_green(self) -> None:
        ev = _make_evidence(
            "csharp-ast",
            "csharp-ast-file",
            {
                "file_path": "Service.cs",
                "catch_blocks": [{"caught_type": "Exception", "rethrows": True, "line": 25}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_csharp_specific_exception_green(self) -> None:
        ev = _make_evidence(
            "csharp-ast",
            "csharp-ast-file",
            {
                "file_path": "Service.cs",
                "catch_blocks": [
                    {"caught_type": "ArgumentException", "rethrows": False, "line": 30}
                ],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    # --- Node.js evidence ---

    def test_nodejs_bare_catch_amber(self) -> None:
        ev = _make_evidence(
            "nodejs-ast",
            "nodejs-ast-file",
            {
                "file_path": "app.js",
                "catch_blocks": [{"caught_type": "", "rethrows": False, "line": 5}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert f.collector_name == "nodejs-ast"

    def test_nodejs_rethrow_green(self) -> None:
        ev = _make_evidence(
            "nodejs-ast",
            "nodejs-ast-file",
            {
                "file_path": "app.js",
                "catch_blocks": [{"caught_type": "", "rethrows": True, "line": 10}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    # --- Cross-language / mixed ---

    def test_mixed_evidence_findings_from_all(self) -> None:
        py_ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "app.py",
                "catch_blocks": [{"caught_type": "", "rethrows": False, "line": 5}],
            },
        )
        java_ev = _make_evidence(
            "java-ast",
            "java-ast-file",
            {
                "file_path": "App.java",
                "catch_blocks": [{"caught_type": "Throwable", "rethrows": False, "line": 10}],
            },
        )
        go_ev = _make_evidence(
            "go-ast",
            "go-ast-file",
            {
                "file_path": "main.go",
                "catch_blocks": [{"caught_type": "", "rethrows": False, "line": 15}],
            },
        )
        cs_ev = _make_evidence(
            "csharp-ast",
            "csharp-ast-file",
            {
                "file_path": "Service.cs",
                "catch_blocks": [{"caught_type": "Exception", "rethrows": False, "line": 8}],
            },
        )
        js_ev = _make_evidence(
            "nodejs-ast",
            "nodejs-ast-file",
            {
                "file_path": "app.js",
                "catch_blocks": [{"caught_type": "", "rethrows": False, "line": 3}],
            },
        )
        result = self.rule.evaluate([py_ev, java_ev, go_ev, cs_ev, js_ev], None)
        assert len(result.findings) == 5
        collectors = {f.collector_name for f in result.findings}
        assert collectors == {"python-ast", "java-ast", "go-ast", "csharp-ast", "nodejs-ast"}

    def test_no_evidence_skipped(self) -> None:
        ev = _make_evidence("terraform", "tf-file", {"resources": []})
        result = self.rule.evaluate([ev], None)
        assert result.skipped
        assert "no AST evidence" in (result.skip_reason or "")

    def test_empty_catch_blocks_green(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {"file_path": "clean.py", "catch_blocks": []},
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_multiple_blocks_multiple_findings(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "messy.py",
                "catch_blocks": [
                    {"caught_type": "", "rethrows": False, "line": 3},
                    {"caught_type": "Exception", "rethrows": False, "line": 10},
                    {"caught_type": "ValueError", "rethrows": False, "line": 17},
                ],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 2
        assert result.findings[0].rag == "amber"
        assert result.findings[1].rag == "red"

    def test_rule_attributes(self) -> None:
        assert self.rule.id == "bare-except-catch-all"
        assert self.rule.band == 1
        assert self.rule.required_collectors == []
        assert self.rule.required_tech == []


# ---------------------------------------------------------------------------
# LoggingToStdoutRule
# ---------------------------------------------------------------------------


class TestLoggingToStdoutRule:
    def setup_method(self) -> None:
        self.rule = LoggingToStdoutRule()

    # --- Python evidence ---

    def test_python_print_amber(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "app.py",
                "log_statements": [{"method": "print", "line": 5}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "print()" in f.summary
        assert f.evidence_locator == "app.py:5"

    def test_python_stdout_write_amber(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "app.py",
                "log_statements": [{"method": "sys.stdout.write", "line": 8}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert "sys.stdout.write()" in result.findings[0].summary

    def test_python_stderr_write_amber(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "app.py",
                "log_statements": [{"method": "sys.stderr.write", "line": 12}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert "sys.stderr.write()" in result.findings[0].summary

    def test_python_logger_not_flagged(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "app.py",
                "log_statements": [{"method": "logger.info", "line": 3}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    # --- Java evidence ---

    def test_java_system_out_println_amber(self) -> None:
        ev = _make_evidence(
            "java-ast",
            "java-ast-file",
            {
                "file_path": "App.java",
                "log_statements": [
                    {"method": "System.out.println", "arguments_text": '"hello"', "line": 6}
                ],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert "System.out.println()" in f.summary
        assert f.collector_name == "java-ast"

    def test_java_system_err_println_amber(self) -> None:
        ev = _make_evidence(
            "java-ast",
            "java-ast-file",
            {
                "file_path": "App.java",
                "log_statements": [
                    {"method": "System.err.println", "arguments_text": '"error"', "line": 10}
                ],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert "System.err.println()" in result.findings[0].summary

    def test_java_system_out_printf_amber(self) -> None:
        ev = _make_evidence(
            "java-ast",
            "java-ast-file",
            {
                "file_path": "App.java",
                "log_statements": [
                    {"method": "System.out.printf", "arguments_text": '"%s"', "line": 14}
                ],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1

    def test_java_logger_not_flagged(self) -> None:
        ev = _make_evidence(
            "java-ast",
            "java-ast-file",
            {
                "file_path": "App.java",
                "log_statements": [
                    {"method": "logger.info", "arguments_text": '"ok"', "line": 3}
                ],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    # --- Go evidence ---

    def test_go_fmt_println_amber(self) -> None:
        ev = _make_evidence(
            "go-ast",
            "go-ast-file",
            {
                "file_path": "server.go",
                "log_statements": [{"method": "fmt.Println", "line": 8}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "fmt.Println()" in f.summary
        assert f.collector_name == "go-ast"
        assert f.evidence_locator == "server.go:8"

    def test_go_fmt_printf_amber(self) -> None:
        ev = _make_evidence(
            "go-ast",
            "go-ast-file",
            {
                "file_path": "server.go",
                "log_statements": [{"method": "fmt.Printf", "line": 12}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "fmt.Printf()" in result.findings[0].summary

    def test_go_log_not_flagged(self) -> None:
        ev = _make_evidence(
            "go-ast",
            "go-ast-file",
            {
                "file_path": "server.go",
                "log_statements": [{"method": "log.Println", "line": 5}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    # --- C# evidence ---

    def test_csharp_console_writeline_amber(self) -> None:
        ev = _make_evidence(
            "csharp-ast",
            "csharp-ast-file",
            {
                "file_path": "Service.cs",
                "log_statements": [{"method": "Console.WriteLine", "line": 6}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert "Console.WriteLine()" in f.summary
        assert f.collector_name == "csharp-ast"

    def test_csharp_console_write_amber(self) -> None:
        ev = _make_evidence(
            "csharp-ast",
            "csharp-ast-file",
            {
                "file_path": "Service.cs",
                "log_statements": [{"method": "Console.Write", "line": 8}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_csharp_debug_writeline_amber(self) -> None:
        ev = _make_evidence(
            "csharp-ast",
            "csharp-ast-file",
            {
                "file_path": "Service.cs",
                "log_statements": [{"method": "Debug.WriteLine", "line": 10}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_csharp_logger_not_flagged(self) -> None:
        ev = _make_evidence(
            "csharp-ast",
            "csharp-ast-file",
            {
                "file_path": "Service.cs",
                "log_statements": [{"method": "logger.Information", "line": 3}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    # --- Node.js evidence ---

    def test_nodejs_console_log_amber(self) -> None:
        ev = _make_evidence(
            "nodejs-ast",
            "nodejs-ast-file",
            {
                "file_path": "app.js",
                "log_statements": [{"method": "console.log", "line": 5}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert "console.log()" in f.summary
        assert f.collector_name == "nodejs-ast"

    def test_nodejs_console_warn_amber(self) -> None:
        ev = _make_evidence(
            "nodejs-ast",
            "nodejs-ast-file",
            {
                "file_path": "app.js",
                "log_statements": [{"method": "console.warn", "line": 8}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_nodejs_process_stdout_amber(self) -> None:
        ev = _make_evidence(
            "nodejs-ast",
            "nodejs-ast-file",
            {
                "file_path": "app.js",
                "log_statements": [{"method": "process.stdout.write", "line": 12}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_nodejs_logger_not_flagged(self) -> None:
        ev = _make_evidence(
            "nodejs-ast",
            "nodejs-ast-file",
            {
                "file_path": "app.js",
                "log_statements": [{"method": "logger.info", "line": 3}],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    # --- Cross-language / mixed ---

    def test_mixed_evidence_findings_from_all(self) -> None:
        py_ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "app.py",
                "log_statements": [{"method": "print", "line": 5}],
            },
        )
        java_ev = _make_evidence(
            "java-ast",
            "java-ast-file",
            {
                "file_path": "App.java",
                "log_statements": [
                    {"method": "System.out.println", "arguments_text": '""', "line": 10}
                ],
            },
        )
        go_ev = _make_evidence(
            "go-ast",
            "go-ast-file",
            {
                "file_path": "main.go",
                "log_statements": [{"method": "fmt.Println", "line": 15}],
            },
        )
        cs_ev = _make_evidence(
            "csharp-ast",
            "csharp-ast-file",
            {
                "file_path": "Service.cs",
                "log_statements": [{"method": "Console.WriteLine", "line": 6}],
            },
        )
        js_ev = _make_evidence(
            "nodejs-ast",
            "nodejs-ast-file",
            {
                "file_path": "app.js",
                "log_statements": [{"method": "console.log", "line": 5}],
            },
        )
        result = self.rule.evaluate([py_ev, java_ev, go_ev, cs_ev, js_ev], None)
        assert len(result.findings) == 5
        collectors = {f.collector_name for f in result.findings}
        assert collectors == {"python-ast", "java-ast", "go-ast", "csharp-ast", "nodejs-ast"}

    def test_no_evidence_skipped(self) -> None:
        ev = _make_evidence("terraform", "tf-file", {"resources": []})
        result = self.rule.evaluate([ev], None)
        assert result.skipped
        assert "no AST evidence" in (result.skip_reason or "")

    def test_no_log_statements_green(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {"file_path": "clean.py", "log_statements": []},
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_multiple_stdout_calls(self) -> None:
        ev = _make_evidence(
            "python-ast",
            "python-ast-file",
            {
                "file_path": "debug.py",
                "log_statements": [
                    {"method": "print", "line": 3},
                    {"method": "sys.stdout.write", "line": 7},
                    {"method": "sys.stderr.write", "line": 11},
                ],
            },
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 3
        assert all(f.rag == "amber" for f in result.findings)

    def test_rule_attributes(self) -> None:
        assert self.rule.id == "logging-to-stdout"
        assert self.rule.band == 1
        assert self.rule.required_collectors == []
        assert self.rule.required_tech == []


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_rules_registered(self) -> None:
        import importlib

        import nfr_review.rules

        importlib.reload(nfr_review.rules)

        from nfr_review.registry import rule_registry

        assert "bare-except-catch-all" in rule_registry
        assert "logging-to-stdout" in rule_registry
