# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for Go class diagram support (M030-S03).

Verifies the enriched Go AST collector produces struct/interface-level
structural data compatible with render_class_diagram, and that the
end-to-end pipeline generates correct Mermaid class diagrams from Go source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.go_ast import GoAstCollector

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "go-class-diagram"


@pytest.fixture(scope="module")
def go_evidence() -> list[Any]:
    collector = GoAstCollector()

    class Cfg:
        exclude_paths: list[str] = []
        exclude_test_paths = False

    return collector.collect(FIXTURE_DIR, Cfg())


@pytest.fixture(scope="module")
def all_structs(go_evidence: list[Any]) -> list[dict[str, Any]]:
    structs: list[dict[str, Any]] = []
    for ev in go_evidence:
        structs.extend(ev.payload.get("structs", []))
    return structs


def _find_struct(structs: list[dict], name: str) -> dict:
    for s in structs:
        if s["name"] == name:
            return s
    pytest.fail(f"Struct/interface {name!r} not found in {[s['name'] for s in structs]}")


# ---------------------------------------------------------------------------
# Unit tests — struct fields
# ---------------------------------------------------------------------------


class TestFieldExtraction:
    def test_config_has_three_fields(self, all_structs: list[dict]) -> None:
        config = _find_struct(all_structs, "Config")
        assert len(config["fields"]) == 3

    def test_field_names_and_types(self, all_structs: list[dict]) -> None:
        config = _find_struct(all_structs, "Config")
        field_map = {f["name"]: f["type"] for f in config["fields"]}
        assert field_map["Name"] == "string"
        assert field_map["maxThreads"] == "int"
        assert field_map["DebugMode"] == "bool"

    def test_field_access_exported(self, all_structs: list[dict]) -> None:
        config = _find_struct(all_structs, "Config")
        access_map = {f["name"]: f["access"] for f in config["fields"]}
        assert access_map["Name"] == "public"
        assert access_map["DebugMode"] == "public"

    def test_field_access_unexported(self, all_structs: list[dict]) -> None:
        config = _find_struct(all_structs, "Config")
        access_map = {f["name"]: f["access"] for f in config["fields"]}
        assert access_map["maxThreads"] == "private"

    def test_field_line_numbers(self, all_structs: list[dict]) -> None:
        config = _find_struct(all_structs, "Config")
        for field in config["fields"]:
            assert field["line"] > 0

    def test_pointer_field_type(self, all_structs: list[dict]) -> None:
        engine = _find_struct(all_structs, "Engine")
        config_field = next(f for f in engine["fields"] if f["name"] == "config")
        assert config_field["type"] == "*Config"

    def test_slice_field_type(self, all_structs: list[dict]) -> None:
        engine = _find_struct(all_structs, "Engine")
        plugins_field = next(f for f in engine["fields"] if f["name"] == "plugins")
        assert "Plugin" in plugins_field["type"]


# ---------------------------------------------------------------------------
# Unit tests — struct vs interface
# ---------------------------------------------------------------------------


class TestStructAndInterface:
    def test_struct_is_struct(self, all_structs: list[dict]) -> None:
        config = _find_struct(all_structs, "Config")
        assert config["is_struct"] is True
        assert config["is_interface"] is False
        assert config["is_abstract"] is False

    def test_interface_is_interface(self, all_structs: list[dict]) -> None:
        logger = _find_struct(all_structs, "Logger")
        assert logger["is_interface"] is True
        assert logger["is_abstract"] is True
        assert logger["is_struct"] is False

    def test_concrete_struct(self, all_structs: list[dict]) -> None:
        engine = _find_struct(all_structs, "Engine")
        assert engine["is_struct"] is True
        assert engine["is_abstract"] is False


# ---------------------------------------------------------------------------
# Unit tests — struct embedding (Go's inheritance analogue)
# ---------------------------------------------------------------------------


class TestStructEmbedding:
    def test_embedded_struct_as_base_class(self, all_structs: list[dict]) -> None:
        enhanced = _find_struct(all_structs, "EnhancedPlugin")
        base_names = [b["name"] for b in enhanced["base_classes"]]
        assert "AudioPlugin" in base_names

    def test_embedding_access_is_public(self, all_structs: list[dict]) -> None:
        enhanced = _find_struct(all_structs, "EnhancedPlugin")
        for b in enhanced["base_classes"]:
            assert b["access"] == "public"

    def test_non_embedded_struct_no_bases(self, all_structs: list[dict]) -> None:
        config = _find_struct(all_structs, "Config")
        assert config["base_classes"] == []

    def test_embedding_own_fields_preserved(self, all_structs: list[dict]) -> None:
        enhanced = _find_struct(all_structs, "EnhancedPlugin")
        field_names = [f["name"] for f in enhanced["fields"]]
        assert "extraFeature" in field_names


# ---------------------------------------------------------------------------
# Unit tests — methods
# ---------------------------------------------------------------------------


class TestMethodEnrichment:
    def test_method_parameters(self, all_structs: list[dict]) -> None:
        engine = _find_struct(all_structs, "Engine")
        register = next(m for m in engine["methods"] if m["name"] == "RegisterPlugin")
        assert len(register["parameters"]) == 1
        assert register["parameters"][0]["name"] == "p"
        assert "Plugin" in register["parameters"][0]["type"]

    def test_method_return_type(self, all_structs: list[dict]) -> None:
        config = _find_struct(all_structs, "Config")
        validate = next(m for m in config["methods"] if m["name"] == "Validate")
        assert validate["return_type"] == "bool"

    def test_method_access_exported(self, all_structs: list[dict]) -> None:
        engine = _find_struct(all_structs, "Engine")
        start = next(m for m in engine["methods"] if m["name"] == "Start")
        assert start["access"] == "public"

    def test_method_access_unexported(self, all_structs: list[dict]) -> None:
        audio = _find_struct(all_structs, "AudioPlugin")
        for m in audio["methods"]:
            if m["name"][0].islower():
                assert m["access"] == "private"

    def test_interface_methods_pure_virtual(self, all_structs: list[dict]) -> None:
        plugin = _find_struct(all_structs, "Plugin")
        for m in plugin["methods"]:
            assert m["is_pure_virtual"] is True

    def test_struct_methods_not_pure_virtual(self, all_structs: list[dict]) -> None:
        engine = _find_struct(all_structs, "Engine")
        for m in engine["methods"]:
            assert m["is_pure_virtual"] is False

    def test_method_line_numbers(self, all_structs: list[dict]) -> None:
        engine = _find_struct(all_structs, "Engine")
        for method in engine["methods"]:
            assert method["line"] > 0

    def test_interface_method_parameters(self, all_structs: list[dict]) -> None:
        logger = _find_struct(all_structs, "Logger")
        log = next(m for m in logger["methods"] if m["name"] == "Log")
        assert len(log["parameters"]) == 1
        assert log["parameters"][0]["name"] == "message"
        assert log["parameters"][0]["type"] == "string"


# ---------------------------------------------------------------------------
# Unit tests — package namespace
# ---------------------------------------------------------------------------


class TestPackageNamespace:
    def test_package_as_namespace(self, all_structs: list[dict]) -> None:
        engine = _find_struct(all_structs, "Engine")
        assert engine["namespace"] == "engine"

    def test_different_packages(self, all_structs: list[dict]) -> None:
        logger = _find_struct(all_structs, "Logger")
        assert logger["namespace"] == "logging"

    def test_package_in_payload(self, go_evidence: list[Any]) -> None:
        packages = {ev.payload["package"] for ev in go_evidence}
        assert "engine" in packages
        assert "plugin" in packages
        assert "logging" in packages
        assert "util" in packages


# ---------------------------------------------------------------------------
# Unit tests — outer_class (always "" for Go)
# ---------------------------------------------------------------------------


class TestNoNestedTypes:
    def test_all_top_level(self, all_structs: list[dict]) -> None:
        for s in all_structs:
            assert s["outer_class"] == "", f"{s['name']} has outer_class={s['outer_class']!r}"


# ---------------------------------------------------------------------------
# Unit tests — line numbers
# ---------------------------------------------------------------------------


class TestLineNumbers:
    def test_struct_line_numbers_positive(self, all_structs: list[dict]) -> None:
        for s in all_structs:
            assert s["line"] > 0, f"{s['name']} has line {s['line']}"


# ---------------------------------------------------------------------------
# Unit tests — type count
# ---------------------------------------------------------------------------


class TestTypeCount:
    def test_total_types_extracted(self, all_structs: list[dict]) -> None:
        names = {s["name"] for s in all_structs}
        expected = {
            "Config",
            "Engine",
            "Logger",
            "ConsoleLogger",
            "Plugin",
            "AudioPlugin",
            "EnhancedPlugin",
            "MidiPlugin",
            "Preset",
            "Editor",
            "EventBus",
            "OrphanHelper",
        }
        assert names == expected


# ---------------------------------------------------------------------------
# Unit tests — backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_existing_fields_still_present(self, go_evidence: list[Any]) -> None:
        for ev in go_evidence:
            assert "catch_blocks" in ev.payload
            assert "log_statements" in ev.payload
            assert "functions" in ev.payload
            assert "error_assignments" in ev.payload
            assert "goroutine_launches" in ev.payload
            assert "http_calls" in ev.payload
            assert "defer_statements" in ev.payload

    def test_new_fields_present(self, go_evidence: list[Any]) -> None:
        for ev in go_evidence:
            assert "package" in ev.payload
            assert "structs" in ev.payload


# ---------------------------------------------------------------------------
# Integration tests — full pipeline to Mermaid diagram
# ---------------------------------------------------------------------------


class TestIntegrationDiagramPipeline:
    @pytest.fixture(scope="class")
    def diagram_mermaid(self, all_structs: list[dict]) -> str:
        from nfr_review.arch_diagrams import render_class_diagram

        result = render_class_diagram(all_structs, title="Go Test")
        return result.mermaid

    @pytest.fixture(scope="class")
    def grouped_mermaid(self, all_structs: list[dict]) -> str:
        from nfr_review.arch_diagrams import render_class_diagram

        result = render_class_diagram(all_structs, title="Go Grouped", group_by_namespace=True)
        return result.mermaid

    def test_integration_struct_stereotype(self, diagram_mermaid: str) -> None:
        assert "<<struct>> Config" in diagram_mermaid
        assert "<<struct>> Engine" in diagram_mermaid

    def test_integration_interface_stereotype(self, diagram_mermaid: str) -> None:
        assert "<<abstract>> Logger" in diagram_mermaid
        assert "<<abstract>> Plugin" in diagram_mermaid

    def test_integration_composition_field(self, diagram_mermaid: str) -> None:
        assert "Engine" in diagram_mermaid and "Config" in diagram_mermaid

    def test_integration_embedding_inheritance(self, diagram_mermaid: str) -> None:
        assert "AudioPlugin <|-- EnhancedPlugin" in diagram_mermaid

    def test_integration_dependency_parameter(self, diagram_mermaid: str) -> None:
        assert "EventBus ..> Plugin" in diagram_mermaid

    def test_integration_namespace_grouping(self, grouped_mermaid: str) -> None:
        assert "namespace engine" in grouped_mermaid
        assert "namespace plugin" in grouped_mermaid
        assert "namespace logging" in grouped_mermaid
        assert "namespace util" in grouped_mermaid

    def test_integration_field_visibility(self, diagram_mermaid: str) -> None:
        assert "Config : +Name string" in diagram_mermaid
        assert "Config : -maxThreads int" in diagram_mermaid

    def test_integration_interface_methods_pure_virtual(self, diagram_mermaid: str) -> None:
        assert "Plugin : +Activate()*" in diagram_mermaid
        assert "Logger : +Log()*" in diagram_mermaid

    def test_integration_orphan_no_edges(self, diagram_mermaid: str) -> None:
        for line in diagram_mermaid.splitlines():
            if "OrphanHelper" in line:
                assert "<|--" not in line or "OrphanHelper" not in line.split("<|--")[1]
                assert "*--" not in line.split("OrphanHelper")[0] if "*--" in line else True
