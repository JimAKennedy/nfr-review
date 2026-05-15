"""Node.js dependency collector — parses package.json files,
enriches each dependency with version metadata from deps.dev.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from nfr_review.deps_dev_client import DepsDevClient, pick_latest_version
from nfr_review.models import Evidence
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path
from nfr_review.registry import collector_registry

logger = logging.getLogger(__name__)

_DEP_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


class NodejsDepsCollector:
    name = "nodejs-deps"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        exclude_test = getattr(config, "exclude_test_paths", True)
        exclude_pats = compile_exclude_patterns(getattr(config, "exclude_paths", []))

        manifest_files: list[str] = []
        raw_deps: list[tuple[str, str, str]] = []  # (source_file, name, version_constraint)

        for pkg_path in sorted(repo_path.rglob("package.json")):
            if "node_modules" in pkg_path.parts:
                continue
            rel = str(pkg_path.relative_to(repo_path))
            if should_exclude_path(
                rel, exclude_test_paths=exclude_test, exclude_patterns=exclude_pats
            ):
                continue
            parsed = _parse_package_json(pkg_path)
            if parsed is None:
                continue
            manifest_files.append(rel)
            raw_deps.extend((rel, name, ver) for name, ver in parsed)

        if not raw_deps:
            return []

        client = DepsDevClient()
        client.prefetch_package_versions("npm", [name for _, name, _ in raw_deps])
        enrichment_errors: list[str] = []
        dependencies: list[dict[str, Any]] = []

        for source_file, name, version_constraint in raw_deps:
            dep = _enrich(client, name, version_constraint, source_file)
            if dep["deps_dev_status"] != "ok":
                enrichment_errors.append(f"{name}: {dep['deps_dev_status']}")
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
                kind="nodejs-deps",
                payload=payload,
            )
        ]


def _parse_package_json(path: Path) -> list[tuple[str, str]] | None:
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.debug("Failed to parse %s", path)
        return None

    if not isinstance(data, dict):
        logger.debug("Unexpected format in %s", path)
        return None

    deps: list[tuple[str, str]] = []
    for section in _DEP_SECTIONS:
        section_data = data.get(section)
        if not isinstance(section_data, dict):
            continue
        for name, version in section_data.items():
            deps.append((name, str(version)))

    return deps


def _enrich(
    client: DepsDevClient, name: str, version_constraint: str, source_file: str
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "declared_version": version_constraint,
        "version_constraint": version_constraint,
        "source_file": source_file,
        "latest_version": None,
        "latest_release_date": None,
        "deps_dev_status": "error",
    }

    data = client.get_package_versions("npm", name)
    if data is None:
        return result

    versions = data.get("versions", [])
    if not versions:
        result["deps_dev_status"] = "not_found"
        return result

    latest = pick_latest_version(versions)
    result["latest_version"] = latest.get("versionKey", {}).get("version") if latest else None
    result["latest_release_date"] = latest.get("publishedAt") if latest else None
    result["deps_dev_status"] = "ok"
    return result


def _register() -> None:
    if "nodejs-deps" not in collector_registry:
        collector_registry.register("nodejs-deps", NodejsDepsCollector())


_register()


__all__ = ["NodejsDepsCollector"]
