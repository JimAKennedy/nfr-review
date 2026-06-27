# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Documentation collector — checks package metadata and docs infrastructure."""

from __future__ import annotations

import ast
import json
import logging
import re
import xml.etree.ElementTree as ET  # nosec B405
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.documentation import DocumentationPayload, ManifestEntry
from nfr_review.hygiene import hygiene_collector_registry
from nfr_review.models import Evidence

logger = logging.getLogger(__name__)

_PYPROJECT_FIELDS = (
    "name",
    "version",
    "description",
    "authors",
    "license",
    "urls",
    "classifiers",
    "requires-python",
)

_PACKAGE_JSON_FIELDS = (
    "name",
    "version",
    "description",
    "author",
    "license",
    "homepage",
    "repository",
    "keywords",
)

_POM_FIELDS = (
    "artifactId",
    "version",
    "description",
    "url",
    "licenses",
    "developers",
    "scm",
)


def _parse_pyproject(repo_path: Path) -> ManifestEntry | None:
    path = repo_path / "pyproject.toml"
    if not path.is_file():
        return None

    try:
        if hasattr(__builtins__, "__import__"):
            import tomllib  # noqa: F811 — stdlib 3.11+
        else:
            import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        try:
            import tomli as tomllib  # type: ignore[no-redef,import-not-found]
        except ModuleNotFoundError:
            logger.debug("Neither tomllib nor tomli available — skipping pyproject.toml")
            return None

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("Failed to parse %s", path)
        return None

    project = data.get("project")
    if not isinstance(project, dict):
        return ManifestEntry(
            path="pyproject.toml",
            type="pyproject.toml",
            fields_present=[],
            fields_missing=list(_PYPROJECT_FIELDS),
        )

    present = [f for f in _PYPROJECT_FIELDS if f in project]
    missing = [f for f in _PYPROJECT_FIELDS if f not in project]
    return ManifestEntry(
        path="pyproject.toml",
        type="pyproject.toml",
        fields_present=present,
        fields_missing=missing,
    )


def _parse_package_json(repo_path: Path) -> ManifestEntry | None:
    path = repo_path / "package.json"
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.debug("Failed to parse %s", path)
        return None

    if not isinstance(data, dict):
        return ManifestEntry(
            path="package.json",
            type="package.json",
            fields_present=[],
            fields_missing=list(_PACKAGE_JSON_FIELDS),
        )

    present = [f for f in _PACKAGE_JSON_FIELDS if f in data]
    missing = [f for f in _PACKAGE_JSON_FIELDS if f not in data]
    return ManifestEntry(
        path="package.json",
        type="package.json",
        fields_present=present,
        fields_missing=missing,
    )


_MAVEN_NS = "http://maven.apache.org/POM/4.0.0"


def _parse_pom_xml(repo_path: Path) -> ManifestEntry | None:
    path = repo_path / "pom.xml"
    if not path.is_file():
        return None

    try:
        tree = ET.parse(path)  # noqa: S314 — local repo path, not user-supplied URL  # nosec B314
    except ET.ParseError:
        logger.debug("Failed to parse %s", path)
        return None

    root = tree.getroot()

    # Determine whether the document uses the Maven namespace or is bare.
    # ET.Element.tag is "{ns}localname" when a namespace is present.
    if root.tag == f"{{{_MAVEN_NS}}}project":
        ns_prefix = f"{{{_MAVEN_NS}}}"
    else:
        ns_prefix = ""

    def _find(tag: str) -> ET.Element | None:
        return root.find(f"{ns_prefix}{tag}")

    present: list[str] = []
    missing: list[str] = []
    for field in _POM_FIELDS:
        elem = _find(field)
        if elem is not None and (elem.text or len(elem)):
            present.append(field)
        else:
            missing.append(field)

    return ManifestEntry(
        path="pom.xml",
        type="pom.xml",
        fields_present=present,
        fields_missing=missing,
    )


_CARGO_FIELDS = (
    "name",
    "version",
    "description",
    "license",
    "authors",
    "repository",
    "homepage",
    "keywords",
)

_GO_MOD_FIELDS = (
    "module",
    "go-version",
)

_CSPROJ_FIELDS = (
    "Version",
    "Description",
    "Authors",
    "PackageLicenseExpression",
    "RepositoryUrl",
    "PackageProjectUrl",
)

_CMAKE_FIELDS = (
    "name",
    "version",
    "description",
    "homepage_url",
)


def _parse_cargo_toml(repo_path: Path) -> ManifestEntry | None:
    path = repo_path / "Cargo.toml"
    if not path.is_file():
        return None

    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        try:
            import tomli as tomllib  # type: ignore[no-redef,import-not-found]
        except ModuleNotFoundError:
            logger.debug("Neither tomllib nor tomli available — skipping Cargo.toml")
            return None

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("Failed to parse %s", path)
        return None

    package = data.get("package")
    if not isinstance(package, dict):
        return ManifestEntry(
            path="Cargo.toml",
            type="Cargo.toml",
            fields_present=[],
            fields_missing=list(_CARGO_FIELDS),
        )

    present = [f for f in _CARGO_FIELDS if f in package]
    missing = [f for f in _CARGO_FIELDS if f not in package]
    return ManifestEntry(
        path="Cargo.toml",
        type="Cargo.toml",
        fields_present=present,
        fields_missing=missing,
    )


def _parse_go_mod(repo_path: Path) -> ManifestEntry | None:
    path = repo_path / "go.mod"
    if not path.is_file():
        return None

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.debug("Failed to read %s", path)
        return None

    present: list[str] = []
    missing: list[str] = []

    if re.search(r"^\s*module\s+\S+", text, re.MULTILINE):
        present.append("module")
    else:
        missing.append("module")

    if re.search(r"^\s*go\s+\d+\.\d+", text, re.MULTILINE):
        present.append("go-version")
    else:
        missing.append("go-version")

    return ManifestEntry(
        path="go.mod",
        type="go.mod",
        fields_present=present,
        fields_missing=missing,
    )


def _parse_csproj(repo_path: Path) -> ManifestEntry | None:
    candidates = sorted(repo_path.glob("*.csproj"))
    if not candidates:
        return None

    path = candidates[0]
    rel_path = path.name

    try:
        tree = ET.parse(path)  # noqa: S314 — local repo path, not user-supplied URL  # nosec B314
    except ET.ParseError:
        logger.debug("Failed to parse %s", path)
        return None

    root = tree.getroot()

    # Collect all text from PropertyGroup children
    props: set[str] = set()
    for pg in root.iter("PropertyGroup"):
        for child in pg:
            tag = child.tag
            if child.text and child.text.strip():
                props.add(tag)

    present = [f for f in _CSPROJ_FIELDS if f in props]
    missing = [f for f in _CSPROJ_FIELDS if f not in props]
    return ManifestEntry(
        path=rel_path,
        type="csproj",
        fields_present=present,
        fields_missing=missing,
    )


_CMAKE_PROJECT_RE = re.compile(
    r"project\s*\("
    r"\s*(\w+)"
    r"(?:\s+VERSION\s+([\d.]+))?"
    r'(?:\s+DESCRIPTION\s+"([^"]*)")?'
    r'(?:\s+HOMEPAGE_URL\s+"([^"]*)")?',
    re.IGNORECASE,
)


def _parse_cmakelists(repo_path: Path) -> ManifestEntry | None:
    path = repo_path / "CMakeLists.txt"
    if not path.is_file():
        return None

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.debug("Failed to read %s", path)
        return None

    m = _CMAKE_PROJECT_RE.search(text)
    if m is None:
        return ManifestEntry(
            path="CMakeLists.txt",
            type="CMakeLists.txt",
            fields_present=[],
            fields_missing=list(_CMAKE_FIELDS),
        )

    present: list[str] = ["name"]
    missing: list[str] = []

    if m.group(2):
        present.append("version")
    else:
        missing.append("version")

    if m.group(3):
        present.append("description")
    else:
        missing.append("description")

    if m.group(4):
        present.append("homepage_url")
    else:
        missing.append("homepage_url")

    return ManifestEntry(
        path="CMakeLists.txt",
        type="CMakeLists.txt",
        fields_present=present,
        fields_missing=missing,
    )


def _detect_py_typed(repo_path: Path) -> bool:
    """Check for PEP 561 py.typed marker file."""
    src_dir = repo_path / "src"
    if src_dir.is_dir():
        for child in src_dir.iterdir():
            if child.is_dir() and (child / "py.typed").is_file():
                return True
    for child in repo_path.iterdir():
        if (
            child.is_dir()
            and child.name not in ("src", "tests", "test", "docs", ".git", ".tox", ".venv")
            and (child / "__init__.py").is_file()
            and (child / "py.typed").is_file()
        ):
            return True
    return False


def _extract_classifiers(repo_path: Path) -> list[str]:
    """Extract trove classifiers from pyproject.toml."""
    path = repo_path / "pyproject.toml"
    if not path.is_file():
        return []

    try:
        if hasattr(__builtins__, "__import__"):
            import tomllib
        else:
            import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        try:
            import tomli as tomllib  # type: ignore[no-redef,import-not-found]
        except ModuleNotFoundError:
            return []

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    project = data.get("project", {})
    if not isinstance(project, dict):
        return []
    classifiers = project.get("classifiers", [])
    return classifiers if isinstance(classifiers, list) else []


def _detect_doc_tool(repo_path: Path) -> str:
    if (repo_path / "mkdocs.yml").is_file():
        return "mkdocs"
    for candidate in ("docs/conf.py", "conf.py"):
        if (repo_path / candidate).is_file():
            return "sphinx"
    if (repo_path / ".readthedocs.yml").is_file():
        return "readthedocs"
    return "none"


def _check_api_docs_hint(repo_path: Path) -> bool:
    src_dir = repo_path / "src"
    if src_dir.is_dir():
        for init in src_dir.rglob("__init__.py"):
            try:
                tree = ast.parse(init.read_text(encoding="utf-8"))
                if ast.get_docstring(tree):
                    return True
            except (OSError, SyntaxError) as e:  # nosec B112
                logger.debug("Failed to parse %s for API docs hint: %s", init, e)
                continue
    top_init = repo_path / "__init__.py"
    if top_init.is_file():
        try:
            tree = ast.parse(top_init.read_text(encoding="utf-8"))
            if ast.get_docstring(tree):
                return True
        except (OSError, SyntaxError) as e:  # nosec B110
            logger.debug("Failed to parse %s for API docs hint: %s", top_init, e)
            pass
    return False


class DocumentationCollector:
    name = "documentation"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        manifests: list[ManifestEntry] = []

        pyproject = _parse_pyproject(repo_path)
        if pyproject is not None:
            manifests.append(pyproject)

        pkg_json = _parse_package_json(repo_path)
        if pkg_json is not None:
            manifests.append(pkg_json)

        pom = _parse_pom_xml(repo_path)
        if pom is not None:
            manifests.append(pom)

        cargo = _parse_cargo_toml(repo_path)
        if cargo is not None:
            manifests.append(cargo)

        go_mod = _parse_go_mod(repo_path)
        if go_mod is not None:
            manifests.append(go_mod)

        csproj = _parse_csproj(repo_path)
        if csproj is not None:
            manifests.append(csproj)

        cmake = _parse_cmakelists(repo_path)
        if cmake is not None:
            manifests.append(cmake)

        has_docs_dir = (repo_path / "docs").is_dir()
        doc_tool = _detect_doc_tool(repo_path)
        has_api_docs_hint = _check_api_docs_hint(repo_path)
        has_py_typed = _detect_py_typed(repo_path)
        classifiers = _extract_classifiers(repo_path)

        payload = DocumentationPayload(
            manifests=manifests,
            has_docs_dir=has_docs_dir,
            doc_tool=doc_tool,
            has_api_docs_hint=has_api_docs_hint,
            has_py_typed=has_py_typed,
            classifier_count=len(classifiers),
            has_classifiers=len(classifiers) > 0,
        )

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="documentation-analysis",
                payload=payload,
            )
        ]


def _register() -> None:
    if "documentation" not in hygiene_collector_registry:
        hygiene_collector_registry.register("documentation", DocumentationCollector())


_register()

__all__ = ["DocumentationCollector"]
