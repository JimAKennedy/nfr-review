"""Tests for 4 Node.js-specific NFR rules and Node.js entries in cross-language rules."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.ast_bare_except import BareExceptCatchAllRule
from nfr_review.rules.ast_logging_stdout import LoggingToStdoutRule
from nfr_review.rules.nodejs_callback_error_ignored import NodejsCallbackErrorIgnoredRule
from nfr_review.rules.nodejs_floating_promise import NodejsFloatingPromiseRule
from nfr_review.rules.nodejs_promise_no_catch import NodejsPromiseNoCatchRule
from nfr_review.rules.nodejs_sync_fs_api import NodejsSyncFsApiRule

_COLLECTOR = "nodejs-ast"
_VERSION = "0.1.0"
_KIND = "nodejs-ast-file"


def _ev(payload: dict, locator: str = "app.js") -> Evidence:
    return Evidence(
        collector_name=_COLLECTOR,
        collector_version=_VERSION,
        locator=locator,
        kind=_KIND,
        payload={"file_path": locator, **payload},
    )


def _non_js_evidence() -> list[Evidence]:
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
# nodejs-floating-promise
# ---------------------------------------------------------------------------


class TestNodejsFloatingPromiseRule:
    rule = NodejsFloatingPromiseRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "nodejs-floating-promise"
        assert self.rule.required_collectors == ["nodejs-ast"]

    def test_registered(self) -> None:
        assert "nodejs-floating-promise" in rule_registry

    def test_detects_floating_promise(self) -> None:
        ev = _ev(
            {
                "promise_chains": [
                    {
                        "expression": "fetch('/api').then(r => r.json())",
                        "has_catch": False,
                        "line": 10,
                        "file": "app.js",
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
        assert "Floating promise" in f.summary
        assert f.pattern_tag == "nodejs-floating-promise"

    def test_clean_promise_with_catch(self) -> None:
        ev = _ev(
            {
                "promise_chains": [
                    {
                        "expression": "fetch('/api').then(r => r.json()).catch(handleError)",
                        "has_catch": True,
                        "line": 5,
                        "file": "app.js",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skipped_no_evidence(self) -> None:
        result = self.rule.evaluate(_non_js_evidence(), None)
        assert result.skipped
        assert "no nodejs-ast evidence" in result.skip_reason

    def test_r007_field_compliance(self) -> None:
        ev = _ev(
            {
                "promise_chains": [
                    {
                        "expression": "doSomething()",
                        "has_catch": False,
                        "line": 3,
                        "file": "index.js",
                    }
                ],
            },
            locator="index.js",
        )
        result = self.rule.evaluate([ev], None)
        f = result.findings[0]
        assert f.rule_id == "nodejs-floating-promise"
        assert f.rag in ("red", "amber", "green")
        assert f.severity in ("high", "medium", "low", "info")
        assert f.summary
        assert f.recommendation
        assert f.evidence_locator
        assert f.collector_name == _COLLECTOR
        assert f.collector_version == _VERSION
        assert f.confidence > 0
        assert f.pattern_tag


# ---------------------------------------------------------------------------
# nodejs-sync-fs-api
# ---------------------------------------------------------------------------


class TestNodejsSyncFsApiRule:
    rule = NodejsSyncFsApiRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "nodejs-sync-fs-api"
        assert self.rule.required_collectors == ["nodejs-ast"]

    def test_registered(self) -> None:
        assert "nodejs-sync-fs-api" in rule_registry

    def test_detects_sync_call(self) -> None:
        ev = _ev(
            {
                "sync_calls": [
                    {"method": "fs.readFileSync", "line": 7, "file": "config.js"},
                    {"method": "child_process.execSync", "line": 12, "file": "config.js"},
                ],
            },
            locator="config.js",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 2
        assert all(f.rag == "amber" for f in result.findings)
        assert all(f.severity == "medium" for f in result.findings)
        assert "readFileSync" in result.findings[0].summary
        assert "execSync" in result.findings[1].summary

    def test_clean_no_sync_calls(self) -> None:
        ev = _ev({"sync_calls": []})
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skipped_no_evidence(self) -> None:
        result = self.rule.evaluate(_non_js_evidence(), None)
        assert result.skipped


# ---------------------------------------------------------------------------
# nodejs-callback-error-ignored
# ---------------------------------------------------------------------------


class TestNodejsCallbackErrorIgnoredRule:
    rule = NodejsCallbackErrorIgnoredRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "nodejs-callback-error-ignored"
        assert self.rule.required_collectors == ["nodejs-ast"]

    def test_registered(self) -> None:
        assert "nodejs-callback-error-ignored" in rule_registry

    def test_detects_ignored_error(self) -> None:
        ev = _ev(
            {
                "callback_patterns": [
                    {
                        "function_name": "readFile",
                        "callback_param": "err",
                        "checks_error": False,
                        "line": 15,
                        "file": "io.js",
                    }
                ],
            },
            locator="io.js",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "err" in f.summary
        assert f.pattern_tag == "nodejs-callback-error-ignored"

    def test_clean_error_checked(self) -> None:
        ev = _ev(
            {
                "callback_patterns": [
                    {
                        "function_name": "readFile",
                        "callback_param": "err",
                        "checks_error": True,
                        "line": 15,
                        "file": "io.js",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skipped_no_evidence(self) -> None:
        result = self.rule.evaluate(_non_js_evidence(), None)
        assert result.skipped


# ---------------------------------------------------------------------------
# nodejs-promise-no-catch
# ---------------------------------------------------------------------------


class TestNodejsPromiseNoCatchRule:
    rule = NodejsPromiseNoCatchRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "nodejs-promise-no-catch"
        assert self.rule.required_collectors == ["nodejs-ast"]

    def test_registered(self) -> None:
        assert "nodejs-promise-no-catch" in rule_registry

    def test_detects_missing_catch(self) -> None:
        ev = _ev(
            {
                "promise_chains": [
                    {
                        "expression": "db.query().then(handle)",
                        "has_catch": False,
                        "line": 22,
                        "file": "db.js",
                    }
                ],
            },
            locator="db.js",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert ".then()" in f.summary
        assert f.pattern_tag == "nodejs-promise-no-catch"

    def test_clean_with_catch(self) -> None:
        ev = _ev(
            {
                "promise_chains": [
                    {
                        "expression": "db.query().then(handle).catch(err)",
                        "has_catch": True,
                        "line": 22,
                        "file": "db.js",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skipped_no_evidence(self) -> None:
        result = self.rule.evaluate(_non_js_evidence(), None)
        assert result.skipped


# ---------------------------------------------------------------------------
# Cross-language: bare-except with Node.js evidence
# ---------------------------------------------------------------------------


class TestBareExceptNodejs:
    rule = BareExceptCatchAllRule()

    def test_bare_catch_amber(self) -> None:
        ev = _ev(
            {
                "catch_blocks": [
                    {
                        "caught_type": "",
                        "rethrows": False,
                        "has_logging": False,
                        "line": 8,
                        "file": "handler.js",
                    }
                ],
            },
            locator="handler.js",
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "Bare except" in f.summary

    def test_rethrow_clean(self) -> None:
        ev = _ev(
            {
                "catch_blocks": [
                    {
                        "caught_type": "",
                        "rethrows": True,
                        "has_logging": False,
                        "line": 8,
                        "file": "handler.js",
                    }
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# Cross-language: logging-to-stdout with Node.js evidence
# ---------------------------------------------------------------------------


class TestLoggingToStdoutNodejs:
    rule = LoggingToStdoutRule()

    def test_console_log_amber(self) -> None:
        ev = _ev(
            {
                "log_statements": [
                    {"method": "console.log", "line": 5, "file": "app.js"},
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.rag == "amber"
        assert f.severity == "medium"
        assert "console.log" in f.summary

    def test_multiple_console_methods(self) -> None:
        ev = _ev(
            {
                "log_statements": [
                    {"method": "console.log", "line": 5, "file": "app.js"},
                    {"method": "console.warn", "line": 8, "file": "app.js"},
                    {"method": "process.stdout.write", "line": 12, "file": "app.js"},
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 3

    def test_clean_no_stdout(self) -> None:
        ev = _ev({"log_statements": []})
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# Registry: all 6 Node.js-relevant rules registered
# ---------------------------------------------------------------------------


class TestNodejsRuleRegistry:
    def test_all_nodejs_rules_registered(self) -> None:
        expected = [
            "nodejs-floating-promise",
            "nodejs-sync-fs-api",
            "nodejs-callback-error-ignored",
            "nodejs-promise-no-catch",
        ]
        for rule_id in expected:
            assert rule_id in rule_registry, f"{rule_id} not registered"

    def test_cross_language_rules_still_registered(self) -> None:
        assert "bare-except-catch-all" in rule_registry
        assert "logging-to-stdout" in rule_registry


# ---------------------------------------------------------------------------
# R007 field compliance across all Node.js rules
# ---------------------------------------------------------------------------


class TestR007FieldCompliance:
    """All findings from Node.js rules must have the required fields."""

    _rules = [
        NodejsFloatingPromiseRule(),
        NodejsSyncFsApiRule(),
        NodejsCallbackErrorIgnoredRule(),
        NodejsPromiseNoCatchRule(),
    ]

    _evidence = [
        _ev(
            {
                "promise_chains": [
                    {
                        "expression": "x()",
                        "has_catch": False,
                        "line": 1,
                        "file": "a.js",
                    }
                ],
                "sync_calls": [{"method": "fs.readFileSync", "line": 2, "file": "a.js"}],
                "callback_patterns": [
                    {
                        "function_name": "read",
                        "callback_param": "err",
                        "checks_error": False,
                        "line": 3,
                        "file": "a.js",
                    }
                ],
            }
        )
    ]

    def test_all_findings_have_required_fields(self) -> None:
        for rule in self._rules:
            result = rule.evaluate(self._evidence, None)
            assert not result.skipped, f"{rule.id} was skipped"
            for f in result.findings:
                assert f.rule_id, f"{rule.id}: missing rule_id"
                assert f.rag in ("red", "amber", "green"), f"{rule.id}: bad rag"
                assert f.severity in (
                    "critical",
                    "high",
                    "medium",
                    "low",
                    "info",
                ), f"{rule.id}: bad severity"
                assert f.summary, f"{rule.id}: empty summary"
                assert f.recommendation, f"{rule.id}: empty recommendation"
                assert f.evidence_locator, f"{rule.id}: empty evidence_locator"
                assert f.collector_name, f"{rule.id}: empty collector_name"
                assert f.collector_version, f"{rule.id}: empty collector_version"
                assert f.confidence > 0, f"{rule.id}: zero confidence"
                assert f.pattern_tag, f"{rule.id}: empty pattern_tag"
