"""Tests for the PythonAstCollector — parsing, payload structure, and extraction accuracy."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.python_ast import PythonAstCollector
from nfr_review.registry import collector_registry

FIXTURES = Path(__file__).parent / "fixtures" / "python-sample-repo"


@pytest.fixture
def collector() -> PythonAstCollector:
    return PythonAstCollector()


class TestRegistration:
    def test_collector_registered(self) -> None:
        import nfr_review.collectors  # noqa: F401

        assert "python-ast" in collector_registry

    def test_parser_init(self, collector: PythonAstCollector) -> None:
        assert collector._get_parser() is not None


class TestCollectOnFixtures:
    def test_returns_evidence_for_each_py_file(self, collector: PythonAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert len(results) >= 6
        assert all(e.kind == "python-ast-file" for e in results)
        assert all(e.collector_name == "python-ast" for e in results)

    def test_payload_has_required_keys(self, collector: PythonAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        required_keys = {
            "file_path",
            "catch_blocks",
            "log_statements",
            "functions",
            "imports",
            "async_calls",
        }
        for ev in results:
            assert required_keys.issubset(ev.payload.keys()), f"Missing keys in {ev.locator}"

    def test_skips_hidden_directories(
        self, collector: PythonAstCollector, tmp_path: Path
    ) -> None:
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "secret.py").write_text("x = 1\n")
        (tmp_path / "visible.py").write_text("y = 2\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].locator == "visible.py"


class TestCatchBlockExtraction:
    def _get_payload(self, collector: PythonAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_bare_except(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_exceptions.py")
        blocks = payload["catch_blocks"]
        bare = [b for b in blocks if b["caught_type"] == ""]
        assert len(bare) >= 1
        assert bare[0]["rethrows"] is False

    def test_broad_except_silent(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_exceptions.py")
        blocks = payload["catch_blocks"]
        silent = [
            b
            for b in blocks
            if b["caught_type"] == "Exception" and not b["rethrows"] and not b["has_logging"]
        ]
        assert len(silent) >= 1

    def test_broad_except_with_logging(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_exceptions.py")
        blocks = payload["catch_blocks"]
        logged = [b for b in blocks if b["caught_type"] == "Exception" and b["has_logging"]]
        assert len(logged) >= 1

    def test_rethrow_detection(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_exceptions.py")
        blocks = payload["catch_blocks"]
        rethrows = [b for b in blocks if b["rethrows"]]
        assert len(rethrows) >= 1

    def test_catch_block_has_file_field(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_exceptions.py")
        for block in payload["catch_blocks"]:
            assert "file" in block
            assert "bad_exceptions.py" in block["file"]


class TestFunctionExtraction:
    def _get_payload(self, collector: PythonAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_mutable_list_default(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_defaults.py")
        funcs = payload["functions"]
        fn = next(f for f in funcs if f["name"] == "mutable_list_default")
        assert len(fn["default_args"]) == 1
        assert fn["default_args"][0]["default_type"] == "list"

    def test_mutable_dict_default(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_defaults.py")
        funcs = payload["functions"]
        fn = next(f for f in funcs if f["name"] == "mutable_dict_default")
        assert len(fn["default_args"]) == 1
        assert fn["default_args"][0]["default_type"] == "dict"

    def test_mutable_set_default(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_defaults.py")
        funcs = payload["functions"]
        fn = next(f for f in funcs if f["name"] == "mutable_set_default")
        assert len(fn["default_args"]) == 1
        assert fn["default_args"][0]["default_type"] == "set"

    def test_immutable_default_not_flagged(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_defaults.py")
        funcs = payload["functions"]
        fn = next(f for f in funcs if f["name"] == "immutable_default")
        mutable = [
            d for d in fn["default_args"] if d["default_type"] in ("list", "dict", "set")
        ]
        assert len(mutable) == 0

    def test_async_function_detected(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_async.py")
        funcs = payload["functions"]
        async_funcs = [f for f in funcs if f["is_async"]]
        assert len(async_funcs) >= 2


class TestImportExtraction:
    def _get_payload(self, collector: PythonAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_star_imports_detected(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_imports.py")
        stars = [i for i in payload["imports"] if i["is_star"]]
        assert len(stars) >= 2
        modules = {i["module"] for i in stars}
        assert "os" in modules
        assert "sys" in modules

    def test_explicit_import_not_star(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_imports.py")
        explicit = [
            i for i in payload["imports"] if not i["is_star"] and i["module"] == "collections"
        ]
        assert len(explicit) == 1
        assert "OrderedDict" in explicit[0]["names"]


class TestLogStatementExtraction:
    def _get_payload(self, collector: PythonAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_print_detected(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_logging.py")
        methods = [s["method"] for s in payload["log_statements"]]
        assert "print" in methods

    def test_stdout_write_detected(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_logging.py")
        methods = [s["method"] for s in payload["log_statements"]]
        assert "sys.stdout.write" in methods

    def test_stderr_write_detected(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_logging.py")
        methods = [s["method"] for s in payload["log_statements"]]
        assert "sys.stderr.write" in methods


class TestAsyncCallExtraction:
    def _get_payload(self, collector: PythonAstCollector, filename: str) -> dict:
        results = collector.collect(FIXTURES, config=None)
        return next(e for e in results if filename in e.locator).payload

    def test_fire_and_forget_detected(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_async.py")
        unstored = [c for c in payload["async_calls"] if not c["stored"]]
        assert len(unstored) >= 1

    def test_stored_task_detected(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_async.py")
        stored = [c for c in payload["async_calls"] if c["stored"]]
        assert len(stored) >= 1

    def test_async_call_names(self, collector: PythonAstCollector) -> None:
        payload = self._get_payload(collector, "bad_async.py")
        call_names = {c["call"] for c in payload["async_calls"]}
        assert "asyncio.create_task" in call_names


class TestEdgeCases:
    def test_empty_file(self, collector: PythonAstCollector, tmp_path: Path) -> None:
        (tmp_path / "empty.py").write_text("")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        p = results[0].payload
        assert p["catch_blocks"] == []
        assert p["log_statements"] == []
        assert p["functions"] == []
        assert p["imports"] == []
        assert p["async_calls"] == []

    def test_non_py_files_ignored(self, collector: PythonAstCollector, tmp_path: Path) -> None:
        (tmp_path / "readme.md").write_text("# Hello")
        (tmp_path / "config.yaml").write_text("key: val")
        (tmp_path / "actual.py").write_text("x = 1\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert results[0].locator == "actual.py"

    def test_good_code_has_minimal_findings(self, collector: PythonAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        good = next(e for e in results if "good_code.py" in e.locator)
        p = good.payload
        stars = [i for i in p["imports"] if i["is_star"]]
        assert len(stars) == 0
        unstored_async = [c for c in p["async_calls"] if not c["stored"]]
        assert len(unstored_async) == 0
        mutable_defaults = [
            d
            for f in p["functions"]
            for d in f["default_args"]
            if d["default_type"] in ("list", "dict", "set")
        ]
        assert len(mutable_defaults) == 0
