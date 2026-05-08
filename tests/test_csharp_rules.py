"""Tests for 4 C#-specific NFR rules and C# entries in cross-language rules."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.ast_bare_except import BareExceptCatchAllRule
from nfr_review.rules.ast_logging_stdout import LoggingToStdoutRule
from nfr_review.rules.csharp_async_void import CSharpAsyncVoidRule
from nfr_review.rules.csharp_blocking_async import CSharpBlockingAsyncRule
from nfr_review.rules.csharp_configure_await import CSharpConfigureAwaitRule
from nfr_review.rules.csharp_disposable_no_using import CSharpDisposableNoUsingRule

_COLLECTOR = "csharp-ast"
_VERSION = "0.1.0"
_KIND = "csharp-ast-file"


def _ev(payload: dict, locator: str = "Program.cs") -> Evidence:
    return Evidence(
        collector_name=_COLLECTOR,
        collector_version=_VERSION,
        locator=locator,
        kind=_KIND,
        payload={"file_path": locator, **payload},
    )


def _non_cs_evidence() -> list[Evidence]:
    return [
        Evidence(
            collector_name="python-ast",
            collector_version="0.1.0",
            locator="main.py",
            kind="python-ast-file",
            payload={},
        )
    ]


# ---------------------------------------------------------------------------
# csharp-async-void
# ---------------------------------------------------------------------------


class TestCSharpAsyncVoidRule:
    rule = CSharpAsyncVoidRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "csharp-async-void"
        assert self.rule.required_collectors == ["csharp-ast"]

    def test_registered(self) -> None:
        assert "csharp-async-void" in rule_registry

    def test_detects_async_void(self) -> None:
        ev = _ev(
            {
                "methods": [
                    {
                        "name": "OnClick",
                        "line": 5,
                        "is_async": True,
                        "return_type": "void",
                        "modifiers": ["public", "async"],
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "high"
        assert "OnClick" in f.summary
        assert f.pattern_tag == "csharp-async-void"

    def test_clean_async_task(self) -> None:
        ev = _ev(
            {
                "methods": [
                    {
                        "name": "DoWork",
                        "line": 10,
                        "is_async": True,
                        "return_type": "Task",
                        "modifiers": ["public", "async"],
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skipped_no_evidence(self) -> None:
        result = self.rule.evaluate(_non_cs_evidence(), None)
        assert result.skipped

    def test_non_async_void_ignored(self) -> None:
        ev = _ev(
            {
                "methods": [
                    {
                        "name": "Main",
                        "line": 1,
                        "is_async": False,
                        "return_type": "void",
                        "modifiers": ["public", "static"],
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# csharp-configure-await
# ---------------------------------------------------------------------------


class TestCSharpConfigureAwaitRule:
    rule = CSharpConfigureAwaitRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "csharp-configure-await"
        assert self.rule.required_collectors == ["csharp-ast"]

    def test_registered(self) -> None:
        assert "csharp-configure-await" in rule_registry

    def test_detects_missing_configure_await(self) -> None:
        ev = _ev(
            {
                "await_expressions": [
                    {
                        "expression": "client.GetAsync(url)",
                        "has_configure_await": False,
                        "line": 15,
                        "file": "Service.cs",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert f.pattern_tag == "csharp-configure-await"

    def test_clean_with_configure_await(self) -> None:
        ev = _ev(
            {
                "await_expressions": [
                    {
                        "expression": "client.GetAsync(url).ConfigureAwait(false)",
                        "has_configure_await": True,
                        "line": 15,
                        "file": "Service.cs",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_skipped_no_evidence(self) -> None:
        result = self.rule.evaluate(_non_cs_evidence(), None)
        assert result.skipped


# ---------------------------------------------------------------------------
# csharp-disposable-no-using
# ---------------------------------------------------------------------------


class TestCSharpDisposableNoUsingRule:
    rule = CSharpDisposableNoUsingRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "csharp-disposable-no-using"
        assert self.rule.required_collectors == ["csharp-ast"]

    def test_registered(self) -> None:
        assert "csharp-disposable-no-using" in rule_registry

    def test_detects_disposable_without_using(self) -> None:
        ev = _ev(
            {
                "object_creations": [
                    {
                        "type_name": "FileStream",
                        "in_using": False,
                        "line": 20,
                        "file": "IO.cs",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "FileStream" in f.summary
        assert f.pattern_tag == "csharp-disposable-no-using"

    def test_clean_with_using(self) -> None:
        ev = _ev(
            {
                "object_creations": [
                    {
                        "type_name": "SqlConnection",
                        "in_using": True,
                        "line": 20,
                        "file": "DB.cs",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_skipped_no_evidence(self) -> None:
        result = self.rule.evaluate(_non_cs_evidence(), None)
        assert result.skipped

    def test_unknown_type_not_flagged(self) -> None:
        ev = _ev(
            {
                "object_creations": [
                    {
                        "type_name": "MyCustomClass",
                        "in_using": False,
                        "line": 10,
                        "file": "App.cs",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_multiple_disposable_types(self) -> None:
        ev = _ev(
            {
                "object_creations": [
                    {"type_name": "HttpClient", "in_using": False, "line": 5, "file": "A.cs"},
                    {
                        "type_name": "StreamWriter",
                        "in_using": False,
                        "line": 8,
                        "file": "A.cs",
                    },
                    {
                        "type_name": "MemoryStream",
                        "in_using": True,
                        "line": 11,
                        "file": "A.cs",
                    },
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 2
        assert all(f.rag == "amber" for f in result.findings)


# ---------------------------------------------------------------------------
# csharp-blocking-async
# ---------------------------------------------------------------------------


class TestCSharpBlockingAsyncRule:
    rule = CSharpBlockingAsyncRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "csharp-blocking-async"
        assert self.rule.required_collectors == ["csharp-ast"]

    def test_registered(self) -> None:
        assert "csharp-blocking-async" in rule_registry

    def test_detects_result_access(self) -> None:
        ev = _ev(
            {
                "blocking_calls": [
                    {
                        "expression": "task.Result",
                        "call_type": ".Result",
                        "line": 12,
                        "file": "Worker.cs",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "red"
        assert f.severity == "high"
        assert ".Result" in f.summary
        assert f.pattern_tag == "csharp-blocking-async"

    def test_detects_wait_call(self) -> None:
        ev = _ev(
            {
                "blocking_calls": [
                    {
                        "expression": "task.Wait()",
                        "call_type": ".Wait",
                        "line": 18,
                        "file": "Worker.cs",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "red"

    def test_clean_no_blocking(self) -> None:
        ev = _ev({"blocking_calls": []})
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"

    def test_skipped_no_evidence(self) -> None:
        result = self.rule.evaluate(_non_cs_evidence(), None)
        assert result.skipped


# ---------------------------------------------------------------------------
# Cross-language: bare-except with C# evidence
# ---------------------------------------------------------------------------


class TestBareExceptCSharp:
    rule = BareExceptCatchAllRule()

    def test_bare_catch_amber(self) -> None:
        ev = _ev(
            {
                "catch_blocks": [
                    {
                        "caught_type": "",
                        "rethrows": False,
                        "has_logging": False,
                        "line": 5,
                        "file": "Program.cs",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_broad_exception_red(self) -> None:
        ev = _ev(
            {
                "catch_blocks": [
                    {
                        "caught_type": "Exception",
                        "rethrows": False,
                        "has_logging": False,
                        "line": 10,
                        "file": "Handler.cs",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"

    def test_system_exception_red(self) -> None:
        ev = _ev(
            {
                "catch_blocks": [
                    {
                        "caught_type": "SystemException",
                        "rethrows": False,
                        "has_logging": False,
                        "line": 15,
                        "file": "Handler.cs",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "red"

    def test_clean_specific_catch_green(self) -> None:
        ev = _ev(
            {
                "catch_blocks": [
                    {
                        "caught_type": "InvalidOperationException",
                        "rethrows": False,
                        "has_logging": True,
                        "line": 5,
                        "file": "Program.cs",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# Cross-language: logging-to-stdout with C# evidence
# ---------------------------------------------------------------------------


class TestLoggingToStdoutCSharp:
    rule = LoggingToStdoutRule()

    def test_console_writeline_amber(self) -> None:
        ev = _ev(
            {
                "log_statements": [
                    {"method": "Console.WriteLine", "line": 8, "file": "Program.cs"}
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"

    def test_clean_no_stdout_green(self) -> None:
        ev = _ev({"log_statements": []})
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# Registry assertions
# ---------------------------------------------------------------------------


class TestCSharpRuleRegistry:
    def test_all_csharp_rules_registered(self) -> None:
        expected = [
            "csharp-async-void",
            "csharp-configure-await",
            "csharp-disposable-no-using",
            "csharp-blocking-async",
        ]
        for rule_id in expected:
            assert rule_id in rule_registry, f"{rule_id} not registered"

    def test_cross_language_rules_still_registered(self) -> None:
        assert "bare-except-catch-all" in rule_registry
        assert "logging-to-stdout" in rule_registry


# ---------------------------------------------------------------------------
# R007 field compliance
# ---------------------------------------------------------------------------


class TestR007FieldCompliance:
    def test_async_void_finding_fields(self) -> None:
        rule = CSharpAsyncVoidRule()
        ev = _ev(
            {
                "methods": [
                    {
                        "name": "Bad",
                        "line": 1,
                        "is_async": True,
                        "return_type": "void",
                        "modifiers": ["async"],
                    }
                ],
            }
        )
        result = rule.evaluate([ev], None)
        f = result.findings[0]
        assert f.rule_id == "csharp-async-void"
        assert f.rag in ("red", "amber", "green")
        assert f.severity in ("high", "medium", "low", "info")
        assert f.summary
        assert f.recommendation
        assert f.evidence_locator
        assert f.collector_name
        assert f.collector_version
        assert f.confidence > 0
        assert f.pattern_tag

    def test_blocking_async_finding_fields(self) -> None:
        rule = CSharpBlockingAsyncRule()
        ev = _ev(
            {
                "blocking_calls": [
                    {
                        "expression": "t.Result",
                        "call_type": ".Result",
                        "line": 5,
                        "file": "X.cs",
                    }
                ],
            }
        )
        result = rule.evaluate([ev], None)
        f = result.findings[0]
        assert f.rule_id == "csharp-blocking-async"
        assert f.rag in ("red", "amber", "green")
        assert f.severity in ("high", "medium", "low", "info")
        assert f.summary
        assert f.recommendation
        assert f.evidence_locator
        assert f.collector_name
        assert f.collector_version
        assert f.confidence > 0
        assert f.pattern_tag
