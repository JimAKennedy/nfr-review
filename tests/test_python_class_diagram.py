# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for Python class diagram support (M030-S02).

Verifies the enriched Python AST collector produces class-level structural
data compatible with render_class_diagram, and that the end-to-end pipeline
generates correct Mermaid class diagrams from Python source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.python_ast import PythonAstCollector

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "python-class-diagram"


@pytest.fixture(scope="module")
def python_evidence() -> list[Any]:
    collector = PythonAstCollector()

    class Cfg:
        exclude_paths: list[str] = []
        exclude_test_paths = False

    return collector.collect(FIXTURE_DIR, Cfg())


@pytest.fixture(scope="module")
def all_classes(python_evidence: list[Any]) -> list[dict[str, Any]]:
    classes: list[dict[str, Any]] = []
    for ev in python_evidence:
        classes.extend(ev.payload.get("classes", []))
    return classes


def _find_class(classes: list[dict], name: str) -> dict:
    for c in classes:
        if c["name"] == name:
            return c
    pytest.fail(f"Class {name!r} not found in {[c['name'] for c in classes]}")


# ---------------------------------------------------------------------------
# Unit tests for enriched Python collector — class fields
# ---------------------------------------------------------------------------


class TestFieldExtraction:
    def test_config_has_three_fields(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        assert len(config["fields"]) == 3

    def test_field_names_and_types(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        field_map = {f["name"]: f["type"] for f in config["fields"]}
        assert field_map["name"] == "str"
        assert field_map["max_threads"] == "int"
        assert field_map["debug_mode"] == "bool"

    def test_field_access_public(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        access_map = {f["name"]: f["access"] for f in config["fields"]}
        assert access_map["name"] == "public"

    def test_field_access_private(self, all_classes: list[dict]) -> None:
        audio = _find_class(all_classes, "AudioPlugin")
        access_map = {f["name"]: f["access"] for f in audio["fields"]}
        assert access_map["_volume"] == "private"

    def test_field_line_numbers(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        for field in config["fields"]:
            assert field["line"] > 0


# ---------------------------------------------------------------------------
# Unit tests — inheritance
# ---------------------------------------------------------------------------


class TestInheritance:
    def test_extends_abc(self, all_classes: list[dict]) -> None:
        plugin = _find_class(all_classes, "Plugin")
        base_names = [b["name"] for b in plugin["base_classes"]]
        assert "ABC" in base_names

    def test_extends_concrete(self, all_classes: list[dict]) -> None:
        audio = _find_class(all_classes, "AudioPlugin")
        base_names = [b["name"] for b in audio["base_classes"]]
        assert "Plugin" in base_names

    def test_implements_protocol(self, all_classes: list[dict]) -> None:
        logger = _find_class(all_classes, "Logger")
        base_names = [b["name"] for b in logger["base_classes"]]
        assert "Protocol" in base_names

    def test_implements_logger(self, all_classes: list[dict]) -> None:
        console = _find_class(all_classes, "ConsoleLogger")
        base_names = [b["name"] for b in console["base_classes"]]
        assert "Logger" in base_names

    def test_no_base_classes(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        assert config["base_classes"] == []


# ---------------------------------------------------------------------------
# Unit tests — abstract and protocol
# ---------------------------------------------------------------------------


class TestAbstractAndProtocol:
    def test_abc_is_abstract(self, all_classes: list[dict]) -> None:
        plugin = _find_class(all_classes, "Plugin")
        assert plugin["is_abstract"] is True
        assert plugin["is_interface"] is False

    def test_protocol_is_interface(self, all_classes: list[dict]) -> None:
        logger = _find_class(all_classes, "Logger")
        assert logger["is_abstract"] is True
        assert logger["is_interface"] is True

    def test_concrete_class(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        assert engine["is_abstract"] is False
        assert engine["is_interface"] is False


# ---------------------------------------------------------------------------
# Unit tests — methods
# ---------------------------------------------------------------------------


class TestMethodEnrichment:
    def test_method_parameters(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        register = next(m for m in engine["methods"] if m["name"] == "register_plugin")
        assert len(register["parameters"]) == 1
        assert register["parameters"][0]["type"] == "Plugin"
        assert register["parameters"][0]["name"] == "plugin"

    def test_method_access_public(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        start = next(m for m in engine["methods"] if m["name"] == "start")
        assert start["access"] == "public"

    def test_method_access_private(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        init = next(m for m in engine["methods"] if m["name"] == "__init__")
        assert init["access"] == "private"

    def test_abstractmethod_is_pure_virtual(self, all_classes: list[dict]) -> None:
        plugin = _find_class(all_classes, "Plugin")
        activate = next(m for m in plugin["methods"] if m["name"] == "activate")
        assert activate["is_pure_virtual"] is True

    def test_concrete_method_not_pure_virtual(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        start = next(m for m in engine["methods"] if m["name"] == "start")
        assert start["is_pure_virtual"] is False

    def test_method_return_type(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        validate = next(m for m in config["methods"] if m["name"] == "validate")
        assert validate["return_type"] == "bool"

    def test_method_line_numbers(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        for method in engine["methods"]:
            assert method["line"] > 0

    def test_protocol_methods_have_parameters(self, all_classes: list[dict]) -> None:
        logger = _find_class(all_classes, "Logger")
        log = next(m for m in logger["methods"] if m["name"] == "log")
        assert len(log["parameters"]) == 1
        assert log["parameters"][0]["name"] == "message"
        assert log["parameters"][0]["type"] == "str"

    def test_self_excluded_from_parameters(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        for method in engine["methods"]:
            param_names = [p["name"] for p in method["parameters"]]
            assert "self" not in param_names

    def test_method_decorators(self, all_classes: list[dict]) -> None:
        plugin = _find_class(all_classes, "Plugin")
        activate = next(m for m in plugin["methods"] if m["name"] == "activate")
        assert "abstractmethod" in activate["decorators"]


# ---------------------------------------------------------------------------
# Unit tests — namespace
# ---------------------------------------------------------------------------


class TestNamespace:
    def test_module_path_as_namespace(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        assert config["namespace"] == "engine.config"

    def test_different_modules(self, all_classes: list[dict]) -> None:
        logger = _find_class(all_classes, "Logger")
        assert logger["namespace"] == "logging_pkg.base"

    def test_module_path_in_payload(self, python_evidence: list[Any]) -> None:
        mod_paths = {ev.payload["module_path"] for ev in python_evidence}
        assert "engine.config" in mod_paths
        assert "plugins.base" in mod_paths


# ---------------------------------------------------------------------------
# Unit tests — inner classes
# ---------------------------------------------------------------------------


class TestInnerClasses:
    def test_preset_is_inner_class(self, all_classes: list[dict]) -> None:
        preset = _find_class(all_classes, "Preset")
        assert preset["outer_class"] == "AudioPlugin"

    def test_top_level_class_no_outer(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        assert engine["outer_class"] == ""


# ---------------------------------------------------------------------------
# Unit tests — line numbers
# ---------------------------------------------------------------------------


class TestLineNumbers:
    def test_class_line_numbers_positive(self, all_classes: list[dict]) -> None:
        for cls in all_classes:
            assert cls["line"] > 0, f"{cls['name']} has line {cls['line']}"


# ---------------------------------------------------------------------------
# Unit tests — backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_existing_fields_still_present(self, python_evidence: list[Any]) -> None:
        for ev in python_evidence:
            assert "catch_blocks" in ev.payload
            assert "log_statements" in ev.payload
            assert "functions" in ev.payload
            assert "imports" in ev.payload
            assert "async_calls" in ev.payload


# ---------------------------------------------------------------------------
# Integration tests — full pipeline to Mermaid diagram
# ---------------------------------------------------------------------------


class TestIntegrationDiagramPipeline:
    @pytest.fixture(scope="class")
    def diagram_mermaid(self, all_classes: list[dict]) -> str:
        from nfr_review.arch_diagrams import render_class_diagram

        result = render_class_diagram(all_classes, title="Python Test")
        return result.mermaid

    @pytest.fixture(scope="class")
    def grouped_mermaid(self, all_classes: list[dict]) -> str:
        from nfr_review.arch_diagrams import render_class_diagram

        result = render_class_diagram(
            all_classes, title="Python Grouped", group_by_namespace=True
        )
        return result.mermaid

    def test_integration_inheritance_abc(self, diagram_mermaid: str) -> None:
        assert "ABC <|-- Plugin" in diagram_mermaid

    def test_integration_inheritance_concrete(self, diagram_mermaid: str) -> None:
        assert "Plugin <|-- AudioPlugin" in diagram_mermaid

    def test_integration_inheritance_protocol_impl(self, diagram_mermaid: str) -> None:
        assert "Logger <|-- ConsoleLogger" in diagram_mermaid

    def test_integration_composition_field(self, diagram_mermaid: str) -> None:
        assert "Engine *-- Config" in diagram_mermaid

    def test_integration_composition_logger_field(self, diagram_mermaid: str) -> None:
        assert "Engine *-- Logger" in diagram_mermaid

    def test_integration_inner_class(self, diagram_mermaid: str) -> None:
        assert 'AudioPlugin *-- Preset : "inner"' in diagram_mermaid

    def test_integration_namespace_grouping(self, grouped_mermaid: str) -> None:
        assert "namespace engine.config" in grouped_mermaid
        assert "namespace plugins.base" in grouped_mermaid
        assert "namespace logging_pkg.base" in grouped_mermaid

    def test_integration_abstract_stereotype(self, diagram_mermaid: str) -> None:
        assert "<<abstract>> Plugin" in diagram_mermaid

    def test_integration_field_visibility(self, diagram_mermaid: str) -> None:
        assert "Config : +name str" in diagram_mermaid
        assert "AudioPlugin : -_volume float" in diagram_mermaid

    def test_integration_orphan_no_edges(self, diagram_mermaid: str) -> None:
        for line in diagram_mermaid.splitlines():
            if "OrphanHelper" in line:
                assert "<|--" not in line or "OrphanHelper" not in line.split("<|--")[1]
                assert "*--" not in line.split("OrphanHelper")[0] if "*--" in line else True
