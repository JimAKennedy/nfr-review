"""Tests for documentation collector and HYG-DOC rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nfr_review.hygiene import (
    hygiene_collector_registry,
    hygiene_rule_registry,
)
from nfr_review.hygiene.collectors.documentation import (
    DocumentationCollector,
)
from nfr_review.hygiene.rules.doc_api_docs import ApiDocsRule
from nfr_review.hygiene.rules.doc_docs_exist import DocsExistRule
from nfr_review.hygiene.rules.doc_pkg_metadata import PkgMetadataRule
from nfr_review.models import Evidence

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_PYPROJECT = [
    "name",
    "version",
    "description",
    "authors",
    "license",
    "urls",
    "classifiers",
    "requires-python",
]


def _make_evidence(payload: dict[str, Any]) -> list[Evidence]:
    return [
        Evidence(
            collector_name="documentation",
            collector_version="0.1.0",
            locator=".",
            kind="documentation-analysis",
            payload=payload,
        )
    ]


def _manifest(
    path: str = "pyproject.toml",
    mtype: str = "pyproject.toml",
    present: list[str] | None = None,
    missing: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "path": path,
        "type": mtype,
        "fields_present": present or [],
        "fields_missing": missing or [],
    }


def _base_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "manifests": [],
        "has_docs_dir": False,
        "doc_tool": "none",
        "has_api_docs_hint": False,
        "has_py_typed": False,
        "classifier_count": 0,
        "has_classifiers": False,
    }
    base.update(overrides)
    return base


def _find_by_tag(result: Any, tag: str) -> Any:
    return next(f for f in result.findings if f.pattern_tag == tag)


def _full_payload(**overrides: Any) -> dict[str, Any]:
    return _base_payload(
        manifests=[
            _manifest(present=list(_ALL_PYPROJECT), missing=[]),
        ],
        has_docs_dir=True,
        doc_tool="mkdocs",
        has_api_docs_hint=True,
        has_py_typed=True,
        classifier_count=3,
        has_classifiers=True,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_collector_registered(self) -> None:
        assert "documentation" in hygiene_collector_registry

    def test_all_rules_registered(self) -> None:
        for rule_id in [
            "HYG-DOC-001",
            "HYG-DOC-002",
            "HYG-DOC-003",
        ]:
            assert rule_id in hygiene_rule_registry, f"{rule_id} not registered"

    def test_rule_categories(self) -> None:
        for rule_id in [
            "HYG-DOC-001",
            "HYG-DOC-002",
            "HYG-DOC-003",
        ]:
            rule = hygiene_rule_registry.get(rule_id)
            assert rule.category == "documentation", f"{rule_id} category mismatch"


# ---------------------------------------------------------------------------
# Collector tests
# ---------------------------------------------------------------------------


class TestDocumentationCollector:
    def test_pyproject_complete(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "foo"\nversion = "1.0"\n'
            'description = "A thing"\nrequires-python = ">=3.11"\n'
            'license = "MIT"\n\n'
            "[project.urls]\n"
            'homepage = "https://example.com"\n'
        )
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert len(results) == 1
        payload = results[0].payload
        assert len(payload["manifests"]) == 1
        m = payload["manifests"][0]
        assert m["type"] == "pyproject.toml"
        assert "name" in m["fields_present"]
        assert "version" in m["fields_present"]

    def test_pyproject_incomplete(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"\n')
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        m = results[0].payload["manifests"][0]
        assert "description" in m["fields_missing"]

    def test_pyproject_no_project_section(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        m = results[0].payload["manifests"][0]
        assert len(m["fields_present"]) == 0
        assert len(m["fields_missing"]) > 0

    def test_malformed_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("{{{{not valid toml")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["manifests"] == []

    def test_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            '{"name": "foo", "version": "1.0.0", '
            '"description": "bar", "license": "MIT", '
            '"homepage": "https://example.com"}'
        )
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        m = results[0].payload["manifests"][0]
        assert m["type"] == "package.json"
        assert "name" in m["fields_present"]
        assert "homepage" in m["fields_present"]

    def test_malformed_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("not json at all")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["manifests"] == []

    def test_both_manifests(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"\n')
        (tmp_path / "package.json").write_text('{"name": "bar"}')
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert len(results[0].payload["manifests"]) == 2

    def test_no_manifests(self, tmp_path: Path) -> None:
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["manifests"] == []

    def test_docs_dir_detection(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["has_docs_dir"] is True

    def test_no_docs_dir(self, tmp_path: Path) -> None:
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["has_docs_dir"] is False

    def test_mkdocs_detection(self, tmp_path: Path) -> None:
        (tmp_path / "mkdocs.yml").write_text("site_name: test\n")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["doc_tool"] == "mkdocs"

    def test_sphinx_detection(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "conf.py").write_text("project = 'test'\n")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["doc_tool"] == "sphinx"

    def test_readthedocs_detection(self, tmp_path: Path) -> None:
        (tmp_path / ".readthedocs.yml").write_text("version: 2\n")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["doc_tool"] == "readthedocs"

    def test_no_doc_tool(self, tmp_path: Path) -> None:
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["doc_tool"] == "none"

    def test_api_docs_hint_with_docstring(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text('"""My package."""\n')
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["has_api_docs_hint"] is True

    def test_api_docs_hint_without_docstring(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "mypkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("x = 1\n")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["has_api_docs_hint"] is False

    def test_evidence_shape(self, tmp_path: Path) -> None:
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert len(results) == 1
        ev = results[0]
        assert ev.kind == "documentation-analysis"
        assert ev.collector_name == "documentation"

    # ------------------------------------------------------------------
    # py.typed detection tests
    # ------------------------------------------------------------------

    def test_py_typed_src_layout(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "mypkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "py.typed").write_text("")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["has_py_typed"] is True

    def test_py_typed_flat_layout(self, tmp_path: Path) -> None:
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "py.typed").write_text("")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["has_py_typed"] is True

    def test_py_typed_absent(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "mypkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["has_py_typed"] is False

    def test_py_typed_not_in_tests_dir(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "py.typed").write_text("")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        assert results[0].payload["has_py_typed"] is False

    # ------------------------------------------------------------------
    # Classifier extraction tests
    # ------------------------------------------------------------------

    def test_classifiers_present(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "foo"\nclassifiers = [\n'
            '  "Development Status :: 3 - Alpha",\n'
            '  "Programming Language :: Python :: 3",\n'
            '  "License :: OSI Approved :: MIT License",\n'
            "]\n"
        )
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        payload = results[0].payload
        assert payload["has_classifiers"] is True
        assert payload["classifier_count"] == 3

    def test_classifiers_absent(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"\n')
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        payload = results[0].payload
        assert payload["has_classifiers"] is False
        assert payload["classifier_count"] == 0

    def test_classifiers_empty_list(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"\nclassifiers = []\n')
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        payload = results[0].payload
        assert payload["has_classifiers"] is False
        assert payload["classifier_count"] == 0

    def test_classifiers_no_pyproject(self, tmp_path: Path) -> None:
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        payload = results[0].payload
        assert payload["has_classifiers"] is False
        assert payload["classifier_count"] == 0

    def test_classifiers_no_project_section(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        payload = results[0].payload
        assert payload["has_classifiers"] is False
        assert payload["classifier_count"] == 0

    # ------------------------------------------------------------------
    # pom.xml tests
    # ------------------------------------------------------------------

    def test_pom_xml_namespaced_complete(self, tmp_path: Path) -> None:
        """Namespaced pom.xml with all tracked fields present."""
        (tmp_path / "pom.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
            "  <modelVersion>4.0.0</modelVersion>\n"
            "  <artifactId>my-app</artifactId>\n"
            "  <version>1.0.0</version>\n"
            "  <description>A sample Maven project</description>\n"
            "  <url>https://example.com</url>\n"
            "  <licenses><license><name>Apache-2.0</name></license></licenses>\n"
            "  <developers><developer><name>Alice</name></developer></developers>\n"
            "  <scm><url>https://github.com/example/my-app</url></scm>\n"
            "</project>\n"
        )
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        assert len(manifests) == 1
        m = manifests[0]
        assert m["type"] == "pom.xml"
        assert m["path"] == "pom.xml"
        assert "artifactId" in m["fields_present"]
        assert "version" in m["fields_present"]
        assert "description" in m["fields_present"]
        assert "url" in m["fields_present"]
        assert "licenses" in m["fields_present"]
        assert "developers" in m["fields_present"]
        assert "scm" in m["fields_present"]
        assert m["fields_missing"] == []

    def test_pom_xml_bare_no_namespace(self, tmp_path: Path) -> None:
        """pom.xml without xmlns attribute (bare tags)."""
        (tmp_path / "pom.xml").write_text(
            '<?xml version="1.0"?>\n'
            "<project>\n"
            "  <artifactId>bare-app</artifactId>\n"
            "  <version>2.0</version>\n"
            "  <description>Bare pom</description>\n"
            "</project>\n"
        )
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        m = results[0].payload["manifests"][0]
        assert m["type"] == "pom.xml"
        assert "artifactId" in m["fields_present"]
        assert "version" in m["fields_present"]
        assert "description" in m["fields_present"]
        # url, licenses, developers, scm absent
        assert "url" in m["fields_missing"]
        assert "licenses" in m["fields_missing"]

    def test_pom_xml_partial_fields(self, tmp_path: Path) -> None:
        """pom.xml with only a subset of fields — missing ones reported."""
        (tmp_path / "pom.xml").write_text(
            '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
            "  <artifactId>partial</artifactId>\n"
            "  <version>0.1</version>\n"
            "</project>\n"
        )
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        m = results[0].payload["manifests"][0]
        assert "artifactId" in m["fields_present"]
        assert "version" in m["fields_present"]
        assert "description" in m["fields_missing"]
        assert "licenses" in m["fields_missing"]
        assert "developers" in m["fields_missing"]
        assert "scm" in m["fields_missing"]

    def test_pom_xml_not_present(self, tmp_path: Path) -> None:
        """No pom.xml — parser returns None, not included in manifests."""
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        types = [m["type"] for m in results[0].payload["manifests"]]
        assert "pom.xml" not in types

    def test_pom_xml_malformed(self, tmp_path: Path) -> None:
        """Malformed pom.xml — skipped gracefully, no manifest entry."""
        (tmp_path / "pom.xml").write_text("<project><unclosed>")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        types = [m["type"] for m in results[0].payload["manifests"]]
        assert "pom.xml" not in types

    def test_pom_xml_alongside_pyproject(self, tmp_path: Path) -> None:
        """Both pom.xml and pyproject.toml produce two manifest entries."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"\n')
        (tmp_path / "pom.xml").write_text(
            '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
            "  <artifactId>foo</artifactId>\n"
            "</project>\n"
        )
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        types = [m["type"] for m in results[0].payload["manifests"]]
        assert "pyproject.toml" in types
        assert "pom.xml" in types
        assert len(types) == 2


# ---------------------------------------------------------------------------
# HYG-DOC-001: Package metadata completeness
# ---------------------------------------------------------------------------


class TestPkgMetadataRule:
    def test_no_manifest_red(self) -> None:
        ev = _make_evidence(_base_payload())
        rule = PkgMetadataRule()
        result = rule.evaluate(ev, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"

    def test_complete_manifest_green(self) -> None:
        ev = _make_evidence(_full_payload())
        rule = PkgMetadataRule()
        result = rule.evaluate(ev, None)
        assert all(f.rag == "green" for f in result.findings)

    def test_missing_many_key_fields_amber(self) -> None:
        m = _manifest(
            present=["name", "version"],
            missing=[
                "description",
                "license",
                "urls",
                "classifiers",
                "authors",
                "requires-python",
            ],
        )
        ev = _make_evidence(_base_payload(manifests=[m]))
        rule = PkgMetadataRule()
        result = rule.evaluate(ev, None)
        assert any(f.rag == "amber" for f in result.findings)

    def test_missing_one_key_field_green(self) -> None:
        m = _manifest(
            present=[
                "name",
                "version",
                "description",
                "license",
                "urls",
            ],
            missing=["homepage"],
        )
        ev = _make_evidence(_base_payload(manifests=[m]))
        rule = PkgMetadataRule()
        result = rule.evaluate(ev, None)
        assert all(f.rag == "green" for f in result.findings)

    def test_no_evidence_skipped(self) -> None:
        rule = PkgMetadataRule()
        result = rule.evaluate([], None)
        assert result.skipped

    def test_pyproject_no_project_section_amber(self) -> None:
        m = _manifest(
            present=[],
            missing=list(_ALL_PYPROJECT),
        )
        ev = _make_evidence(_base_payload(manifests=[m]))
        rule = PkgMetadataRule()
        result = rule.evaluate(ev, None)
        assert any(f.rag == "amber" for f in result.findings)


# ---------------------------------------------------------------------------
# HYG-DOC-002: Documentation infrastructure
# ---------------------------------------------------------------------------


class TestDocsExistRule:
    def test_no_docs_amber(self) -> None:
        ev = _make_evidence(_base_payload())
        rule = DocsExistRule()
        result = rule.evaluate(ev, None)
        assert result.findings[0].rag == "amber"

    def test_docs_dir_green(self) -> None:
        ev = _make_evidence(_base_payload(has_docs_dir=True))
        rule = DocsExistRule()
        result = rule.evaluate(ev, None)
        assert result.findings[0].rag == "green"

    def test_doc_tool_green(self) -> None:
        ev = _make_evidence(_base_payload(doc_tool="mkdocs"))
        rule = DocsExistRule()
        result = rule.evaluate(ev, None)
        assert result.findings[0].rag == "green"

    def test_both_green(self) -> None:
        ev = _make_evidence(_base_payload(has_docs_dir=True, doc_tool="sphinx"))
        rule = DocsExistRule()
        result = rule.evaluate(ev, None)
        f = result.findings[0]
        assert f.rag == "green"
        assert "docs/ directory" in f.summary
        assert "sphinx" in f.summary

    def test_no_evidence_skipped(self) -> None:
        rule = DocsExistRule()
        result = rule.evaluate([], None)
        assert result.skipped


# ---------------------------------------------------------------------------
# HYG-DOC-003: API docs hint
# ---------------------------------------------------------------------------


class TestApiDocsRule:
    def test_no_python_green(self) -> None:
        ev = _make_evidence(_base_payload())
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"
        assert "not applicable" in result.findings[0].summary.lower()

    def test_python_with_docstring_green(self) -> None:
        m = _manifest(present=["name"], missing=[])
        ev = _make_evidence(_base_payload(manifests=[m], has_api_docs_hint=True))
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        docstring_f = _find_by_tag(result, "api-docs-hint")
        assert docstring_f.rag == "green"

    def test_python_no_docstring_amber(self) -> None:
        m = _manifest(present=["name"], missing=[])
        ev = _make_evidence(_base_payload(manifests=[m]))
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        docstring_f = _find_by_tag(result, "api-docs-hint")
        assert docstring_f.rag == "amber"

    def test_no_evidence_skipped(self) -> None:
        rule = ApiDocsRule()
        result = rule.evaluate([], None)
        assert result.skipped

    def test_package_json_not_python(self) -> None:
        m = _manifest(
            path="package.json",
            mtype="package.json",
            present=["name"],
            missing=[],
        )
        ev = _make_evidence(_base_payload(manifests=[m]))
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_python_produces_three_findings(self) -> None:
        m = _manifest(present=["name"], missing=[])
        ev = _make_evidence(_base_payload(manifests=[m]))
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        assert len(result.findings) == 3
        tags = {f.pattern_tag for f in result.findings}
        assert tags == {"api-docs-hint", "py-typed", "classifiers"}

    # ------------------------------------------------------------------
    # py.typed sub-check
    # ------------------------------------------------------------------

    def test_py_typed_present_green(self) -> None:
        m = _manifest(present=["name"], missing=[])
        ev = _make_evidence(_base_payload(manifests=[m], has_py_typed=True))
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        f = _find_by_tag(result, "py-typed")
        assert f.rag == "green"
        assert f.severity == "info"
        assert "PEP 561" in f.summary

    def test_py_typed_absent_amber(self) -> None:
        m = _manifest(present=["name"], missing=[])
        ev = _make_evidence(_base_payload(manifests=[m], has_py_typed=False))
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        f = _find_by_tag(result, "py-typed")
        assert f.rag == "amber"
        assert f.severity == "low"
        assert "py.typed" in f.recommendation

    # ------------------------------------------------------------------
    # Classifier sub-check
    # ------------------------------------------------------------------

    def test_classifiers_present_green(self) -> None:
        m = _manifest(present=["name"], missing=[])
        ev = _make_evidence(
            _base_payload(manifests=[m], has_classifiers=True, classifier_count=3)
        )
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        f = _find_by_tag(result, "classifiers")
        assert f.rag == "green"
        assert f.severity == "info"
        assert "3" in f.summary

    def test_classifiers_absent_info(self) -> None:
        m = _manifest(present=["name"], missing=[])
        ev = _make_evidence(_base_payload(manifests=[m]))
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        f = _find_by_tag(result, "classifiers")
        assert f.rag == "green"
        assert f.severity == "info"
        assert "Development Status" in f.recommendation

    # ------------------------------------------------------------------
    # Full pass: everything present
    # ------------------------------------------------------------------

    def test_all_checks_green(self) -> None:
        m = _manifest(present=["name"], missing=[])
        ev = _make_evidence(
            _base_payload(
                manifests=[m],
                has_api_docs_hint=True,
                has_py_typed=True,
                has_classifiers=True,
                classifier_count=5,
            )
        )
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        assert len(result.findings) == 3
        assert all(f.rag == "green" for f in result.findings)


# ---------------------------------------------------------------------------
# Cargo.toml parser tests
# ---------------------------------------------------------------------------


class TestCargoTomlParser:
    def test_cargo_complete(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "mylib"\nversion = "0.1.0"\n'
            'description = "A Rust lib"\nlicense = "MIT"\n'
            'authors = ["Alice <alice@example.com>"]\n'
            'repository = "https://github.com/alice/mylib"\n'
            'homepage = "https://mylib.rs"\n'
            'keywords = ["rust", "lib"]\n'
        )
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        cargo_manifests = [m for m in manifests if m["type"] == "Cargo.toml"]
        assert len(cargo_manifests) == 1
        m = cargo_manifests[0]
        assert m["path"] == "Cargo.toml"
        assert "name" in m["fields_present"]
        assert "version" in m["fields_present"]
        assert "description" in m["fields_present"]
        assert "license" in m["fields_present"]
        assert m["fields_missing"] == []

    def test_cargo_missing_fields(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "mylib"\nversion = "0.1.0"\n')
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        m = next(x for x in manifests if x["type"] == "Cargo.toml")
        assert "description" in m["fields_missing"]
        assert "license" in m["fields_missing"]
        assert "authors" in m["fields_missing"]

    def test_cargo_no_package_section(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[workspace]\nmembers = []\n")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        m = next(x for x in manifests if x["type"] == "Cargo.toml")
        assert m["fields_present"] == []
        assert len(m["fields_missing"]) > 0

    def test_cargo_malformed(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("{{{{ not valid toml")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        cargo_manifests = [m for m in manifests if m["type"] == "Cargo.toml"]
        assert cargo_manifests == []

    def test_cargo_absent(self, tmp_path: Path) -> None:
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        cargo_manifests = [m for m in manifests if m["type"] == "Cargo.toml"]
        assert cargo_manifests == []


# ---------------------------------------------------------------------------
# go.mod parser tests
# ---------------------------------------------------------------------------


class TestGoModParser:
    def test_go_mod_complete(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module github.com/alice/myapp\n\ngo 1.21\n")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        m = next(x for x in manifests if x["type"] == "go.mod")
        assert m["path"] == "go.mod"
        assert "module" in m["fields_present"]
        assert "go-version" in m["fields_present"]
        assert m["fields_missing"] == []

    def test_go_mod_missing_go_version(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module github.com/alice/myapp\n")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        m = next(x for x in manifests if x["type"] == "go.mod")
        assert "module" in m["fields_present"]
        assert "go-version" in m["fields_missing"]

    def test_go_mod_absent(self, tmp_path: Path) -> None:
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        go_manifests = [m for m in manifests if m["type"] == "go.mod"]
        assert go_manifests == []


# ---------------------------------------------------------------------------
# .csproj parser tests
# ---------------------------------------------------------------------------


class TestCsprojParser:
    def test_csproj_complete(self, tmp_path: Path) -> None:
        (tmp_path / "MyApp.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup>\n"
            "    <Version>1.2.3</Version>\n"
            "    <Description>My awesome app</Description>\n"
            "    <Authors>Alice</Authors>\n"
            "    <PackageLicenseExpression>MIT</PackageLicenseExpression>\n"
            "    <RepositoryUrl>https://github.com/alice/myapp</RepositoryUrl>\n"
            "    <PackageProjectUrl>https://myapp.example.com</PackageProjectUrl>\n"
            "  </PropertyGroup>\n"
            "</Project>\n"
        )
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        m = next(x for x in manifests if x["type"] == "csproj")
        assert m["path"] == "MyApp.csproj"
        assert "Version" in m["fields_present"]
        assert "Description" in m["fields_present"]
        assert "Authors" in m["fields_present"]
        assert "PackageLicenseExpression" in m["fields_present"]
        assert m["fields_missing"] == []

    def test_csproj_missing_fields(self, tmp_path: Path) -> None:
        (tmp_path / "MyApp.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup>\n"
            "    <TargetFramework>net8.0</TargetFramework>\n"
            "  </PropertyGroup>\n"
            "</Project>\n"
        )
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        m = next(x for x in manifests if x["type"] == "csproj")
        assert "Version" in m["fields_missing"]
        assert "Description" in m["fields_missing"]

    def test_csproj_malformed_xml(self, tmp_path: Path) -> None:
        (tmp_path / "MyApp.csproj").write_text("<Project><Unclosed>\n")
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        csproj_manifests = [m for m in manifests if m["type"] == "csproj"]
        assert csproj_manifests == []

    def test_csproj_absent(self, tmp_path: Path) -> None:
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        csproj_manifests = [m for m in manifests if m["type"] == "csproj"]
        assert csproj_manifests == []

    def test_csproj_picks_first_alphabetically(self, tmp_path: Path) -> None:
        # Two .csproj files; parser picks the first sorted by name
        for name in ("ZApp.csproj", "AApp.csproj"):
            (tmp_path / name).write_text(
                f"<Project><PropertyGroup><Description>{name}</Description></PropertyGroup></Project>\n"
            )
        collector = DocumentationCollector()
        results = collector.collect(tmp_path, None)
        manifests = results[0].payload["manifests"]
        m = next(x for x in manifests if x["type"] == "csproj")
        assert m["path"] == "AApp.csproj"
