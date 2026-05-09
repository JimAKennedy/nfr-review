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
    }
    base.update(overrides)
    return base


def _full_payload(**overrides: Any) -> dict[str, Any]:
    return _base_payload(
        manifests=[
            _manifest(present=list(_ALL_PYPROJECT), missing=[]),
        ],
        has_docs_dir=True,
        doc_tool="mkdocs",
        has_api_docs_hint=True,
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
        assert result.findings[0].rag == "green"
        assert "not applicable" in result.findings[0].summary.lower()

    def test_python_with_docstring_green(self) -> None:
        m = _manifest(present=["name"], missing=[])
        ev = _make_evidence(_base_payload(manifests=[m], has_api_docs_hint=True))
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        assert result.findings[0].rag == "green"

    def test_python_no_docstring_amber(self) -> None:
        m = _manifest(present=["name"], missing=[])
        ev = _make_evidence(_base_payload(manifests=[m]))
        rule = ApiDocsRule()
        result = rule.evaluate(ev, None)
        assert result.findings[0].rag == "amber"

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
        assert result.findings[0].rag == "green"
