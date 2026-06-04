# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for Java class diagram support (M030-S01).

Verifies the enriched Java AST collector produces class-level structural
data compatible with render_class_diagram, and that the end-to-end pipeline
generates correct Mermaid class diagrams from Java source.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.java_ast import JavaAstCollector

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "java-class-diagram"


@pytest.fixture(scope="module")
def java_evidence() -> list[Any]:
    collector = JavaAstCollector()

    class Cfg:
        exclude_paths: list[str] = []
        exclude_test_paths = False

    return collector.collect(FIXTURE_DIR, Cfg())


@pytest.fixture(scope="module")
def all_classes(java_evidence: list[Any]) -> list[dict[str, Any]]:
    classes: list[dict[str, Any]] = []
    for ev in java_evidence:
        classes.extend(ev.payload.get("classes", []))
    return classes


def _find_class(classes: list[dict], name: str) -> dict:
    for c in classes:
        if c["name"] == name:
            return c
    pytest.fail(f"Class {name!r} not found in {[c['name'] for c in classes]}")


# ---------------------------------------------------------------------------
# T03: Unit tests for enriched Java collector
# ---------------------------------------------------------------------------


class TestFieldExtraction:
    def test_config_has_three_fields(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        assert len(config["fields"]) == 3

    def test_field_names_and_types(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        field_map = {f["name"]: f["type"] for f in config["fields"]}
        assert field_map["name"] == "String"
        assert field_map["maxThreads"] == "int"
        assert field_map["debugMode"] == "boolean"

    def test_field_access_modifiers(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        access_map = {f["name"]: f["access"] for f in config["fields"]}
        assert access_map["name"] == "private"
        assert access_map["debugMode"] == "protected"

    def test_field_line_numbers(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        for field in config["fields"]:
            assert field["line"] > 0


class TestInheritance:
    def test_extends(self, all_classes: list[dict]) -> None:
        audio = _find_class(all_classes, "AudioPlugin")
        base_names = [b["name"] for b in audio["base_classes"]]
        assert "Plugin" in base_names

    def test_implements(self, all_classes: list[dict]) -> None:
        console = _find_class(all_classes, "ConsoleLogger")
        base_names = [b["name"] for b in console["base_classes"]]
        assert "Logger" in base_names

    def test_no_base_classes(self, all_classes: list[dict]) -> None:
        config = _find_class(all_classes, "Config")
        assert config["base_classes"] == []


class TestAbstractAndInterface:
    def test_abstract_class(self, all_classes: list[dict]) -> None:
        plugin = _find_class(all_classes, "Plugin")
        assert plugin["is_abstract"] is True
        assert plugin.get("is_interface") is False

    def test_interface_declaration(self, all_classes: list[dict]) -> None:
        logger = _find_class(all_classes, "Logger")
        assert logger["is_abstract"] is True
        assert logger["is_interface"] is True

    def test_concrete_class(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        assert engine["is_abstract"] is False


class TestMethodEnrichment:
    def test_method_parameters(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        register = next(m for m in engine["methods"] if m["name"] == "registerPlugin")
        assert len(register["parameters"]) == 1
        assert register["parameters"][0]["type"] == "Plugin"
        assert register["parameters"][0]["name"] == "plugin"

    def test_method_access(self, all_classes: list[dict]) -> None:
        plugin = _find_class(all_classes, "Plugin")
        activate = next(m for m in plugin["methods"] if m["name"] == "activate")
        assert activate["access"] == "public"

    def test_abstract_method_is_pure_virtual(self, all_classes: list[dict]) -> None:
        plugin = _find_class(all_classes, "Plugin")
        activate = next(m for m in plugin["methods"] if m["name"] == "activate")
        assert activate["is_pure_virtual"] is True

    def test_concrete_method_not_pure_virtual(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        start = next(m for m in engine["methods"] if m["name"] == "start")
        assert start["is_pure_virtual"] is False

    def test_method_line_numbers(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        for method in engine["methods"]:
            assert method["line"] > 0

    def test_interface_methods_are_public(self, all_classes: list[dict]) -> None:
        logger = _find_class(all_classes, "Logger")
        for method in logger["methods"]:
            assert method["access"] == "public"


class TestPackageNamespace:
    def test_package_as_namespace(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        assert engine["namespace"] == "com.example.engine"

    def test_different_packages(self, all_classes: list[dict]) -> None:
        logger = _find_class(all_classes, "Logger")
        assert logger["namespace"] == "com.example.logging"

    def test_package_in_payload(self, java_evidence: list[Any]) -> None:
        packages = {ev.payload["package"] for ev in java_evidence}
        assert "com.example.engine" in packages
        assert "com.example.plugin" in packages


class TestInnerClasses:
    def test_editor_is_inner_class(self, all_classes: list[dict]) -> None:
        editor = _find_class(all_classes, "Editor")
        assert editor["outer_class"] == "MidiPlugin"

    def test_top_level_class_no_outer(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        assert engine["outer_class"] == ""


class TestLineNumbers:
    def test_class_line_numbers_positive(self, all_classes: list[dict]) -> None:
        for cls in all_classes:
            assert cls["line"] > 0, f"{cls['name']} has line {cls['line']}"


class TestBackwardCompatibility:
    def test_annotations_still_present(self, all_classes: list[dict]) -> None:
        audio = _find_class(all_classes, "AudioPlugin")
        assert "annotations" in audio

    def test_methods_still_have_mapping_paths(self, all_classes: list[dict]) -> None:
        engine = _find_class(all_classes, "Engine")
        for method in engine["methods"]:
            assert "mapping_paths" in method


# ---------------------------------------------------------------------------
# T04: Integration tests — full pipeline to Mermaid diagram
# ---------------------------------------------------------------------------


class TestIntegrationDiagramPipeline:
    @pytest.fixture(scope="class")
    def diagram_mermaid(self, all_classes: list[dict]) -> str:
        from nfr_review.arch_diagrams import render_class_diagram

        result = render_class_diagram(all_classes, title="Java Test")
        return result.mermaid

    @pytest.fixture(scope="class")
    def grouped_mermaid(self, all_classes: list[dict]) -> str:
        from nfr_review.arch_diagrams import render_class_diagram

        result = render_class_diagram(
            all_classes, title="Java Grouped", group_by_namespace=True
        )
        return result.mermaid

    def test_integration_inheritance_extends(self, diagram_mermaid: str) -> None:
        assert "Plugin <|-- AudioPlugin" in diagram_mermaid

    def test_integration_inheritance_implements(self, diagram_mermaid: str) -> None:
        assert "Logger <|-- ConsoleLogger" in diagram_mermaid

    def test_integration_composition_field(self, diagram_mermaid: str) -> None:
        assert "Engine *-- Config" in diagram_mermaid

    def test_integration_composition_interface_field(self, diagram_mermaid: str) -> None:
        assert "Engine *-- Logger" in diagram_mermaid

    def test_integration_dependency_parameter(self, diagram_mermaid: str) -> None:
        assert "EventBus ..> Plugin" in diagram_mermaid

    def test_integration_inner_class(self, diagram_mermaid: str) -> None:
        assert 'MidiPlugin *-- Editor : "inner"' in diagram_mermaid

    def test_integration_namespace_grouping(self, grouped_mermaid: str) -> None:
        assert "namespace com_example_engine" in grouped_mermaid
        assert "namespace com_example_plugin" in grouped_mermaid
        assert "namespace com_example_logging" in grouped_mermaid

    def test_integration_abstract_stereotype(self, diagram_mermaid: str) -> None:
        assert diagram_mermaid.count("<<abstract>>") >= 2

    def test_integration_field_visibility(self, diagram_mermaid: str) -> None:
        assert "-name String" in diagram_mermaid
        assert "#debugMode boolean" in diagram_mermaid

    def test_integration_orphan_no_edges(self, diagram_mermaid: str) -> None:
        for line in diagram_mermaid.splitlines():
            if "OrphanHelper" in line:
                assert "<|--" not in line or "OrphanHelper" not in line.split("<|--")[1]
                assert "*--" not in line.split("OrphanHelper")[0] if "*--" in line else True


# ---------------------------------------------------------------------------
# mmdc syntax validation — catches parse errors substring tests miss
# ---------------------------------------------------------------------------

_MMDC = shutil.which("mmdc")
requires_mmdc = pytest.mark.skipif(_MMDC is None, reason="mmdc not installed")


def _assert_mmdc_parses(mermaid: str, label: str = "") -> None:
    assert _MMDC is not None
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "input.mmd"
        out = Path(td) / "output.png"
        cfg = Path(td) / "config.json"
        inp.write_text(mermaid)
        cfg.write_text(json.dumps({"maxTextSize": 200_000}))
        result = subprocess.run(
            [_MMDC, "-i", str(inp), "-o", str(out), "-b", "transparent", "-c", str(cfg)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")[:500]
            pytest.fail(f"mmdc parse failure{f' ({label})' if label else ''}: {err}")


@requires_mmdc
class TestMmcdSyntaxValidation:
    """Pipe real collector → diagram output through mmdc to catch syntax errors."""

    def test_mmdc_validates_ungrouped(self, all_classes: list[dict]) -> None:
        from nfr_review.arch_diagrams import render_class_diagram

        d = render_class_diagram(all_classes, title="Java Ungrouped")
        _assert_mmdc_parses(d.mermaid, "java ungrouped")

    def test_mmdc_validates_grouped(self, all_classes: list[dict]) -> None:
        from nfr_review.arch_diagrams import render_class_diagram

        d = render_class_diagram(all_classes, title="Java Grouped", group_by_namespace=True)
        _assert_mmdc_parses(d.mermaid, "java grouped")
