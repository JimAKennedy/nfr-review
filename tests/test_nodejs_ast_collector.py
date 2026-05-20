"""Tests for the NodejsAstCollector — parsing, payload structure, and extraction accuracy."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.nodejs_ast import NodejsAstCollector
from nfr_review.registry import collector_registry

FIXTURES = Path(__file__).parent / "fixtures" / "nodejs-sample-repo"


@pytest.fixture
def collector() -> NodejsAstCollector:
    return NodejsAstCollector()


def _evidence_for(collector: NodejsAstCollector, filename: str) -> dict:
    results = collector.collect(FIXTURES, config=None)
    for e in results:
        if e.locator == filename:
            return e.payload
    pytest.fail(f"No evidence found for {filename}")


class TestRegistration:
    def test_collector_registered(self) -> None:
        import nfr_review.collectors  # noqa: F401

        assert "nodejs-ast" in collector_registry

    def test_parser_init(self, collector: NodejsAstCollector) -> None:
        assert collector._get_parser() is not None

    def test_collector_metadata(self, collector: NodejsAstCollector) -> None:
        assert collector.name == "nodejs-ast"
        assert collector.language == "typescript"
        assert collector.file_extensions == (".js", ".ts", ".jsx", ".tsx")
        assert collector.evidence_kind == "nodejs-ast-file"


class TestCollectOnFixtures:
    def test_returns_evidence_for_each_js_file(self, collector: NodejsAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        js_results = [e for e in results if e.locator.endswith(".js")]
        assert len(js_results) == 4
        assert all(e.kind == "nodejs-ast-file" for e in js_results)
        assert all(e.collector_name == "nodejs-ast" for e in js_results)

    def test_payload_has_required_keys(self, collector: NodejsAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        required_keys = {
            "file_path",
            "catch_blocks",
            "log_statements",
            "functions",
            "await_expressions",
            "promise_chains",
            "sync_calls",
            "callback_patterns",
        }
        for ev in results:
            if ev.locator.endswith(".js"):
                assert required_keys.issubset(ev.payload.keys()), (
                    f"Missing keys in {ev.locator}"
                )

    def test_file_path_set_correctly(self, collector: NodejsAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            if ev.locator.endswith(".js"):
                assert ev.payload["file_path"] == ev.locator

    def test_skips_hidden_directories(
        self, collector: NodejsAstCollector, tmp_path: Path
    ) -> None:
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "secret.js").write_text("function x() {}\n")
        (tmp_path / "visible.js").write_text("function y() {}\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].locator == "visible.js"

    def test_skips_node_modules(self, collector: NodejsAstCollector, tmp_path: Path) -> None:
        nm = tmp_path / "node_modules" / "dep"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module.exports = {};\n")
        (tmp_path / "app.js").write_text("const dep = require('./dep');\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].locator == "app.js"


class TestCatchBlockExtraction:
    def test_bare_catch_detected(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.js")
        assert len(payload["catch_blocks"]) == 4

    def test_caught_type_always_empty(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.js")
        assert all(c["caught_type"] == "" for c in payload["catch_blocks"])

    def test_rethrows_detection(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.js")
        rethrows = [c for c in payload["catch_blocks"] if c["rethrows"]]
        assert len(rethrows) == 1

    def test_no_rethrow_detection(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.js")
        no_rethrow = [c for c in payload["catch_blocks"] if not c["rethrows"]]
        assert len(no_rethrow) == 3

    def test_has_logging_detection(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.js")
        with_logging = [c for c in payload["catch_blocks"] if c["has_logging"]]
        assert len(with_logging) == 3

    def test_no_logging_in_bare_catch(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.js")
        silent = [c for c in payload["catch_blocks"] if not c["has_logging"]]
        assert len(silent) == 1

    def test_catch_has_file_and_line(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.js")
        for cb in payload["catch_blocks"]:
            assert cb["file"] == "bad_exceptions.js"
            assert isinstance(cb["line"], int)
            assert cb["line"] > 0


class TestLogStatementExtraction:
    def test_console_log(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.js")
        logs = [s for s in payload["log_statements"] if s["method"] == "console.log"]
        assert len(logs) == 2

    def test_console_warn(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.js")
        warns = [s for s in payload["log_statements"] if s["method"] == "console.warn"]
        assert len(warns) == 1

    def test_console_error(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.js")
        errors = [s for s in payload["log_statements"] if s["method"] == "console.error"]
        assert len(errors) == 1

    def test_console_info(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.js")
        infos = [s for s in payload["log_statements"] if s["method"] == "console.info"]
        assert len(infos) == 1

    def test_process_stdout_write(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.js")
        stdout = [
            s for s in payload["log_statements"] if s["method"] == "process.stdout.write"
        ]
        assert len(stdout) == 1

    def test_process_stderr_write(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.js")
        stderr = [
            s for s in payload["log_statements"] if s["method"] == "process.stderr.write"
        ]
        assert len(stderr) == 1

    def test_log_count(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.js")
        assert len(payload["log_statements"]) == 7

    def test_log_has_file_and_line(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.js")
        for ls in payload["log_statements"]:
            assert ls["file"] == "bad_logging.js"
            assert isinstance(ls["line"], int)
            assert ls["line"] > 0


class TestFunctionExtraction:
    def test_async_function_detected(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        async_fns = [
            f for f in payload["functions"] if f["is_async"] and f["kind"] == "function"
        ]
        assert len(async_fns) >= 2

    def test_sync_function_detected(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        sync_fns = [
            f for f in payload["functions"] if not f["is_async"] and f["kind"] == "function"
        ]
        assert len(sync_fns) >= 3

    def test_arrow_function_detected(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        arrows = [f for f in payload["functions"] if f["kind"] == "arrow"]
        assert len(arrows) >= 1

    def test_method_detected(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.js")
        methods = [f for f in payload["functions"] if f["kind"] == "method"]
        assert len(methods) >= 1

    def test_async_method_detected(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.js")
        async_methods = [
            f for f in payload["functions"] if f["is_async"] and f["kind"] == "method"
        ]
        assert len(async_methods) >= 1

    def test_function_name_captured(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        names = [f["name"] for f in payload["functions"]]
        assert "fetchData" in names
        assert "readConfig" in names
        assert "runCommand" in names

    def test_function_has_line(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        for fn in payload["functions"]:
            assert isinstance(fn["line"], int)
            assert fn["line"] > 0


class TestAwaitExtraction:
    def test_await_expressions_captured(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        assert len(payload["await_expressions"]) >= 1

    def test_await_expression_text(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        exprs = [a["expression"] for a in payload["await_expressions"]]
        assert any("fetch" in e for e in exprs)

    def test_await_has_file_and_line(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        for aw in payload["await_expressions"]:
            assert aw["file"] == "bad_async.js"
            assert isinstance(aw["line"], int)

    def test_good_code_has_many_awaits(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.js")
        assert len(payload["await_expressions"]) >= 6


class TestPromiseChainExtraction:
    def test_then_chain_without_catch(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        no_catch = [p for p in payload["promise_chains"] if not p["has_catch"]]
        assert len(no_catch) == 1

    def test_then_chain_with_catch(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        with_catch = [p for p in payload["promise_chains"] if p["has_catch"]]
        assert len(with_catch) == 1

    def test_promise_chain_count(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        assert len(payload["promise_chains"]) == 2

    def test_chain_has_expression_text(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        for pc in payload["promise_chains"]:
            assert ".then" in pc["expression"]

    def test_chain_has_file_and_line(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        for pc in payload["promise_chains"]:
            assert pc["file"] == "bad_async.js"
            assert isinstance(pc["line"], int)


class TestSyncCallExtraction:
    def test_read_file_sync(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        rfs = [s for s in payload["sync_calls"] if "readFileSync" in s["method"]]
        assert len(rfs) == 1

    def test_write_file_sync(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        wfs = [s for s in payload["sync_calls"] if "writeFileSync" in s["method"]]
        assert len(wfs) == 1

    def test_append_file_sync(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        afs = [s for s in payload["sync_calls"] if "appendFileSync" in s["method"]]
        assert len(afs) == 1

    def test_exec_sync(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        es = [s for s in payload["sync_calls"] if "execSync" in s["method"]]
        assert len(es) == 1

    def test_sync_call_count(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        assert len(payload["sync_calls"]) == 4

    def test_sync_call_has_file_and_line(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        for sc in payload["sync_calls"]:
            assert sc["file"] == "bad_async.js"
            assert isinstance(sc["line"], int)


class TestCallbackExtraction:
    def test_callback_without_error_check(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        no_check = [c for c in payload["callback_patterns"] if not c["checks_error"]]
        assert len(no_check) == 2

    def test_callback_with_error_check(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        with_check = [c for c in payload["callback_patterns"] if c["checks_error"]]
        assert len(with_check) == 1

    def test_callback_count(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        assert len(payload["callback_patterns"]) == 3

    def test_callback_function_name(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        names = {c["function_name"] for c in payload["callback_patterns"]}
        assert "fs.readFile" in names

    def test_callback_param_name(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        params = {c["callback_param"] for c in payload["callback_patterns"]}
        assert "err" in params
        assert "error" in params

    def test_callback_has_file_and_line(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.js")
        for cb in payload["callback_patterns"]:
            assert cb["file"] == "bad_async.js"
            assert isinstance(cb["line"], int)


class TestGoodCode:
    def test_no_log_statements(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.js")
        assert len(payload["log_statements"]) == 0

    def test_no_sync_calls(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.js")
        assert len(payload["sync_calls"]) == 0

    def test_no_promise_chains(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.js")
        assert len(payload["promise_chains"]) == 0

    def test_all_catches_rethrow(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.js")
        assert all(c["rethrows"] for c in payload["catch_blocks"])

    def test_callback_checks_error(self, collector: NodejsAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.js")
        assert all(c["checks_error"] for c in payload["callback_patterns"])
