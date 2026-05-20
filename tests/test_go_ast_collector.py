"""Tests for the GoAstCollector — parsing, payload structure, and extraction accuracy."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.go_ast import GoAstCollector
from nfr_review.registry import collector_registry

FIXTURES = Path(__file__).parent / "fixtures" / "go-sample-repo"


@pytest.fixture
def collector() -> GoAstCollector:
    return GoAstCollector()


class TestRegistration:
    def test_collector_registered(self) -> None:
        import nfr_review.collectors  # noqa: F401

        assert "go-ast" in collector_registry

    def test_registry_has_expected_count(self) -> None:
        import nfr_review.collectors  # noqa: F401

        assert len(collector_registry) >= 3

    def test_parser_init(self, collector: GoAstCollector) -> None:
        assert collector._get_parser() is not None

    def test_class_attributes(self, collector: GoAstCollector) -> None:
        assert collector.name == "go-ast"
        assert collector.version == "0.1.0"
        assert collector.language == "go"
        assert collector.file_extensions == (".go",)
        assert collector.evidence_kind == "go-ast-file"


class TestCollectOnFixtures:
    def test_returns_evidence_for_each_go_file(self, collector: GoAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert len(results) >= 7
        assert all(e.kind == "go-ast-file" for e in results)
        assert all(e.collector_name == "go-ast" for e in results)

    def test_payload_has_required_keys(self, collector: GoAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        required_keys = {
            "file_path",
            "catch_blocks",
            "log_statements",
            "functions",
            "error_assignments",
            "goroutine_launches",
            "http_calls",
            "defer_statements",
        }
        for ev in results:
            assert required_keys.issubset(ev.payload.keys()), f"Missing keys in {ev.locator}"

    def test_skips_hidden_directories(self, collector: GoAstCollector, tmp_path: Path) -> None:
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "secret.go").write_text("package main\n")
        (tmp_path / "visible.go").write_text("package main\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].locator == "visible.go"

    def test_skips_non_go_files(self, collector: GoAstCollector, tmp_path: Path) -> None:
        (tmp_path / "readme.md").write_text("# Hello")
        (tmp_path / "go.mod").write_text("module test\n")
        (tmp_path / "actual.go").write_text("package main\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].locator == "actual.go"


class TestCatchBlockExtraction:
    def _get_payload(self, collector: GoAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_recover_without_rethrow(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_exceptions.go")
        blocks = payload["catch_blocks"]
        non_rethrow = [b for b in blocks if not b["rethrows"]]
        assert len(non_rethrow) >= 1

    def test_recover_with_rethrow(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_exceptions.go")
        blocks = payload["catch_blocks"]
        rethrows = [b for b in blocks if b["rethrows"]]
        assert len(rethrows) >= 1

    def test_caught_type_always_empty(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_exceptions.go")
        for block in payload["catch_blocks"]:
            assert block["caught_type"] == ""

    def test_catch_block_has_file_field(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_exceptions.go")
        for block in payload["catch_blocks"]:
            assert "file" in block
            assert "bad_exceptions.go" in block["file"]

    def test_multiple_recovers_detected(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_exceptions.go")
        assert len(payload["catch_blocks"]) >= 3


class TestLogStatementExtraction:
    def _get_payload(self, collector: GoAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_fmt_println_detected(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_logging.go")
        methods = [s["method"] for s in payload["log_statements"]]
        assert "fmt.Println" in methods

    def test_fmt_printf_detected(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_logging.go")
        methods = [s["method"] for s in payload["log_statements"]]
        assert "fmt.Printf" in methods

    def test_fmt_print_detected(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_logging.go")
        methods = [s["method"] for s in payload["log_statements"]]
        assert "fmt.Print" in methods

    def test_log_println_detected(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_logging.go")
        methods = [s["method"] for s in payload["log_statements"]]
        assert "log.Println" in methods

    def test_log_fatal_detected(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_logging.go")
        methods = [s["method"] for s in payload["log_statements"]]
        assert "log.Fatal" in methods

    def test_log_statement_count(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_logging.go")
        assert len(payload["log_statements"]) >= 8

    def test_log_statement_has_file_field(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_logging.go")
        for stmt in payload["log_statements"]:
            assert "file" in stmt
            assert "bad_logging.go" in stmt["file"]


class TestErrorAssignmentExtraction:
    def _get_payload(self, collector: GoAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_blank_identifier_error_ignored(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_errors.go")
        assignments = payload["error_assignments"]
        assert len(assignments) >= 3

    def test_error_ignored_flag(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_errors.go")
        for ea in payload["error_assignments"]:
            assert ea["error_ignored"] is True

    def test_discarded_return_detected(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_errors.go")
        calls = [ea["call"] for ea in payload["error_assignments"]]
        discarded = [c for c in calls if c == "http.Get"]
        assert len(discarded) >= 2

    def test_error_assignment_has_file_field(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_errors.go")
        for ea in payload["error_assignments"]:
            assert "file" in ea
            assert "bad_errors.go" in ea["file"]


class TestGoroutineLaunchExtraction:
    def _get_payload(self, collector: GoAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_goroutine_count(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_goroutines.go")
        assert len(payload["goroutine_launches"]) >= 4

    def test_goroutine_has_expression(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_goroutines.go")
        for g in payload["goroutine_launches"]:
            assert g["expression"] != ""

    def test_bare_goroutine_call(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_goroutines.go")
        exprs = [g["expression"] for g in payload["goroutine_launches"]]
        assert any("doWork()" in e for e in exprs)

    def test_goroutine_has_file_field(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_goroutines.go")
        for g in payload["goroutine_launches"]:
            assert "file" in g
            assert "bad_goroutines.go" in g["file"]


class TestHttpCallExtraction:
    def _get_payload(self, collector: GoAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_default_client_calls_detected(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_http.go")
        calls = [h["call"] for h in payload["http_calls"]]
        assert "http.Get" in calls
        assert "http.Post" in calls
        assert "http.Head" in calls
        assert "http.PostForm" in calls

    def test_client_without_timeout(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_http.go")
        clients = [h for h in payload["http_calls"] if h["call"] == "http.Client"]
        no_timeout = [c for c in clients if not c["has_timeout"]]
        assert len(no_timeout) >= 1

    def test_client_with_timeout(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_http.go")
        clients = [h for h in payload["http_calls"] if h["call"] == "http.Client"]
        with_timeout = [c for c in clients if c["has_timeout"]]
        assert len(with_timeout) >= 1

    def test_http_call_count(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_http.go")
        assert len(payload["http_calls"]) >= 6

    def test_http_call_has_file_field(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_http.go")
        for h in payload["http_calls"]:
            assert "file" in h
            assert "bad_http.go" in h["file"]


class TestDeferStatementExtraction:
    def _get_payload(self, collector: GoAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_defer_in_for_loop(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_defer.go")
        in_loop = [d for d in payload["defer_statements"] if d["in_loop"]]
        assert len(in_loop) >= 2

    def test_defer_outside_loop(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_defer.go")
        outside = [d for d in payload["defer_statements"] if not d["in_loop"]]
        assert len(outside) >= 1

    def test_defer_has_expression(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_defer.go")
        for d in payload["defer_statements"]:
            assert d["expression"] != ""

    def test_defer_has_file_field(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_defer.go")
        for d in payload["defer_statements"]:
            assert "file" in d
            assert "bad_defer.go" in d["file"]


class TestFunctionExtraction:
    def _get_payload(self, collector: GoAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_function_count(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_errors.go")
        assert len(payload["functions"]) >= 4

    def test_function_names(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_errors.go")
        names = [f["name"] for f in payload["functions"]]
        assert "discardErrorWithBlank" in names
        assert "completelyDiscardReturn" in names

    def test_plain_function_has_empty_receiver(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "bad_errors.go")
        for f in payload["functions"]:
            assert f["receiver"] == ""


class TestGoodCode:
    def _get_payload(self, collector: GoAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_no_catch_blocks(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "good_code.go")
        assert len(payload["catch_blocks"]) == 0

    def test_no_error_assignments(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "good_code.go")
        assert len(payload["error_assignments"]) == 0

    def test_no_log_statements(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "good_code.go")
        assert len(payload["log_statements"]) == 0

    def test_no_defer_in_loop(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "good_code.go")
        in_loop = [d for d in payload["defer_statements"] if d["in_loop"]]
        assert len(in_loop) == 0

    def test_client_with_timeout(self, collector: GoAstCollector) -> None:
        payload = self._get_payload(collector, "good_code.go")
        clients = [h for h in payload["http_calls"] if h["call"] == "http.Client"]
        assert all(c["has_timeout"] for c in clients)


class TestEdgeCases:
    def test_empty_go_file(self, collector: GoAstCollector, tmp_path: Path) -> None:
        (tmp_path / "empty.go").write_text("package main\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        p = results[0].payload
        assert p["catch_blocks"] == []
        assert p["log_statements"] == []
        assert p["functions"] == []
        assert p["error_assignments"] == []
        assert p["goroutine_launches"] == []
        assert p["http_calls"] == []
        assert p["defer_statements"] == []
