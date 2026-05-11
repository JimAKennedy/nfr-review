"""Documentation collector — checks package metadata and docs infrastructure."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Any

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


def _parse_pyproject(repo_path: Path) -> dict[str, Any] | None:
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
    except Exception:
        logger.debug("Failed to parse %s", path)
        return None

    project = data.get("project")
    if not isinstance(project, dict):
        return {
            "path": "pyproject.toml",
            "type": "pyproject.toml",
            "fields_present": [],
            "fields_missing": list(_PYPROJECT_FIELDS),
        }

    present = [f for f in _PYPROJECT_FIELDS if f in project]
    missing = [f for f in _PYPROJECT_FIELDS if f not in project]
    return {
        "path": "pyproject.toml",
        "type": "pyproject.toml",
        "fields_present": present,
        "fields_missing": missing,
    }


def _parse_package_json(repo_path: Path) -> dict[str, Any] | None:
    path = repo_path / "package.json"
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Failed to parse %s", path)
        return None

    if not isinstance(data, dict):
        return {
            "path": "package.json",
            "type": "package.json",
            "fields_present": [],
            "fields_missing": list(_PACKAGE_JSON_FIELDS),
        }

    present = [f for f in _PACKAGE_JSON_FIELDS if f in data]
    missing = [f for f in _PACKAGE_JSON_FIELDS if f not in data]
    return {
        "path": "package.json",
        "type": "package.json",
        "fields_present": present,
        "fields_missing": missing,
    }


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
            except Exception:  # nosec B112
                continue
    top_init = repo_path / "__init__.py"
    if top_init.is_file():
        try:
            tree = ast.parse(top_init.read_text(encoding="utf-8"))
            if ast.get_docstring(tree):
                return True
        except Exception:  # nosec B110
            pass
    return False


class DocumentationCollector:
    name = "documentation"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        manifests: list[dict[str, Any]] = []

        pyproject = _parse_pyproject(repo_path)
        if pyproject is not None:
            manifests.append(pyproject)

        pkg_json = _parse_package_json(repo_path)
        if pkg_json is not None:
            manifests.append(pkg_json)

        has_docs_dir = (repo_path / "docs").is_dir()
        doc_tool = _detect_doc_tool(repo_path)
        has_api_docs_hint = _check_api_docs_hint(repo_path)

        payload: dict[str, Any] = {
            "manifests": manifests,
            "has_docs_dir": has_docs_dir,
            "doc_tool": doc_tool,
            "has_api_docs_hint": has_api_docs_hint,
        }

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
