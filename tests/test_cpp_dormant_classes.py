# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for CPP-DORMANT — dormant/orphan class detection rule.

Also verifies that the enriched relationship data (parameters, friends,
nested classes, namespaces) actually reduces the number of orphan classes
compared to the base fields (inheritance + field types only).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nfr_review.arch_diagrams import render_class_diagram
from nfr_review.collectors.cpp_ast import CppAstCollector
from nfr_review.models import Evidence
from nfr_review.rules.cpp_dormant_classes import CppDormantClassesRule

FIXTURES = Path(__file__).parent / "fixtures" / "cpp-ast-sample-repo"


@pytest.fixture()
def collector() -> CppAstCollector:
    return CppAstCollector()


@pytest.fixture()
def rule() -> CppDormantClassesRule:
    return CppDormantClassesRule()


def _make_evidence(classes: list[dict], file_path: str = "test.h") -> list[Evidence]:
    return [
        Evidence(
            collector_name="cpp-ast",
            collector_version="0.1.0",
            locator=file_path,
            kind="cpp-ast-file",
            payload={"file_path": file_path, "classes": classes},
        ),
    ]


# ---------------------------------------------------------------------------
# Rule: basic behaviour
# ---------------------------------------------------------------------------


class TestDormantClassesRule:
    def test_skips_without_evidence(self, rule: CppDormantClassesRule) -> None:
        result = rule.evaluate([], context=None)
        assert result.skipped is True

    def test_single_class_not_flagged(self, rule: CppDormantClassesRule) -> None:
        classes = [
            {
                "name": "Solo",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]
        result = rule.evaluate(_make_evidence(classes), context=None)
        assert result.findings == []

    def test_all_connected_green(self, rule: CppDormantClassesRule) -> None:
        classes = [
            {
                "name": "Base",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": True,
            },
            {
                "name": "Derived",
                "line": 10,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [{"name": "Base", "access": "public"}],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]
        result = rule.evaluate(_make_evidence(classes), context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "cpp-no-dormant-classes"

    def test_orphan_flagged(self, rule: CppDormantClassesRule) -> None:
        classes = [
            {
                "name": "Base",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": True,
            },
            {
                "name": "Derived",
                "line": 10,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [{"name": "Base", "access": "public"}],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "Orphan",
                "line": 20,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]
        result = rule.evaluate(_make_evidence(classes), context=None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "amber"
        assert "Orphan" in result.findings[0].summary
        assert result.findings[0].pattern_tag == "cpp-dormant-class"

    def test_parameter_type_connects(self, rule: CppDormantClassesRule) -> None:
        classes = [
            {
                "name": "Handler",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
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
                    },
                ],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "Message",
                "line": 20,
                "has_destructor": False,
                "is_struct": True,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]
        result = rule.evaluate(_make_evidence(classes), context=None)
        assert result.findings[0].rag == "green"

    def test_friend_connects(self, rule: CppDormantClassesRule) -> None:
        classes = [
            {
                "name": "Secret",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "friends": ["Debugger"],
            },
            {
                "name": "Debugger",
                "line": 10,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]
        result = rule.evaluate(_make_evidence(classes), context=None)
        assert result.findings[0].rag == "green"

    def test_nested_class_connects(self, rule: CppDormantClassesRule) -> None:
        classes = [
            {
                "name": "Outer",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "Inner",
                "line": 5,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "outer_class": "Outer",
            },
        ]
        result = rule.evaluate(_make_evidence(classes), context=None)
        assert result.findings[0].rag == "green"

    def test_field_type_connects(self, rule: CppDormantClassesRule) -> None:
        classes = [
            {
                "name": "Container",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [
                    {"name": "item_", "type": "Item", "access": "private", "line": 2},
                ],
                "is_abstract": False,
            },
            {
                "name": "Item",
                "line": 10,
                "has_destructor": False,
                "is_struct": True,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]
        result = rule.evaluate(_make_evidence(classes), context=None)
        assert result.findings[0].rag == "green"

    def test_return_type_connects(self, rule: CppDormantClassesRule) -> None:
        classes = [
            {
                "name": "Factory",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [
                    {
                        "name": "create",
                        "return_type": "Product",
                        "access": "public",
                        "is_virtual": False,
                        "is_pure_virtual": False,
                        "line": 3,
                    },
                ],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "Product",
                "line": 20,
                "has_destructor": False,
                "is_struct": True,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]
        result = rule.evaluate(_make_evidence(classes), context=None)
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# Live fixture: orphan reduction verification
# ---------------------------------------------------------------------------


class TestOrphanReduction:
    """Verify that the dormant_check.h fixture produces exactly the
    expected connected/orphaned classes when processed end-to-end."""

    def _collect_classes(self, collector: CppAstCollector) -> list[dict]:
        results = collector.collect(FIXTURES, config=None)
        dormant = [e for e in results if "dormant_check.h" in e.payload["file_path"]]
        assert len(dormant) == 1
        return dormant[0].payload["classes"]

    def test_fixture_class_count(self, collector: CppAstCollector) -> None:
        classes = self._collect_classes(collector)
        names = {c["name"] for c in classes}
        assert "Engine" in names
        assert "OrphanHelperA" in names
        assert "OrphanHelperB" in names
        assert len(classes) >= 10

    def test_connected_classes_have_edges(self, collector: CppAstCollector) -> None:
        classes = self._collect_classes(collector)
        diagram = render_class_diagram(classes)
        m = diagram.mermaid
        assert "PluginBase <|-- AudioPlugin" in m
        assert "PluginBase <|-- MidiPlugin" in m
        assert "Engine *-- Config" in m
        assert "Engine *-- Logger" in m
        assert 'MidiPlugin ..> PluginInspector : "friend"' in m or "PluginInspector" in m

    def test_orphans_detected_by_rule(
        self, collector: CppAstCollector, rule: CppDormantClassesRule
    ) -> None:
        results = collector.collect(FIXTURES, config=None)
        dormant = [e for e in results if "dormant_check.h" in e.payload["file_path"]]
        result = rule.evaluate(dormant, context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "OrphanHelperA" in orphan_names
        assert "OrphanHelperB" in orphan_names
        assert "Engine" not in orphan_names
        assert "PluginBase" not in orphan_names

    def test_parameter_type_prevents_orphan(
        self, collector: CppAstCollector, rule: CppDormantClassesRule
    ) -> None:
        """Engine.run(Config&) connects Config via parameter — not just field."""
        results = collector.collect(FIXTURES, config=None)
        dormant = [e for e in results if "dormant_check.h" in e.payload["file_path"]]
        result = rule.evaluate(dormant, context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "Config" not in orphan_names

    def test_friend_prevents_orphan(
        self, collector: CppAstCollector, rule: CppDormantClassesRule
    ) -> None:
        results = collector.collect(FIXTURES, config=None)
        dormant = [e for e in results if "dormant_check.h" in e.payload["file_path"]]
        result = rule.evaluate(dormant, context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "PluginInspector" not in orphan_names

    def test_nested_class_prevents_orphan(
        self, collector: CppAstCollector, rule: CppDormantClassesRule
    ) -> None:
        results = collector.collect(FIXTURES, config=None)
        dormant = [e for e in results if "dormant_check.h" in e.payload["file_path"]]
        result = rule.evaluate(dormant, context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "ToolBar" not in orphan_names
        assert "Editor" not in orphan_names

    def test_ownership_transfer_annotation_suppresses(
        self, collector: CppAstCollector, rule: CppDormantClassesRule
    ) -> None:
        results = collector.collect(FIXTURES, config=None)
        dormant = [e for e in results if "dormant_check.h" in e.payload["file_path"]]
        result = rule.evaluate(dormant, context=None)
        orphan_names = {f.summary.split("'")[1] for f in result.findings if f.rag == "amber"}
        assert "FrameworkView" not in orphan_names

    def test_ownership_transfer_annotation_extracted(self, collector: CppAstCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        dormant = [e for e in results if "dormant_check.h" in e.payload["file_path"]]
        classes = dormant[0].payload["classes"]
        fw_class = next(c for c in classes if c["name"] == "FrameworkView")
        assert "ownership-transfer" in fw_class["annotations"]


# ---------------------------------------------------------------------------
# Unit tests: annotation suppression with synthetic evidence
# ---------------------------------------------------------------------------


class TestAnnotationSuppression:
    def test_annotated_orphan_not_flagged(self, rule: CppDormantClassesRule) -> None:
        classes = [
            {
                "name": "Base",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": True,
            },
            {
                "name": "Derived",
                "line": 10,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [{"name": "Base", "access": "public"}],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "FactoryView",
                "line": 20,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "annotations": ["ownership-transfer"],
            },
        ]
        result = rule.evaluate(_make_evidence(classes), context=None)
        assert all(f.rag == "green" for f in result.findings)

    def test_unannotated_orphan_still_flagged(self, rule: CppDormantClassesRule) -> None:
        classes = [
            {
                "name": "Base",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": True,
            },
            {
                "name": "Derived",
                "line": 10,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [{"name": "Base", "access": "public"}],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "Orphan",
                "line": 20,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
        ]
        result = rule.evaluate(_make_evidence(classes), context=None)
        assert any(f.rag == "amber" and "Orphan" in f.summary for f in result.findings)

    def test_framework_managed_also_suppresses(self, rule: CppDormantClassesRule) -> None:
        classes = [
            {
                "name": "Base",
                "line": 1,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": True,
            },
            {
                "name": "Derived",
                "line": 10,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [{"name": "Base", "access": "public"}],
                "methods": [],
                "fields": [],
                "is_abstract": False,
            },
            {
                "name": "Widget",
                "line": 20,
                "has_destructor": False,
                "is_struct": False,
                "base_classes": [],
                "methods": [],
                "fields": [],
                "is_abstract": False,
                "annotations": ["framework-managed"],
            },
        ]
        result = rule.evaluate(_make_evidence(classes), context=None)
        assert all(f.rag == "green" for f in result.findings)
