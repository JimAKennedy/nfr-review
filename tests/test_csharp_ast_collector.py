"""Tests for the CSharpAstCollector — parsing, payload structure, and extraction accuracy."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.csharp_ast import CSharpAstCollector
from nfr_review.registry import collector_registry

FIXTURES = Path(__file__).parent / "fixtures" / "csharp-sample-repo"


@pytest.fixture
def collector() -> CSharpAstCollector:
    return CSharpAstCollector()


def _evidence_for(collector: CSharpAstCollector, filename: str) -> dict:
    results = collector.collect(FIXTURES, config=None)
    for e in results:
        if e.locator == filename:
            return e.payload
    pytest.fail(f"No evidence found for {filename}")


class TestRegistration:
    def test_collector_registered(self) -> None:
        import nfr_review.collectors  # noqa: F401

        assert "csharp-ast" in collector_registry

    def test_parser_init(self, collector: CSharpAstCollector) -> None:
        assert collector._get_parser() is not None

    def test_collector_metadata(self, collector: CSharpAstCollector) -> None:
        assert collector.name == "csharp-ast"
        assert collector.language == "csharp"
        assert collector.file_extensions == (".cs",)
        assert collector.evidence_kind == "csharp-ast-file"


class TestCollectOnFixtures:
    def test_returns_evidence_for_each_cs_file(self, collector: CSharpAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert len(results) == 5
        assert all(e.kind == "csharp-ast-file" for e in results)
        assert all(e.collector_name == "csharp-ast" for e in results)

    def test_payload_has_required_keys(self, collector: CSharpAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        required_keys = {
            "file_path",
            "catch_blocks",
            "log_statements",
            "methods",
            "await_expressions",
            "object_creations",
            "blocking_calls",
        }
        for ev in results:
            assert required_keys.issubset(ev.payload.keys()), f"Missing keys in {ev.locator}"

    def test_skips_hidden_directories(
        self, collector: CSharpAstCollector, tmp_path: Path
    ) -> None:
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "secret.cs").write_text("class X {}\n")
        (tmp_path / "visible.cs").write_text("class Y {}\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].locator == "visible.cs"

    def test_skips_bin_obj_directories(
        self, collector: CSharpAstCollector, tmp_path: Path
    ) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config.cs").write_text("class X {}\n")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.cs").write_text("class Y {}\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].locator == "src/main.cs"


class TestCatchBlockExtraction:
    def test_bare_catch(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.cs")
        bare = [c for c in payload["catch_blocks"] if c["caught_type"] == ""]
        assert len(bare) == 1
        assert bare[0]["rethrows"] is False

    def test_catch_exception(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.cs")
        exc = [c for c in payload["catch_blocks"] if c["caught_type"] == "Exception"]
        assert len(exc) == 1
        assert exc[0]["rethrows"] is False
        assert exc[0]["has_logging"] is True

    def test_catch_without_rethrow(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.cs")
        inv = [
            c
            for c in payload["catch_blocks"]
            if c["caught_type"] == "InvalidOperationException"
        ]
        assert len(inv) == 1
        assert inv[0]["rethrows"] is False

    def test_catch_with_rethrow(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.cs")
        io = [c for c in payload["catch_blocks"] if c["caught_type"] == "IOException"]
        assert len(io) == 1
        assert io[0]["rethrows"] is True

    def test_catch_count(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_exceptions.cs")
        assert len(payload["catch_blocks"]) == 4


class TestLogStatementExtraction:
    def test_console_writeline(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.cs")
        wl = [s for s in payload["log_statements"] if s["method"] == "Console.WriteLine"]
        assert len(wl) >= 3

    def test_console_write(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.cs")
        w = [s for s in payload["log_statements"] if s["method"] == "Console.Write"]
        assert len(w) >= 1

    def test_debug_writeline(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.cs")
        dw = [s for s in payload["log_statements"] if s["method"] == "Debug.WriteLine"]
        assert len(dw) >= 1

    def test_log_count(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_logging.cs")
        assert len(payload["log_statements"]) == 7


class TestMethodExtraction:
    def test_async_void_detected(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.cs")
        async_voids = [
            m for m in payload["methods"] if m["is_async"] and m["return_type"] == "void"
        ]
        assert len(async_voids) >= 2

    def test_async_task_detected(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.cs")
        async_tasks = [
            m
            for m in payload["methods"]
            if m["is_async"] and m["return_type"].startswith("Task")
        ]
        assert len(async_tasks) >= 3

    def test_sync_method(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.cs")
        sync = [m for m in payload["methods"] if not m["is_async"]]
        assert len(sync) >= 3

    def test_modifiers_present(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.cs")
        ff = next(m for m in payload["methods"] if m["name"] == "FireAndForget")
        assert "public" in ff["modifiers"]
        assert "async" in ff["modifiers"]


class TestAwaitExtraction:
    def test_await_with_configure_await(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.cs")
        with_ca = [a for a in payload["await_expressions"] if a["has_configure_await"]]
        assert len(with_ca) >= 1

    def test_await_without_configure_await(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.cs")
        without_ca = [a for a in payload["await_expressions"] if not a["has_configure_await"]]
        assert len(without_ca) >= 2

    def test_await_expression_text(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.cs")
        exprs = [a["expression"] for a in payload["await_expressions"]]
        assert any("ConfigureAwait" in e for e in exprs)


class TestObjectCreationExtraction:
    def test_filestream_without_using(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_disposable.cs")
        leaked = [
            o
            for o in payload["object_creations"]
            if o["type_name"] == "FileStream" and not o["in_using"]
        ]
        assert len(leaked) == 1

    def test_sqlconnection_without_using(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_disposable.cs")
        leaked = [
            o
            for o in payload["object_creations"]
            if o["type_name"] == "SqlConnection" and not o["in_using"]
        ]
        assert len(leaked) == 1

    def test_filestream_with_using(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_disposable.cs")
        proper = [
            o
            for o in payload["object_creations"]
            if o["type_name"] == "FileStream" and o["in_using"]
        ]
        assert len(proper) == 2

    def test_creation_count(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_disposable.cs")
        assert len(payload["object_creations"]) == 5


class TestBlockingCallExtraction:
    def test_dot_result(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.cs")
        results = [b for b in payload["blocking_calls"] if b["call_type"] == ".Result"]
        assert len(results) == 1
        assert ".Result" in results[0]["expression"]

    def test_dot_wait(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.cs")
        waits = [b for b in payload["blocking_calls"] if b["call_type"] == ".Wait"]
        assert len(waits) == 1
        assert ".Wait()" in waits[0]["expression"]

    def test_get_awaiter_get_result(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.cs")
        ga = [b for b in payload["blocking_calls"] if b["call_type"] == ".GetAwaiter"]
        assert len(ga) == 1
        assert "GetAwaiter" in ga[0]["expression"]

    def test_blocking_count(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "bad_async.cs")
        assert len(payload["blocking_calls"]) == 3


class TestGoodCode:
    def test_no_log_statements(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.cs")
        assert len(payload["log_statements"]) == 0

    def test_no_blocking_calls(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.cs")
        assert len(payload["blocking_calls"]) == 0

    def test_all_objects_in_using(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.cs")
        assert all(o["in_using"] for o in payload["object_creations"])

    def test_all_awaits_have_configure_await(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.cs")
        assert all(a["has_configure_await"] for a in payload["await_expressions"])

    def test_catch_rethrows(self, collector: CSharpAstCollector) -> None:
        payload = _evidence_for(collector, "good_code.cs")
        assert len(payload["catch_blocks"]) == 1
        assert payload["catch_blocks"][0]["rethrows"] is True
