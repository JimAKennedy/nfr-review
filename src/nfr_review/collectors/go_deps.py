"""Go dependency collector — parses go.mod files,
enriches each dependency with version metadata from deps.dev.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from nfr_review.deps_dev_client import DepsDevClient
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger(__name__)

_REQUIRE_LINE_RE = re.compile(r"^\s*([\w./@\-]+)\s+(v[\w.\-+]+)")
_GO_VERSION_RE = re.compile(r"^v(\d+(?:\.\d+)*)(.*)$")


class GoDepsCollector:
    name = "go-deps"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        manifest_files: list[str] = []
        raw_deps: list[tuple[str, str, str, bool]] = []  # (source, name, version, indirect)

        for mod_path in sorted(repo_path.rglob("go.mod")):
            rel = str(mod_path.relative_to(repo_path))
            parsed = _parse_go_mod(mod_path)
            if parsed is None:
                continue
            if parsed:
                manifest_files.append(rel)
                raw_deps.extend((rel, name, ver, indirect) for name, ver, indirect in parsed)

        if not raw_deps:
            return []

        client = DepsDevClient()
        client.prefetch_package_versions("go", [name for _, name, _, _ in raw_deps])
        enrichment_errors: list[str] = []
        dependencies: list[dict[str, Any]] = []

        for source_file, name, version, indirect in raw_deps:
            dep = _enrich(client, name, version, source_file, indirect)
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
                kind="go-deps",
                payload=payload,
            )
        ]


def _parse_go_mod(path: Path) -> list[tuple[str, str, bool]] | None:
    try:
        content = path.read_text()
    except OSError:
        logger.debug("Failed to read %s", path)
        return None

    deps: list[tuple[str, str, bool]] = []
    in_require_block = False
    in_skip_block = False

    for line in content.splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith("//"):
            continue

        if stripped.startswith(("replace", "exclude", "retract")):
            if "(" in stripped:
                in_skip_block = True
            continue

        if in_skip_block:
            if stripped == ")":
                in_skip_block = False
            continue

        if stripped.startswith("module ") or stripped.startswith("go "):
            continue

        if stripped.startswith("require ("):
            in_require_block = True
            continue

        if stripped == ")":
            in_require_block = False
            continue

        if stripped.startswith("require "):
            remainder = stripped[len("require ") :]
            match = _REQUIRE_LINE_RE.match(remainder)
            if match:
                indirect = "// indirect" in stripped
                deps.append((match.group(1), match.group(2), indirect))
            else:
                logger.debug("Malformed require line in %s: %s", path, stripped)
            continue

        if in_require_block:
            match = _REQUIRE_LINE_RE.match(stripped)
            if match:
                indirect = "// indirect" in stripped
                deps.append((match.group(1), match.group(2), indirect))
            else:
                logger.debug("Malformed require line in %s: %s", path, stripped)

    return deps


def _enrich(
    client: DepsDevClient, name: str, version: str, source_file: str, indirect: bool
) -> dict[str, Any]:
    m = _GO_VERSION_RE.match(version)
    constraint = f">={m.group(1)}{m.group(2)}" if m else version

    result: dict[str, Any] = {
        "name": name,
        "declared_version": version,
        "version_constraint": constraint,
        "source_file": source_file,
        "latest_version": None,
        "latest_release_date": None,
        "deps_dev_status": "error",
        "indirect": indirect,
    }

    data = client.get_package_versions("go", name)
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
    if "go-deps" not in collector_registry:
        collector_registry.register("go-deps", GoDepsCollector())


_register()


__all__ = ["GoDepsCollector"]
