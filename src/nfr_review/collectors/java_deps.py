"""Java dependency collector — parses pom.xml and build.gradle/build.gradle.kts,
enriches each dependency with version metadata from deps.dev.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET  # nosec B405
from pathlib import Path
from typing import Any

from nfr_review.deps_dev_client import DepsDevClient
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger(__name__)

_SKIP_DIRS = {"target", ".gradle", "build"}

_GRADLE_DEP_RE = re.compile(
    r"(?:implementation|api|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly"
    r"|annotationProcessor)\s*[\(]?\s*['\"]([^'\"]+):([^'\"]+):([^'\"]+)['\"]"
)


class JavaDepsCollector:
    name = "java-deps"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        manifest_files: list[str] = []
        raw_deps: list[tuple[str, str, str, str | None]] = []

        for pom_path in sorted(repo_path.rglob("pom.xml")):
            if _should_skip(pom_path):
                continue
            rel = str(pom_path.relative_to(repo_path))
            parsed = _parse_pom_xml(pom_path)
            if parsed is None:
                continue
            if parsed:
                manifest_files.append(rel)
                raw_deps.extend((rel, name, version, scope) for name, version, scope in parsed)

        for gradle_path in sorted(
            list(repo_path.rglob("build.gradle")) + list(repo_path.rglob("build.gradle.kts"))
        ):
            if _should_skip(gradle_path):
                continue
            rel = str(gradle_path.relative_to(repo_path))
            parsed_gradle = _parse_build_gradle(gradle_path)
            if parsed_gradle:
                manifest_files.append(rel)
                raw_deps.extend((rel, name, version, None) for name, version in parsed_gradle)

        if not raw_deps:
            return []

        client = DepsDevClient()
        enrichment_errors: list[str] = []
        dependencies: list[dict[str, Any]] = []

        for source_file, name, version, scope in raw_deps:
            dep = _enrich(client, name, version, source_file, scope)
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
                kind="java-deps",
                payload=payload,
            )
        ]


def _should_skip(path: Path) -> bool:
    return bool(_SKIP_DIRS & set(path.parts))


def _parse_pom_xml(path: Path) -> list[tuple[str, str, str | None]] | None:
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

    deps_el = root.find(f"{ns}dependencies")
    if deps_el is None:
        return []

    results: list[tuple[str, str, str | None]] = []
    for dep_el in deps_el.findall(f"{ns}dependency"):
        group_id_el = dep_el.find(f"{ns}groupId")
        artifact_id_el = dep_el.find(f"{ns}artifactId")
        if group_id_el is None or artifact_id_el is None:
            continue
        group_id = (group_id_el.text or "").strip()
        artifact_id = (artifact_id_el.text or "").strip()
        if not group_id or not artifact_id:
            continue

        version_el = dep_el.find(f"{ns}version")
        version = (version_el.text or "").strip() if version_el is not None else ""

        scope_el = dep_el.find(f"{ns}scope")
        scope = (scope_el.text or "").strip() if scope_el is not None else None

        name = f"{group_id}:{artifact_id}"
        results.append((name, version, scope))

    return results


def _parse_build_gradle(path: Path) -> list[tuple[str, str]]:
    try:
        content = path.read_text()
    except OSError:
        logger.debug("Failed to read %s", path)
        return []

    deps: list[tuple[str, str]] = []
    for match in _GRADLE_DEP_RE.finditer(content):
        group_id, artifact_id, version = match.group(1), match.group(2), match.group(3)
        name = f"{group_id}:{artifact_id}"
        deps.append((name, version))

    if not deps:
        logger.debug("No dependencies found via regex in %s", path)

    return deps


def _enrich(
    client: DepsDevClient,
    name: str,
    version: str,
    source_file: str,
    scope: str | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "declared_version": version,
        "version_constraint": version,
        "source_file": source_file,
        "latest_version": None,
        "latest_release_date": None,
        "deps_dev_status": "error",
    }
    if scope is not None:
        result["scope"] = scope

    data = client.get_package_versions("maven", name)
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
    if "java-deps" not in collector_registry:
        collector_registry.register("java-deps", JavaDepsCollector())


_register()


__all__ = ["JavaDepsCollector"]
