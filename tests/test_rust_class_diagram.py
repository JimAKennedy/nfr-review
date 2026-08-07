# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for Rust class-diagram support.

Verifies the Rust AST collector produces struct/trait-level structural data
compatible with render_class_diagram, matching the convention set by Go's
class-diagram support (structs modeled the same way, no native classes).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nfr_review.arch_diagrams import render_class_diagram
from nfr_review.arch_orchestrator import _collect_class_data
from nfr_review.collectors.rust_ast import RustAstCollector

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rust-class-diagram"


@pytest.fixture(scope="module")
def rust_evidence() -> list[Any]:
    collector = RustAstCollector()
    return collector.collect(FIXTURE_DIR, config=None)


@pytest.fixture(scope="module")
def all_structs(rust_evidence: list[Any]) -> list[Any]:
    structs = []
    for ev in rust_evidence:
        structs.extend(ev.payload.structs)
    return structs


def _find_struct(structs: list, name: str):
    for s in structs:
        if s.name == name:
            return s
    pytest.fail(f"Struct/trait {name!r} not found in {[s.name for s in structs]}")


class TestStructAndTraitExtraction:
    def test_circle_and_square_are_structs(self, all_structs: list) -> None:
        circle = _find_struct(all_structs, "Circle")
        square = _find_struct(all_structs, "Square")
        assert circle.is_struct is True
        assert circle.is_interface is False
        assert square.is_struct is True

    def test_shape_is_a_trait(self, all_structs: list) -> None:
        shape = _find_struct(all_structs, "Shape")
        assert shape.is_interface is True
        assert shape.is_abstract is True

    def test_circle_and_square_implement_shape(self, all_structs: list) -> None:
        circle = _find_struct(all_structs, "Circle")
        square = _find_struct(all_structs, "Square")
        assert [b.name for b in circle.base_classes] == ["Shape"]
        assert [b.name for b in square.base_classes] == ["Shape"]

    def test_circle_fields(self, all_structs: list) -> None:
        circle = _find_struct(all_structs, "Circle")
        field_names = {f.name for f in circle.fields}
        assert field_names == {"radius"}

    def test_square_fields_include_private(self, all_structs: list) -> None:
        square = _find_struct(all_structs, "Square")
        field_names = {f.name for f in square.fields}
        assert field_names == {"side", "label"}
        by_name = {f.name: f for f in square.fields}
        assert by_name["side"].access == "public"
        assert by_name["label"].access == "private"

    def test_shape_trait_default_method_is_not_pure_virtual(self, all_structs: list) -> None:
        shape = _find_struct(all_structs, "Shape")
        by_name = {m.name: m for m in shape.methods}
        assert by_name["area"].is_pure_virtual is True  # signature only, no body
        assert by_name["perimeter"].is_pure_virtual is False  # has a default body

    def test_impl_methods_attached_to_struct(self, all_structs: list) -> None:
        circle = _find_struct(all_structs, "Circle")
        method_names = {m.name for m in circle.methods}
        assert "area" in method_names  # from `impl Shape for Circle`
        assert "new" in method_names  # from inherent `impl Circle`


class TestOrchestratorIntegration:
    def test_collect_class_data_includes_rust(self) -> None:
        result = _collect_class_data([FIXTURE_DIR], cb=lambda _msg: None)
        assert result is not None
        rust_classes = [c for c in result if c["language"] == "Rust"]
        assert len(rust_classes) == 3
        names = {c["name"] for c in rust_classes}
        assert names == {"Circle", "Square", "Shape"}


class TestMermaidRendering:
    def test_renders_valid_class_diagram(self) -> None:
        result = _collect_class_data([FIXTURE_DIR], cb=lambda _msg: None)
        diagram = render_class_diagram(result, title="Rust Test")
        assert diagram.mermaid.startswith("classDiagram")
        assert "Circle" in diagram.mermaid
        assert "Shape" in diagram.mermaid

    def test_inheritance_edge_rendered(self) -> None:
        result = _collect_class_data([FIXTURE_DIR], cb=lambda _msg: None)
        diagram = render_class_diagram(result, title="Rust Test")
        # Mermaid class-diagram inheritance arrow syntax: Base <|-- Derived
        assert "Shape" in diagram.mermaid and "Circle" in diagram.mermaid
        assert "<|--" in diagram.mermaid
