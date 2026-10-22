# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rust dependency collector — parses Cargo.toml [dependencies] /
[dev-dependencies] tables, enriches each dependency with version metadata
from deps.dev.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.deps import DependencyItem, DepsPayload
from nfr_review.deps_dev_client import DepsDevClient, pick_latest_version
from nfr_review.models import Evidence
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path
from nfr_review.registry import collector_registry

logger = logging.getLogger(__name__)

_DEP_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")


class RustDepsCollector:
    name = "rust-deps"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        exclude_test = getattr(config, "exclude_test_paths", True)
        exclude_pats = compile_exclude_patterns(getattr(config, "exclude_paths", []))

        manifest_files: list[str] = []
        raw_deps: list[tuple[str, str, str]] = []  # (source_file, name, declared_version)

        for cargo_path in sorted(repo_path.rglob("Cargo.toml")):
            rel = str(cargo_path.relative_to(repo_path))
            if should_exclude_path(
                rel, exclude_test_paths=exclude_test, exclude_patterns=exclude_pats
            ):
                continue
            parsed = _parse_cargo_toml(cargo_path)
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


def _parse_cargo_toml(path: Path) -> list[tuple[str, str]]:
    """Return (name, declared_version) pairs. Git/path-only deps (no version
    string, since they aren't published to a registry) are skipped."""
    try:
        data = tomllib.loads(path.read_text())
    except Exception:  # noqa: BLE001
        logger.debug("Failed to parse %s", path)
        return []

    deps: list[tuple[str, str]] = []
    for table_name in _DEP_TABLES:
        table = data.get(table_name, {})
        if not isinstance(table, dict):
            continue
        for name, spec in table.items():
            version = _dep_version(spec)
            if version is not None:
                deps.append((name, version))
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
