"""Tests for the 4 Go-specific NFR rules."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.go_defer_in_loop import GoDeferInLoopRule
from nfr_review.rules.go_error_ignored import GoErrorIgnoredRule
from nfr_review.rules.go_goroutine_leak import GoGoroutineLeakRule
from nfr_review.rules.go_http_no_timeout import GoHttpNoTimeoutRule

_COLLECTOR = "go-ast"
_VERSION = "0.1.0"
_KIND = "go-ast-file"


def _ev(payload: dict, locator: str = "main.go") -> Evidence:
    return Evidence(
        collector_name=_COLLECTOR,
        collector_version=_VERSION,
        locator=locator,
        kind=_KIND,
        payload={"file_path": locator, **payload},
    )


def _non_go_evidence() -> list[Evidence]:
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
# go-error-ignored
# ---------------------------------------------------------------------------


class TestGoErrorIgnoredRule:
    rule = GoErrorIgnoredRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "go-error-ignored"
        assert self.rule.required_collectors == ["go-ast"]

    def test_registered(self) -> None:
        assert "go-error-ignored" in rule_registry

    def test_detects_ignored_error(self) -> None:
        ev = _ev(
            {
                "error_assignments": [
                    {"call": "os.Open", "error_ignored": True, "line": 10, "file": "main.go"},
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert result.findings[0].pattern_tag == "go-error-ignored"
        assert "os.Open" in result.findings[0].summary

    def test_multiple_ignored_errors(self) -> None:
        ev = _ev(
            {
                "error_assignments": [
                    {"call": "os.Open", "error_ignored": True, "line": 5, "file": "main.go"},
                    {
                        "call": "json.Unmarshal",
                        "error_ignored": True,
                        "line": 12,
                        "file": "main.go",
                    },
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 2

    def test_green_no_ignored_errors(self) -> None:
        ev = _ev({"error_assignments": []})
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_green_when_errors_handled(self) -> None:
        ev = _ev(
            {
                "error_assignments": [
                    {"call": "os.Open", "error_ignored": False, "line": 10, "file": "main.go"},
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_skipped_no_go_evidence(self) -> None:
        result = self.rule.evaluate(_non_go_evidence(), None)
        assert result.skipped
        assert "no go-ast" in result.skip_reason


# ---------------------------------------------------------------------------
# go-goroutine-leak
# ---------------------------------------------------------------------------


class TestGoGoroutineLeakRule:
    rule = GoGoroutineLeakRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "go-goroutine-leak"
        assert self.rule.required_collectors == ["go-ast"]

    def test_registered(self) -> None:
        assert "go-goroutine-leak" in rule_registry

    def test_detects_goroutine_launch(self) -> None:
        ev = _ev(
            {
                "goroutine_launches": [
                    {"expression": "func() { process() }()", "line": 15, "file": "main.go"},
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert result.findings[0].pattern_tag == "go-goroutine-leak"

    def test_multiple_goroutines(self) -> None:
        ev = _ev(
            {
                "goroutine_launches": [
                    {"expression": "func() {}()", "line": 10, "file": "main.go"},
                    {"expression": "handleConn(c)", "line": 20, "file": "main.go"},
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 2

    def test_green_no_goroutines(self) -> None:
        ev = _ev({"goroutine_launches": []})
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_skipped_no_go_evidence(self) -> None:
        result = self.rule.evaluate(_non_go_evidence(), None)
        assert result.skipped


# ---------------------------------------------------------------------------
# go-http-no-timeout
# ---------------------------------------------------------------------------


class TestGoHttpNoTimeoutRule:
    rule = GoHttpNoTimeoutRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "go-http-no-timeout"
        assert self.rule.required_collectors == ["go-ast"]

    def test_registered(self) -> None:
        assert "go-http-no-timeout" in rule_registry

    def test_default_client_call_is_red(self) -> None:
        ev = _ev(
            {
                "http_calls": [
                    {"call": "http.Get", "has_timeout": False, "line": 8, "file": "main.go"},
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"
        assert result.findings[0].pattern_tag == "go-http-no-timeout"

    def test_all_default_client_calls_are_red(self) -> None:
        ev = _ev(
            {
                "http_calls": [
                    {"call": "http.Get", "has_timeout": False, "line": 5, "file": "main.go"},
                    {"call": "http.Post", "has_timeout": False, "line": 6, "file": "main.go"},
                    {"call": "http.Head", "has_timeout": False, "line": 7, "file": "main.go"},
                    {
                        "call": "http.PostForm",
                        "has_timeout": False,
                        "line": 8,
                        "file": "main.go",
                    },
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 4
        assert all(f.rag == "red" for f in result.findings)

    def test_client_without_timeout_is_amber(self) -> None:
        ev = _ev(
            {
                "http_calls": [
                    {
                        "call": "http.Client",
                        "has_timeout": False,
                        "line": 12,
                        "file": "main.go",
                    },
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"

    def test_client_with_timeout_no_finding(self) -> None:
        ev = _ev(
            {
                "http_calls": [
                    {
                        "call": "http.Client",
                        "has_timeout": True,
                        "line": 12,
                        "file": "main.go",
                    },
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_green_no_http_calls(self) -> None:
        ev = _ev({"http_calls": []})
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_skipped_no_go_evidence(self) -> None:
        result = self.rule.evaluate(_non_go_evidence(), None)
        assert result.skipped


# ---------------------------------------------------------------------------
# go-defer-in-loop
# ---------------------------------------------------------------------------


class TestGoDeferInLoopRule:
    rule = GoDeferInLoopRule()

    def test_attributes(self) -> None:
        assert self.rule.id == "go-defer-in-loop"
        assert self.rule.required_collectors == ["go-ast"]

    def test_registered(self) -> None:
        assert "go-defer-in-loop" in rule_registry

    def test_detects_defer_in_loop(self) -> None:
        ev = _ev(
            {
                "defer_statements": [
                    {
                        "expression": "f.Close()",
                        "in_loop": True,
                        "line": 20,
                        "file": "main.go",
                    },
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert result.findings[0].severity == "medium"
        assert result.findings[0].pattern_tag == "go-defer-in-loop"

    def test_defer_outside_loop_is_green(self) -> None:
        ev = _ev(
            {
                "defer_statements": [
                    {
                        "expression": "f.Close()",
                        "in_loop": False,
                        "line": 5,
                        "file": "main.go",
                    },
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_multiple_defers_in_loop(self) -> None:
        ev = _ev(
            {
                "defer_statements": [
                    {
                        "expression": "f.Close()",
                        "in_loop": True,
                        "line": 10,
                        "file": "main.go",
                    },
                    {
                        "expression": "conn.Close()",
                        "in_loop": True,
                        "line": 15,
                        "file": "main.go",
                    },
                ],
            }
        )
        result = self.rule.evaluate([ev], None)
        assert len(result.findings) == 2

    def test_green_no_defer_statements(self) -> None:
        ev = _ev({"defer_statements": []})
        result = self.rule.evaluate([ev], None)
        assert result.findings[0].rag == "green"

    def test_skipped_no_go_evidence(self) -> None:
        result = self.rule.evaluate(_non_go_evidence(), None)
        assert result.skipped
