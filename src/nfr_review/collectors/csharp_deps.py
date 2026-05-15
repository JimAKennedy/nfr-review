"""C# dependency collector — parses .csproj files (MSBuild XML with
PackageReference elements), enriches each dependency with version metadata
from deps.dev.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET  # nosec B405
from pathlib import Path
from typing import Any

from nfr_review.deps_dev_client import DepsDevClient
from nfr_review.models import Evidence
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path
from nfr_review.registry import collector_registry

logger = logging.getLogger(__name__)

_SKIP_DIRS = {"bin", "obj"}
_BARE_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


class CsharpDepsCollector:
    name = "csharp-deps"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        exclude_test = getattr(config, "exclude_test_paths", True)
        exclude_pats = compile_exclude_patterns(getattr(config, "exclude_paths", []))

        manifest_files: list[str] = []
        raw_deps: list[tuple[str, str, str]] = []

        for csproj_path in sorted(repo_path.rglob("*.csproj")):
            if _should_skip(csproj_path):
                continue
            rel = str(csproj_path.relative_to(repo_path))
            if should_exclude_path(
                rel, exclude_test_paths=exclude_test, exclude_patterns=exclude_pats
            ):
                continue
            parsed = _parse_csproj(csproj_path)
            if parsed is None:
                continue
            if parsed:
                manifest_files.append(rel)
                raw_deps.extend((rel, name, version) for name, version in parsed)

        if not raw_deps:
            return []

        client = DepsDevClient()
        client.prefetch_package_versions("nuget", [name for _, name, _ in raw_deps])
        enrichment_errors: list[str] = []
        dependencies: list[dict[str, Any]] = []

        for source_file, name, version in raw_deps:
            dep = _enrich(client, name, version, source_file)
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
                kind="csharp-deps",
                payload=payload,
            )
        ]


def _should_skip(path: Path) -> bool:
    return bool(_SKIP_DIRS & set(path.parts))


def _parse_csproj(path: Path) -> list[tuple[str, str]] | None:
    try:
        tree = ET.parse(path)  # nosec B314
    except (ET.ParseError, OSError):
        logger.debug("Failed to parse %s", path)
        return None

    root = tree.getroot()
    tag = root.tag
    ns = ""
    if tag.startswith("{"):
        ns = tag[: tag.index("}") + 1]

    results: list[tuple[str, str]] = []
    for item_group in root.findall(f"{ns}ItemGroup"):
        for pkg_ref in item_group.findall(f"{ns}PackageReference"):
            include = pkg_ref.get("Include")
            if not include:
                continue

            version = pkg_ref.get("Version", "")
            if not version:
                version_el = pkg_ref.find(f"{ns}Version")
                version = (version_el.text or "").strip() if version_el is not None else ""

            results.append((include, version))

    return results


def _enrich(
    client: DepsDevClient,
    name: str,
    version: str,
    source_file: str,
) -> dict[str, Any]:
    constraint = f">={version}" if version and _BARE_VERSION_RE.match(version) else version
    result: dict[str, Any] = {
        "name": name,
        "declared_version": version,
        "version_constraint": constraint,
        "source_file": source_file,
        "latest_version": None,
        "latest_release_date": None,
        "deps_dev_status": "error",
    }

    data = client.get_package_versions("nuget", name)
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
    if "csharp-deps" not in collector_registry:
        collector_registry.register("csharp-deps", CsharpDepsCollector())


_register()


__all__ = ["CsharpDepsCollector"]
