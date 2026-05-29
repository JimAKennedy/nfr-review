# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for Java/Python/Go dormant class detection rules (M030-S04).

Mirrors the structure of test_cpp_dormant_classes.py with language-specific
fixtures and the shared _detect_orphans core.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nfr_review.arch_diagrams import render_class_diagram
from nfr_review.collectors.go_ast import GoAstCollector
from nfr_review.collectors.java_ast import JavaAstCollector
from nfr_review.collectors.python_ast import PythonAstCollector
from nfr_review.models import Evidence
from nfr_review.rules.dormant_classes import (
    GoDormantClassesRule,
    JavaDormantClassesRule,
    PythonDormantClassesRule,
)

JAVA_FIXTURES = Path(__file__).parent / "fixtures" / "java-class-diagram"
PYTHON_FIXTURES = Path(__file__).parent / "fixtures" / "python-class-diagram"
GO_FIXTURES = Path(__file__).parent / "fixtures" / "go-class-diagram"


def _make_evidence(
    classes: list[dict],
    *,
    kind: str,
    collector_name: str,
    classes_key: str = "classes",
    file_path: str = "test.java",
) -> list[Evidence]:
    return [
        Evidence(
            collector_name=collector_name,
            collector_version="0.1.0",
            locator=file_path,
            kind=kind,
            payload={"file_path": file_path, classes_key: classes},
        ),
    ]


# ---------------------------------------------------------------------------
# Java dormant rule: unit tests
# ---------------------------------------------------------------------------


class TestJavaDormantUnit:
    @pytest.fixture()
    def rule(self) -> JavaDormantClassesRule:
        return JavaDormantClassesRule()

    def _ev(self, classes: list[dict]) -> list[Evidence]:
        return _make_evidence(classes, kind="java-ast-file", collector_name="java-ast")

    def test_skips_without_evidence(self, rule: JavaDormantClassesRule) -> None:
        result = rule.evaluate([], context=None)
        assert result.skipped is True

    def test_single_class_not_flagged(self, rule: JavaDormantClassesRule) -> None:
        classes = [
            {"name": "Solo", "line": 1, "base_classes": [], "methods": [], "fields": []}
        ]
        result = rule.evaluate(self._ev(classes), context=None)
        assert result.findings == []

    def test_all_connected_green(self, rule: JavaDormantClassesRule) -> None:
        classes = [
            {
                "name": "Base",
                "line": 1,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": True,
            },
            {
                "name": "Derived",
                "line": 10,
                "base_classes": [{"name": "Base", "access": "public"}],
                "methods": [],
                "fields": [],
            },
        ]
        result = rule.evaluate(self._ev(classes), context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "java-no-dormant-classes"

    def test_orphan_flagged(self, rule: JavaDormantClassesRule) -> None:
        classes = [
            {
                "name": "Base",
                "line": 1,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": True,
            },
            {
                "name": "Derived",
                "line": 10,
                "base_classes": [{"name": "Base", "access": "public"}],
                "methods": [],
                "fields": [],
            },
            {"name": "Orphan", "line": 20, "base_classes": [], "methods": [], "fields": []},
        ]
        result = rule.evaluate(self._ev(classes), context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "Orphan" in result.findings[0].summary
        assert result.findings[0].pattern_tag == "java-dormant-class"

    def test_field_type_connects(self, rule: JavaDormantClassesRule) -> None:
        classes = [
            {
                "name": "Container",
                "line": 1,
                "base_classes": [],
                "methods": [],
                "fields": [{"name": "item", "type": "Item", "access": "private", "line": 2}],
            },
            {"name": "Item", "line": 10, "base_classes": [], "methods": [], "fields": []},
        ]
        result = rule.evaluate(self._ev(classes), context=None)
        assert result.findings[0].rag == "green"

    def test_parameter_type_connects(self, rule: JavaDormantClassesRule) -> None:
        classes = [
            {
                "name": "Handler",
                "line": 1,
                "base_classes": [],
                "methods": [
                    {
                        "name": "process",
                        "return_type": "void",
                        "access": "public",
                        "is_virtual": False,
                        "is_pure_virtual": False,
                        "line": 3,
                        "parameters": [{"name": "msg", "type": "Message"}],
                    }
                ],
                "fields": [],
            },
            {"name": "Message", "line": 20, "base_classes": [], "methods": [], "fields": []},
        ]
        result = rule.evaluate(self._ev(classes), context=None)
        assert result.findings[0].rag == "green"

    def test_nested_class_connects(self, rule: JavaDormantClassesRule) -> None:
        classes = [
            {"name": "Outer", "line": 1, "base_classes": [], "methods": [], "fields": []},
            {
                "name": "Inner",
                "line": 5,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "outer_class": "Outer",
            },
        ]
        result = rule.evaluate(self._ev(classes), context=None)
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# Python dormant rule: unit tests
# ---------------------------------------------------------------------------


class TestPythonDormantUnit:
    @pytest.fixture()
    def rule(self) -> PythonDormantClassesRule:
        return PythonDormantClassesRule()

    def _ev(self, classes: list[dict]) -> list[Evidence]:
        return _make_evidence(
            classes, kind="python-ast-file", collector_name="python-ast", file_path="test.py"
        )

    def test_skips_without_evidence(self, rule: PythonDormantClassesRule) -> None:
        result = rule.evaluate([], context=None)
        assert result.skipped is True

    def test_orphan_flagged(self, rule: PythonDormantClassesRule) -> None:
        classes = [
            {"name": "Base", "line": 1, "base_classes": [], "methods": [], "fields": []},
            {
                "name": "Derived",
                "line": 10,
                "base_classes": [{"name": "Base", "access": "public"}],
                "methods": [],
                "fields": [],
            },
            {"name": "Orphan", "line": 20, "base_classes": [], "methods": [], "fields": []},
        ]
        result = rule.evaluate(self._ev(classes), context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "Orphan" in orphan_names
        assert "Base" not in orphan_names

    def test_all_connected_green(self, rule: PythonDormantClassesRule) -> None:
        classes = [
            {"name": "Base", "line": 1, "base_classes": [], "methods": [], "fields": []},
            {
                "name": "Child",
                "line": 10,
                "base_classes": [{"name": "Base", "access": "public"}],
                "methods": [],
                "fields": [],
            },
        ]
        result = rule.evaluate(self._ev(classes), context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "python-no-dormant-classes"


# ---------------------------------------------------------------------------
# Go dormant rule: unit tests
# ---------------------------------------------------------------------------


class TestGoDormantUnit:
    @pytest.fixture()
    def rule(self) -> GoDormantClassesRule:
        return GoDormantClassesRule()

    def _ev(self, structs: list[dict]) -> list[Evidence]:
        return _make_evidence(
            structs,
            kind="go-ast-file",
            collector_name="go-ast",
            classes_key="structs",
            file_path="test.go",
        )

    def test_skips_without_evidence(self, rule: GoDormantClassesRule) -> None:
        result = rule.evaluate([], context=None)
        assert result.skipped is True

    def test_orphan_flagged(self, rule: GoDormantClassesRule) -> None:
        structs = [
            {"name": "Base", "line": 1, "base_classes": [], "methods": [], "fields": []},
            {
                "name": "Derived",
                "line": 10,
                "base_classes": [{"name": "Base", "access": "public"}],
                "methods": [],
                "fields": [],
            },
            {"name": "Orphan", "line": 20, "base_classes": [], "methods": [], "fields": []},
        ]
        result = rule.evaluate(self._ev(structs), context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "Orphan" in orphan_names
        assert "Base" not in orphan_names

    def test_embedding_connects(self, rule: GoDormantClassesRule) -> None:
        structs = [
            {"name": "Logger", "line": 1, "base_classes": [], "methods": [], "fields": []},
            {
                "name": "ConsoleLogger",
                "line": 10,
                "base_classes": [{"name": "Logger", "access": "public"}],
                "methods": [],
                "fields": [],
            },
        ]
        result = rule.evaluate(self._ev(structs), context=None)
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "go-no-dormant-classes"


# ---------------------------------------------------------------------------
# Live fixture: Java integration
# ---------------------------------------------------------------------------


class _Cfg:
    exclude_paths: list[str] = []
    exclude_test_paths = False


class TestJavaLiveFixture:
    @pytest.fixture(scope="class")
    def evidence(self) -> list[Any]:
        return JavaAstCollector().collect(JAVA_FIXTURES, _Cfg())

    @pytest.fixture(scope="class")
    def rule(self) -> JavaDormantClassesRule:
        return JavaDormantClassesRule()

    def test_orphan_detected(self, evidence: list[Any], rule: JavaDormantClassesRule) -> None:
        result = rule.evaluate(evidence, context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "OrphanHelper" in orphan_names

    def test_connected_not_flagged(
        self, evidence: list[Any], rule: JavaDormantClassesRule
    ) -> None:
        result = rule.evaluate(evidence, context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "Engine" not in orphan_names
        assert "AudioPlugin" not in orphan_names

    def test_diagram_renders(self, evidence: list[Any]) -> None:
        classes: list[dict] = []
        for ev in evidence:
            classes.extend(ev.payload.get("classes", []))
        diagram = render_class_diagram(classes)
        assert "classDiagram" in diagram.mermaid


# ---------------------------------------------------------------------------
# Live fixture: Python integration
# ---------------------------------------------------------------------------


class TestPythonLiveFixture:
    @pytest.fixture(scope="class")
    def evidence(self) -> list[Any]:
        return PythonAstCollector().collect(PYTHON_FIXTURES, _Cfg())

    @pytest.fixture(scope="class")
    def rule(self) -> PythonDormantClassesRule:
        return PythonDormantClassesRule()

    def test_orphan_detected(
        self, evidence: list[Any], rule: PythonDormantClassesRule
    ) -> None:
        result = rule.evaluate(evidence, context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "OrphanHelper" in orphan_names

    def test_connected_not_flagged(
        self, evidence: list[Any], rule: PythonDormantClassesRule
    ) -> None:
        result = rule.evaluate(evidence, context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "Engine" not in orphan_names
        assert "AudioPlugin" not in orphan_names

    def test_diagram_renders(self, evidence: list[Any]) -> None:
        classes: list[dict] = []
        for ev in evidence:
            classes.extend(ev.payload.get("classes", []))
        diagram = render_class_diagram(classes)
        assert "classDiagram" in diagram.mermaid


# ---------------------------------------------------------------------------
# Live fixture: Go integration
# ---------------------------------------------------------------------------


class TestGoLiveFixture:
    @pytest.fixture(scope="class")
    def evidence(self) -> list[Any]:
        return GoAstCollector().collect(GO_FIXTURES, _Cfg())

    @pytest.fixture(scope="class")
    def rule(self) -> GoDormantClassesRule:
        return GoDormantClassesRule()

    def test_orphan_detected(self, evidence: list[Any], rule: GoDormantClassesRule) -> None:
        result = rule.evaluate(evidence, context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "OrphanHelper" in orphan_names

    def test_connected_not_flagged(
        self, evidence: list[Any], rule: GoDormantClassesRule
    ) -> None:
        result = rule.evaluate(evidence, context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "Engine" not in orphan_names
        assert "AudioPlugin" not in orphan_names

    def test_diagram_renders(self, evidence: list[Any]) -> None:
        structs: list[dict] = []
        for ev in evidence:
            structs.extend(ev.payload.get("structs", []))
        diagram = render_class_diagram(structs)
        assert "classDiagram" in diagram.mermaid
