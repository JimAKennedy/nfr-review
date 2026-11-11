# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rust dependency collector — parses Cargo.toml dependency tables (including
`[target.<cfg>]` tables, workspace-inherited and renamed dependencies),
enriches each dependency with version metadata from deps.dev. Build output
under `target/` is never read.
"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.deps import DependencyItem, DepsPayload
from nfr_review.deps_dev_client import DepsDevClient, pick_latest_version
from nfr_review.models import Evidence
from nfr_review.path_filter import (
    ALWAYS_SKIP_DIRS,
    compile_exclude_patterns,
    should_exclude_path,
)
from nfr_review.registry import collector_registry

logger = logging.getLogger(__name__)

_DEP_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")
_PRUNE_DIRS = ALWAYS_SKIP_DIRS | {"target"}


class RustDepsCollector:
    name = "rust-deps"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        exclude_test = getattr(config, "exclude_test_paths", True)
        exclude_pats = compile_exclude_patterns(getattr(config, "exclude_paths", []))

        manifest_files: list[str] = []
        raw_deps: list[tuple[str, str, str]] = []  # (source_file, name, declared_version)

        manifests = _find_cargo_tomls(repo_path)
        loaded = {path: _load_cargo_toml(path) for path in manifests}
        for cargo_path in manifests:
            rel = cargo_path.relative_to(repo_path).as_posix()
            if should_exclude_path(
                rel, exclude_test_paths=exclude_test, exclude_patterns=exclude_pats
            ):
                continue
            data = loaded[cargo_path]
            if data is None:
                continue
            parsed = _cargo_deps(data, _workspace_dependencies(cargo_path, repo_path, loaded))
            if not parsed:
                continue
            manifest_files.append(rel)
            raw_deps.extend((rel, name, version) for name, version in parsed)

        if not raw_deps:
            return []

        client = DepsDevClient()
        client.prefetch_package_versions("cargo", [name for _, name, _ in raw_deps])
        enrichment_errors: list[str] = []
        dependencies: list[DependencyItem] = []

        for source_file, name, declared_version in raw_deps:
            dep = _enrich(client, name, declared_version, source_file)
            if dep.deps_dev_status != "ok":
                enrichment_errors.append(f"{name}: {dep.deps_dev_status}")
            dependencies.append(dep)

        payload = DepsPayload(
            dependencies=dependencies,
            manifest_files_found=manifest_files,
            enrichment_errors=enrichment_errors,
        )

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="rust-deps",
                payload=payload,
            )
        ]


def _find_cargo_tomls(repo_path: Path) -> list[Path]:
    """Every Cargo.toml under *repo_path*, never descending into build output."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [d for d in dirnames if d not in _PRUNE_DIRS]
        if "Cargo.toml" in filenames:
            found.append(Path(dirpath) / "Cargo.toml")
    return sorted(found)


def _load_cargo_toml(path: Path) -> dict[str, Any] | None:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.debug("Failed to parse %s", path)
        return None


def _iter_dep_tables(data: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Top-level dependency tables, then the same tables under each [target.<spec>]."""
    sections: list[Any] = [data]
    target = data.get("target")
    if isinstance(target, dict):
        sections.extend(target.values())
    for section in sections:
        if not isinstance(section, dict):
            continue
        for table_name in _DEP_TABLES:
            table = section.get(table_name)
            if isinstance(table, dict):
                yield table


def _workspace_dependencies(
    manifest: Path, repo_path: Path, loaded: dict[Path, dict[str, Any] | None]
) -> dict[str, Any]:
    """[workspace.dependencies] of the nearest ancestor workspace manifest."""
    directory = manifest.parent
    while True:
        data = loaded.get(directory / "Cargo.toml")
        if data is not None:
            workspace = data.get("workspace")
            if isinstance(workspace, dict):
                deps = workspace.get("dependencies", {})
                return deps if isinstance(deps, dict) else {}
        if directory == repo_path or directory.parent == directory:
            return {}
        directory = directory.parent


def _resolve_dep(
    key: str, spec: Any, workspace_deps: dict[str, Any]
) -> tuple[str, str] | None:
    """(crate name, declared version) for one dependency entry, or None
    for git/path-only deps and unresolvable workspace references."""
    if isinstance(spec, dict) and spec.get("workspace") is True:
        spec = workspace_deps.get(key)
    version = _dep_version(spec)
    if version is None:
        return None
    package = spec.get("package") if isinstance(spec, dict) else None
    return (package if isinstance(package, str) else key), version


def _cargo_deps(data: dict[str, Any], workspace_deps: dict[str, Any]) -> list[tuple[str, str]]:
    deps: list[tuple[str, str]] = []
    for table in _iter_dep_tables(data):
        for key, spec in table.items():
            resolved = _resolve_dep(key, spec, workspace_deps)
            if resolved is not None:
                deps.append(resolved)
    return deps


def _dep_version(spec: Any) -> str | None:
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict):
        version = spec.get("version")
        if isinstance(version, str):
            return version
    return None


def _enrich(
    client: DepsDevClient, name: str, declared_version: str, source_file: str
) -> DependencyItem:
    data = client.get_package_versions("cargo", name)
    if data is None:
        return DependencyItem(
            name=name,
            declared_version=declared_version,
            version_constraint=declared_version,
            source_file=source_file,
        )

    versions = data.get("versions", [])
    if not versions:
        return DependencyItem(
            name=name,
            declared_version=declared_version,
            version_constraint=declared_version,
            source_file=source_file,
            deps_dev_status="not_found",
        )

    latest = pick_latest_version(versions)
    return DependencyItem(
        name=name,
        declared_version=declared_version,
        version_constraint=declared_version,
        source_file=source_file,
        latest_version=latest.get("versionKey", {}).get("version") if latest else None,
        latest_release_date=latest.get("publishedAt") if latest else None,
        deps_dev_status="ok",
    )


def _register() -> None:
    if "rust-deps" not in collector_registry:
        collector_registry.register("rust-deps", RustDepsCollector())


_register()


__all__ = ["RustDepsCollector"]
