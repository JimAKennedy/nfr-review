"""Tests for the C++ AST collector."""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.collectors.cpp_ast import CppAstCollector

FIXTURES = Path(__file__).parent / "fixtures" / "cpp-ast-sample-repo"


@pytest.fixture()
def collector() -> CppAstCollector:
    return CppAstCollector()


class TestGoodCode:
    def test_parses_good_cpp(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        good_cpp = [e for e in results if "good_code.cpp" in e.payload["file_path"]]
        assert len(good_cpp) == 1
        payload = good_cpp[0].payload
        assert payload["functions"]
        func_names = [f["name"] for f in payload["functions"]]
        assert "main" in func_names

    def test_extracts_smart_pointers(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        good_cpp = [e for e in results if "good_code.cpp" in e.payload["file_path"]]
        payload = good_cpp[0].payload
        smart_kinds = {sp["kind"] for sp in payload["smart_pointers"]}
        assert "unique_ptr" in smart_kinds or "shared_ptr" in smart_kinds

    def test_good_code_no_new_delete(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        good_cpp = [e for e in results if "good_code.cpp" in e.payload["file_path"]]
        payload = good_cpp[0].payload
        assert len(payload["new_expressions"]) == 0
        assert len(payload["delete_expressions"]) == 0

    def test_extracts_namespaces(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        good_cpp = [e for e in results if "good_code.cpp" in e.payload["file_path"]]
        payload = good_cpp[0].payload
        assert "example" in payload["namespaces"]

    def test_extracts_includes(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        good_cpp = [e for e in results if "good_code.cpp" in e.payload["file_path"]]
        payload = good_cpp[0].payload
        include_paths = [inc["path"] for inc in payload["includes"]]
        assert "good_code.h" in include_paths
        system_includes = [inc for inc in payload["includes"] if inc["is_system"]]
        assert len(system_includes) >= 1


class TestBadMemory:
    def test_detects_new_expressions(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        bad_mem = [e for e in results if "bad_memory.cpp" in e.payload["file_path"]]
        assert len(bad_mem) == 1
        payload = bad_mem[0].payload
        assert len(payload["new_expressions"]) >= 3

    def test_detects_delete_expressions(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        bad_mem = [e for e in results if "bad_memory.cpp" in e.payload["file_path"]]
        payload = bad_mem[0].payload
        assert len(payload["delete_expressions"]) >= 2

    def test_detects_malloc_calls(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        bad_mem = [e for e in results if "bad_memory.cpp" in e.payload["file_path"]]
        payload = bad_mem[0].payload
        malloc_names = {m["call"] for m in payload["malloc_calls"]}
        assert "malloc" in malloc_names
        assert "free" in malloc_names

    def test_detects_raw_pointers(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        bad_mem = [e for e in results if "bad_memory.cpp" in e.payload["file_path"]]
        payload = bad_mem[0].payload
        assert len(payload["raw_pointers"]) >= 1


class TestBadIncludes:
    def test_header_missing_include_guard(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        bad_h = [e for e in results if "bad_includes.h" in e.payload["file_path"]]
        assert len(bad_h) == 1
        payload = bad_h[0].payload
        assert payload["has_pragma_once"] is False
        assert payload["has_include_guard"] is False

    def test_good_header_has_pragma_once(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        good_h = [e for e in results if "good_code.h" in e.payload["file_path"]]
        assert len(good_h) == 1
        payload = good_h[0].payload
        assert payload["has_pragma_once"] is True


class TestTemplateCode:
    def test_parses_templates_without_error(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        tmpl = [e for e in results if "template_code.cpp" in e.payload["file_path"]]
        assert len(tmpl) == 1
        payload = tmpl[0].payload
        assert payload["functions"]

    def test_extracts_class_from_template(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        tmpl = [e for e in results if "template_code.cpp" in e.payload["file_path"]]
        payload = tmpl[0].payload
        class_names = [c["name"] for c in payload["classes"]]
        assert "Container" in class_names


class TestCollectorMetadata:
    def test_evidence_kind(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert all(e.kind == "cpp-ast-file" for e in results)

    def test_collector_name(self, collector: CppAstCollector) -> None:
        assert collector.name == "cpp-ast"

    def test_file_extensions(self, collector: CppAstCollector) -> None:
        assert ".cpp" in collector.file_extensions
        assert ".h" in collector.file_extensions
        assert ".hpp" in collector.file_extensions

    def test_collects_all_fixture_files(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        file_paths = {e.payload["file_path"] for e in results}
        assert len(file_paths) == 5

    def test_log_statements_contract(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for e in results:
            assert "log_statements" in e.payload
