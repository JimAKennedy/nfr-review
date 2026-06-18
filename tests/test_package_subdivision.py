"""Tests for package subdivision rules (Python, Java, Go)."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.rules.go_package_subdivision import GoPackageSubdivisionRule
from nfr_review.rules.java_package_subdivision import JavaPackageSubdivisionRule
from nfr_review.rules.python_package_subdivision import PythonPackageSubdivisionRule

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PY_COLLECTOR = "python-ast"
_PY_VERSION = "0.1.0"
_PY_KIND = "python-ast-file"

_JAVA_COLLECTOR = "java-ast"
_JAVA_VERSION = "0.1.0"
_JAVA_KIND = "java-ast-file"

_GO_COLLECTOR = "go-ast"
_GO_VERSION = "0.1.0"
_GO_KIND = "go-ast-file"


def _make_py_class(name: str, namespace: str = "app.models") -> dict:
    return {
        "name": name,
        "line": 1,
        "is_abstract": False,
        "is_interface": False,
        "base_classes": [],
        "fields": [],
        "methods": [],
        "namespace": namespace,
        "outer_class": "",
    }


def _make_java_class(name: str, namespace: str = "com.example") -> dict:
    return {
        "name": name,
        "line": 1,
        "annotations": [],
        "is_abstract": False,
        "is_interface": False,
        "base_classes": [],
        "fields": [],
        "methods": [],
        "namespace": namespace,
        "outer_class": "",
    }


def _make_go_struct(name: str, namespace: str = "main") -> dict:
    return {
        "name": name,
        "line": 1,
        "is_struct": True,
        "is_abstract": False,
        "is_interface": False,
        "base_classes": [],
        "fields": [],
        "methods": [],
        "namespace": namespace,
        "outer_class": "",
    }


def _py_evidence(module_path: str, classes: list[dict]) -> Evidence:
    return Evidence(
        collector_name=_PY_COLLECTOR,
        collector_version=_PY_VERSION,
        locator="test.py",
        kind=_PY_KIND,
        payload={
            "file_path": "test.py",
            "module_path": module_path,
            "classes": classes,
            "catch_blocks": [],
            "log_statements": [],
            "functions": [],
            "imports": [],
            "async_calls": [],
        },
    )


def _java_evidence(package: str, classes: list[dict]) -> Evidence:
    return Evidence(
        collector_name=_JAVA_COLLECTOR,
        collector_version=_JAVA_VERSION,
        locator="Test.java",
        kind=_JAVA_KIND,
        payload={
            "file_path": "Test.java",
            "package": package,
            "classes": classes,
            "methods": [],
            "catch_blocks": [],
            "imports": [],
            "thread_pool_constructions": [],
            "log_statements": [],
        },
    )


def _go_evidence(package: str, structs: list[dict]) -> Evidence:
    return Evidence(
        collector_name=_GO_COLLECTOR,
        collector_version=_GO_VERSION,
        locator="test.go",
        kind=_GO_KIND,
        payload={
            "file_path": "test.go",
            "package": package,
            "structs": structs,
            "catch_blocks": [],
            "log_statements": [],
            "functions": [],
            "error_assignments": [],
            "goroutine_launches": [],
            "http_calls": [],
            "defer_statements": [],
        },
    )


# ---------------------------------------------------------------------------
# Python package subdivision
# ---------------------------------------------------------------------------


class TestPythonPackageSubdivision:
    rule = PythonPackageSubdivisionRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped
        assert "no python-ast evidence" in result.skip_reason

    def test_skip_wrong_collector(self) -> None:
        ev = _java_evidence("com.example", [_make_java_class("Foo")])
        result = self.rule.evaluate([ev], None)
        assert result.skipped

    def test_green_healthy_structure(self) -> None:
        evidence = [
            _py_evidence("app.models.user", [_make_py_class("User")]),
            _py_evidence("app.models.order", [_make_py_class("Order")]),
            _py_evidence("app.services.auth", [_make_py_class("AuthService")]),
        ]
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "python-pkg-subdivision-ok"

    def test_god_package_detection(self) -> None:
        # Create 16 classes in one package (threshold is 15).
        classes = [_make_py_class(f"Class{i}", "app.monolith") for i in range(16)]
        ev = _py_evidence("app.monolith.module", classes)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        reds = [f for f in result.findings if f.rag == "red"]
        assert len(reds) >= 1
        assert reds[0].pattern_tag == "python-god-package"
        assert "16 classes" in reds[0].summary

    def test_flat_structure_detection(self) -> None:
        # Two packages both at depth 1.
        evidence = [
            _py_evidence("models.user", [_make_py_class("User")]),
            _py_evidence("services.auth", [_make_py_class("AuthService")]),
        ]
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        flat = [f for f in result.findings if f.pattern_tag == "python-flat-structure"]
        assert len(flat) == 1
        assert flat[0].rag == "amber"

    def test_mixed_concerns_detection(self) -> None:
        # Many domain words in a single package.
        classes = [
            _make_py_class("InvoiceProcessor"),
            _make_py_class("PaymentGateway"),
            _make_py_class("ShippingTracker"),
            _make_py_class("InventoryManager"),
            _make_py_class("CustomerNotifier"),
        ]
        ev = _py_evidence("app.everything.mod", classes)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        mixed = [f for f in result.findings if f.pattern_tag == "python-mixed-concerns"]
        assert len(mixed) >= 1
        assert mixed[0].rag == "amber"

    def test_no_classes_returns_green(self) -> None:
        ev = _py_evidence("app.empty", [])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# Java package subdivision
# ---------------------------------------------------------------------------


class TestJavaPackageSubdivision:
    rule = JavaPackageSubdivisionRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped
        assert "no java-ast evidence" in result.skip_reason

    def test_skip_wrong_collector(self) -> None:
        ev = _py_evidence("app.models", [_make_py_class("Foo")])
        result = self.rule.evaluate([ev], None)
        assert result.skipped

    def test_green_healthy_structure(self) -> None:
        evidence = [
            _java_evidence("com.example.user", [_make_java_class("UserEntity")]),
            _java_evidence("com.example.order", [_make_java_class("OrderEntity")]),
        ]
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "java-pkg-subdivision-ok"

    def test_god_package_detection(self) -> None:
        classes = [_make_java_class(f"Class{i}", "com.example.monolith") for i in range(16)]
        ev = _java_evidence("com.example.monolith", classes)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        reds = [f for f in result.findings if f.rag == "red"]
        assert len(reds) >= 1
        assert reds[0].pattern_tag == "java-god-package"
        assert "16 classes" in reds[0].summary

    def test_flat_structure_detection(self) -> None:
        evidence = [
            _java_evidence("models", [_make_java_class("User")]),
            _java_evidence("services", [_make_java_class("AuthService")]),
        ]
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        flat = [f for f in result.findings if f.pattern_tag == "java-flat-structure"]
        assert len(flat) == 1
        assert flat[0].rag == "amber"

    def test_mixed_concerns_detection(self) -> None:
        classes = [
            _make_java_class("InvoiceProcessor"),
            _make_java_class("PaymentGateway"),
            _make_java_class("ShippingTracker"),
            _make_java_class("InventoryManager"),
            _make_java_class("CustomerNotifier"),
        ]
        ev = _java_evidence("com.example.everything", classes)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        mixed = [f for f in result.findings if f.pattern_tag == "java-mixed-concerns"]
        assert len(mixed) >= 1
        assert mixed[0].rag == "amber"

    def test_no_classes_returns_green(self) -> None:
        ev = _java_evidence("com.example.empty", [])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"


# ---------------------------------------------------------------------------
# Go package subdivision
# ---------------------------------------------------------------------------


class TestGoPackageSubdivision:
    rule = GoPackageSubdivisionRule()

    def test_skip_no_evidence(self) -> None:
        result = self.rule.evaluate([], None)
        assert result.skipped
        assert "no go-ast evidence" in result.skip_reason

    def test_skip_wrong_collector(self) -> None:
        ev = _py_evidence("app.models", [_make_py_class("Foo")])
        result = self.rule.evaluate([ev], None)
        assert result.skipped

    def test_green_healthy_structure(self) -> None:
        evidence = [
            _go_evidence("user", [_make_go_struct("User")]),
            _go_evidence("order", [_make_go_struct("Order")]),
        ]
        result = self.rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert result.findings[0].pattern_tag == "go-pkg-subdivision-ok"

    def test_god_package_detection(self) -> None:
        # Go threshold is 20, so create 21 structs.
        structs = [_make_go_struct(f"Struct{i}", "bigpkg") for i in range(21)]
        ev = _go_evidence("bigpkg", structs)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        reds = [f for f in result.findings if f.rag == "red"]
        assert len(reds) >= 1
        assert reds[0].pattern_tag == "go-god-package"
        assert "21 structs" in reds[0].summary

    def test_go_threshold_higher_than_java(self) -> None:
        # 16 structs should NOT trigger god-package in Go (threshold 20).
        structs = [_make_go_struct(f"Struct{i}", "pkg") for i in range(16)]
        ev = _go_evidence("pkg", structs)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        reds = [f for f in result.findings if f.rag == "red"]
        assert len(reds) == 0

    def test_mixed_concerns_detection(self) -> None:
        structs = [
            _make_go_struct("InvoiceProcessor"),
            _make_go_struct("PaymentGateway"),
            _make_go_struct("ShippingTracker"),
            _make_go_struct("InventoryCounter"),
            _make_go_struct("CustomerNotifier"),
        ]
        ev = _go_evidence("everything", structs)
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        mixed = [f for f in result.findings if f.pattern_tag == "go-mixed-concerns"]
        assert len(mixed) >= 1
        assert mixed[0].rag == "amber"

    def test_no_structs_returns_green(self) -> None:
        ev = _go_evidence("empty", [])
        result = self.rule.evaluate([ev], None)
        assert not result.skipped
        assert result.findings[0].rag == "green"
