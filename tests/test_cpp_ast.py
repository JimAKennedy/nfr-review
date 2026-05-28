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


class TestClassHierarchy:
    """Tests for enriched class extraction: base classes, methods, fields."""

    def _get_hierarchy_payload(self, collector: CppAstCollector) -> dict:
        results = collector.collect(FIXTURES, config=None)
        hier = [e for e in results if "class_hierarchy.h" in e.payload["file_path"]]
        assert len(hier) == 1
        return hier[0].payload

    def _class_by_name(self, payload: dict, name: str) -> dict:
        for c in payload["classes"]:
            if c["name"] == name:
                return c
        raise AssertionError(f"Class {name!r} not found")

    def test_detects_abstract_class(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        audio = self._class_by_name(p, "AudioProcessor")
        assert audio["is_abstract"] is True

    def test_concrete_classes_not_abstract(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        plugin = self._class_by_name(p, "PluginProcessor")
        assert plugin["is_abstract"] is False

    def test_extracts_base_classes(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        plugin = self._class_by_name(p, "PluginProcessor")
        assert len(plugin["base_classes"]) == 1
        assert plugin["base_classes"][0]["name"] == "AudioProcessor"
        assert plugin["base_classes"][0]["access"] == "public"

    def test_multi_level_inheritance(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        reverb = self._class_by_name(p, "ReverbProcessor")
        assert len(reverb["base_classes"]) == 1
        assert reverb["base_classes"][0]["name"] == "EffectProcessor"

    def test_extracts_methods_with_access(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        audio = self._class_by_name(p, "AudioProcessor")
        method_names = [m["name"] for m in audio["methods"]]
        assert "processBlock" in method_names
        assert "getName" in method_names

    def test_pure_virtual_methods(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        audio = self._class_by_name(p, "AudioProcessor")
        pure = [m for m in audio["methods"] if m["is_pure_virtual"]]
        assert len(pure) == 2

    def test_virtual_methods(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        effect = self._class_by_name(p, "EffectProcessor")
        virtual_methods = [m for m in effect["methods"] if m["is_virtual"]]
        assert any(m["name"] == "setMix" for m in virtual_methods)

    def test_extracts_fields_with_access(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        audio = self._class_by_name(p, "AudioProcessor")
        protected_fields = [f for f in audio["fields"] if f["access"] == "protected"]
        assert len(protected_fields) == 2
        field_names = {f["name"] for f in protected_fields}
        assert "sampleRate_" in field_names
        assert "blockSize_" in field_names

    def test_private_fields(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        plugin = self._class_by_name(p, "PluginProcessor")
        private_fields = [f for f in plugin["fields"] if f["access"] == "private"]
        assert len(private_fields) == 2

    def test_struct_default_public(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        config = self._class_by_name(p, "Config")
        assert config["is_struct"] is True
        for f in config["fields"]:
            assert f["access"] == "public"

    def test_struct_methods(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        config = self._class_by_name(p, "Config")
        assert any(m["name"] == "validate" for m in config["methods"])

    def test_no_base_class_for_root(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        audio = self._class_by_name(p, "AudioProcessor")
        assert audio["base_classes"] == []

    def test_field_types(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        plugin = self._class_by_name(p, "PluginProcessor")
        field_types = {f["name"]: f["type"] for f in plugin["fields"]}
        assert field_types["gain_"] == "float"

    def test_has_destructor(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        audio = self._class_by_name(p, "AudioProcessor")
        assert audio["has_destructor"] is True

    def test_class_count(self, collector: CppAstCollector) -> None:
        p = self._get_hierarchy_payload(collector)
        assert len(p["classes"]) == 5


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
        assert len(file_paths) == 6

    def test_log_statements_contract(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for e in results:
            assert "log_statements" in e.payload
