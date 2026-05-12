"""Python dependency collector — parses requirements.txt and pyproject.toml,
enriches each dependency with version metadata from deps.dev.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

from nfr_review.deps_dev_client import DepsDevClient
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger(__name__)


class PythonDepsCollector:
    name = "python-deps"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        manifest_files: list[str] = []
        raw_deps: list[tuple[str, Requirement]] = []

        for req_path in sorted(repo_path.rglob("requirements.txt")):
            rel = str(req_path.relative_to(repo_path))
            manifest_files.append(rel)
            raw_deps.extend((rel, req) for req in _parse_requirements_txt(req_path))

        pyproject_path = repo_path / "pyproject.toml"
        if pyproject_path.is_file():
            manifest_files.append("pyproject.toml")
            raw_deps.extend(
                ("pyproject.toml", req) for req in _parse_pyproject_toml(pyproject_path)
            )

        if not raw_deps:
            return []

        client = DepsDevClient()
        client.prefetch_package_versions("pypi", [req.name for _, req in raw_deps])
        enrichment_errors: list[str] = []
        dependencies: list[dict[str, Any]] = []

        for source_file, req in raw_deps:
            dep = _enrich(client, req, source_file)
            if dep["deps_dev_status"] != "ok":
                enrichment_errors.append(f"{req.name}: {dep['deps_dev_status']}")
            dependencies.append(dep)

        payload: dict[str, Any] = {
            "dependencies": dependencies,
            "manifest_files_found": manifest_files,
            "enrichment_errors": enrichment_errors,
        }

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="python-deps",
                payload=payload,
            )
        ]


def _parse_requirements_txt(path: Path) -> list[Requirement]:
    reqs: list[Requirement] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("-r ") or stripped.startswith("-r\t"):
            logger.debug("Skipping -r include in %s: %s", path, stripped)
            continue
        try:
            reqs.append(Requirement(stripped))
        except InvalidRequirement:
            logger.debug("Skipping unparseable line in %s: %s", path, stripped)
    return reqs


def _parse_pyproject_toml(path: Path) -> list[Requirement]:
    reqs: list[Requirement] = []
    try:
        data = tomllib.loads(path.read_text())
    except Exception:  # noqa: BLE001
        logger.debug("Failed to parse %s", path)
        return reqs

    project = data.get("project", {})
    dep_strings: list[str] = list(project.get("dependencies", []))

    for group_deps in project.get("optional-dependencies", {}).values():
        dep_strings.extend(group_deps)

    for entry in dep_strings:
        try:
            reqs.append(Requirement(entry))
        except InvalidRequirement:
            logger.debug("Skipping unparseable dependency in %s: %s", path, entry)
    return reqs


def _enrich(client: DepsDevClient, req: Requirement, source_file: str) -> dict[str, Any]:
    specifier_str = str(req.specifier) if req.specifier else ""
    result: dict[str, Any] = {
        "name": req.name,
        "declared_version": specifier_str,
        "version_constraint": specifier_str,
        "source_file": source_file,
        "latest_version": None,
        "latest_release_date": None,
        "deps_dev_status": "error",
    }

    data = client.get_package_versions("pypi", req.name)
    if data is None:
        return result

    versions = data.get("versions", [])
    if not versions:
        result["deps_dev_status"] = "not_found"
        return result

    latest = versions[-1]
    result["latest_version"] = latest.get("versionKey", {}).get("version")
    result["latest_release_date"] = latest.get("publishedAt")
    result["deps_dev_status"] = "ok"
    return result


def _register() -> None:
    if "python-deps" not in collector_registry:
        collector_registry.register("python-deps", PythonDepsCollector())


_register()


__all__ = ["PythonDepsCollector"]
