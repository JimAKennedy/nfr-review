# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Manifest-based cross-repo dependency detection.

Parses build manifests (pom.xml, build.gradle, package.json, pyproject.toml,
requirements.txt, go.mod, Cargo.toml, *.csproj) to extract declared
dependencies.  When a declared dependency matches a component in the
analysis set (by repo name or artifact ID), emits an IntegrationPoint
with ``style='build_dependency'``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

from nfr_review.arch_models import Component, IntegrationPoint
from nfr_review.arch_utils import (
    make_id,
    safe_read_text,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-ecosystem dependency extractors
# ---------------------------------------------------------------------------
# Each returns list[tuple[str, str]] — (dep_name, version_spec).
# dep_name is the canonical identifier for that ecosystem:
#   Maven: groupId:artifactId
#   Gradle: group:name
#   npm: package name
#   Python: normalized package name
#   Go: module path
#   Rust: crate name
#   .NET: NuGet package ID

_MAVEN_DEP_RE = re.compile(
    r"<dependency>\s*"
    r"<groupId>([^<]+)</groupId>\s*"
    r"<artifactId>([^<]+)</artifactId>"
    r"(?:\s*<version>([^<]*)</version>)?",
    re.DOTALL,
)

_MAVEN_PARENT_RE = re.compile(
    r"<parent>\s*"
    r"<groupId>([^<]+)</groupId>\s*"
    r"<artifactId>([^<]+)</artifactId>"
    r"(?:\s*<version>([^<]*)</version>)?",
    re.DOTALL,
)

_MAVEN_MODULE_RE = re.compile(r"<module>([^<]+)</module>")


def extract_maven_deps(content: str) -> list[tuple[str, str]]:
    """Extract dependencies from a Maven pom.xml."""
    deps: list[tuple[str, str]] = []
    for m in _MAVEN_DEP_RE.finditer(content):
        group_id, artifact_id, version = m.group(1), m.group(2), m.group(3) or ""
        deps.append((f"{group_id}:{artifact_id}", version.strip()))
    for m in _MAVEN_PARENT_RE.finditer(content):
        group_id, artifact_id, version = m.group(1), m.group(2), m.group(3) or ""
        deps.append((f"{group_id}:{artifact_id}", version.strip()))
    for m in _MAVEN_MODULE_RE.finditer(content):
        deps.append((m.group(1).strip(), ""))
    return deps


_GRADLE_DEP_RE = re.compile(
    r"""(?:implementation|api|compileOnly|runtimeOnly|testImplementation|classpath)"""
    r"""\s*(?:\(\s*)?['"]([^'"]+)['"]\s*\)?""",
)


def extract_gradle_deps(content: str) -> list[tuple[str, str]]:
    """Extract dependencies from build.gradle / build.gradle.kts."""
    deps: list[tuple[str, str]] = []
    for m in _GRADLE_DEP_RE.finditer(content):
        coord = m.group(1).strip()
        parts = coord.split(":")
        if len(parts) >= 2:
            name = f"{parts[0]}:{parts[1]}"
            version = parts[2] if len(parts) > 2 else ""
            deps.append((name, version))
        else:
            deps.append((coord, ""))
    return deps


def extract_npm_deps(content: str) -> list[tuple[str, str]]:
    """Extract dependencies from package.json."""
    deps: list[tuple[str, str]] = []
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return deps
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = data.get(key, {})
        if isinstance(section, dict):
            for name, version in section.items():
                deps.append((name, str(version)))
    return deps


_PYPROJECT_DEP_RE = re.compile(r'^"?([a-zA-Z0-9_.-]+)', re.MULTILINE)


def extract_python_deps(content: str, filename: str = "") -> list[tuple[str, str]]:
    """Extract dependencies from pyproject.toml, requirements.txt, or setup.cfg."""
    deps: list[tuple[str, str]] = []
    lower = filename.lower()

    if lower.endswith(".toml") or (not lower and "[project]" in content):
        in_deps = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped in ("dependencies = [", "dependencies = ["):
                in_deps = True
                continue
            if re.match(r"^(dependencies|optional-dependencies)\s*=\s*\[", stripped):
                in_deps = True
                continue
            if in_deps:
                if stripped == "]" or (stripped and not stripped.startswith(('"', "'", "#"))):
                    if stripped == "]":
                        in_deps = False
                    continue
                m = re.match(
                    r"""['"]([a-zA-Z0-9_.-]+)(?:\[.*?\])?\s*([><=!~^].*?)?['"]""", stripped
                )
                if m:
                    deps.append(
                        (_normalize_python_name(m.group(1)), (m.group(2) or "").strip())
                    )
    elif lower.endswith((".txt", ".in")) or (not lower and "==" in content):
        for line in content.splitlines():
            line = line.split("#")[0].strip()
            if not line or line.startswith("-"):
                continue
            m = re.match(r"([a-zA-Z0-9_.-]+)(?:\[.*?\])?\s*([><=!~^].*)?", line)
            if m:
                deps.append((_normalize_python_name(m.group(1)), (m.group(2) or "").strip()))
    elif lower.endswith(".cfg"):
        in_deps = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "install_requires =":
                in_deps = True
                continue
            if in_deps:
                if stripped and not stripped[0].isspace() and "=" in stripped:
                    in_deps = False
                    continue
                m = re.match(r"([a-zA-Z0-9_.-]+)(?:\[.*?\])?\s*([><=!~^].*)?", stripped)
                if m:
                    deps.append(
                        (_normalize_python_name(m.group(1)), (m.group(2) or "").strip())
                    )
    return deps


def _normalize_python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


_GO_BLOCK_DEP_RE = re.compile(r"^\s*(\S+)\s+(v\S+)", re.MULTILINE)
_GO_REQUIRE_BLOCK_RE = re.compile(r"require\s*\((.*?)\)", re.DOTALL)
_GO_SINGLE_REQUIRE_RE = re.compile(r"^require\s+(\S+)\s+(v\S+)", re.MULTILINE)


def extract_go_deps(content: str) -> list[tuple[str, str]]:
    """Extract dependencies from go.mod."""
    deps: list[tuple[str, str]] = []
    for block_m in _GO_REQUIRE_BLOCK_RE.finditer(content):
        block = block_m.group(1)
        for m in _GO_BLOCK_DEP_RE.finditer(block):
            deps.append((m.group(1), m.group(2)))
    for m in _GO_SINGLE_REQUIRE_RE.finditer(content):
        if not any(d[0] == m.group(1) for d in deps):
            deps.append((m.group(1), m.group(2)))
    return deps


_CARGO_DEP_RE = re.compile(
    r"""^\s*([a-zA-Z0-9_-]+)\s*=\s*(?:"([^"]+)"|{[^}]*version\s*=\s*"([^"]+)"[^}]*})""",
    re.MULTILINE,
)


def extract_rust_deps(content: str) -> list[tuple[str, str]]:
    """Extract dependencies from Cargo.toml."""
    deps: list[tuple[str, str]] = []
    in_deps = False
    for line in content.splitlines():
        stripped = line.strip()
        if re.match(r"\[(dev-)?dependencies(\.[^\]]+)?\]", stripped):
            in_deps = True
            continue
        if stripped.startswith("[") and "dependencies" not in stripped:
            in_deps = False
            continue
        if in_deps:
            m = _CARGO_DEP_RE.match(line)
            if m:
                name = m.group(1)
                version = m.group(2) or m.group(3) or ""
                deps.append((name, version))
    return deps


_CSPROJ_PKG_RE = re.compile(
    r'<PackageReference\s+Include="([^"]+)"(?:\s+Version="([^"]*)")?',
)
_CSPROJ_PROJ_RE = re.compile(
    r'<ProjectReference\s+Include="([^"]+)"',
)


def extract_dotnet_deps(content: str) -> list[tuple[str, str]]:
    """Extract dependencies from a .NET .csproj file."""
    deps: list[tuple[str, str]] = []
    for m in _CSPROJ_PKG_RE.finditer(content):
        deps.append((m.group(1), m.group(2) or ""))
    for m in _CSPROJ_PROJ_RE.finditer(content):
        proj_path = m.group(1).replace("\\", "/")
        proj_name = Path(proj_path).stem
        deps.append((proj_name, ""))
    return deps


# ---------------------------------------------------------------------------
# Manifest file scanning
# ---------------------------------------------------------------------------

_ExtractFn = Callable[[str], list[tuple[str, str]]]

_MANIFEST_EXTRACTORS: list[tuple[str, str | list[str], _ExtractFn]] = [
    ("maven", "pom.xml", extract_maven_deps),
    ("gradle", ["build.gradle", "build.gradle.kts"], extract_gradle_deps),
    ("npm", "package.json", extract_npm_deps),
    ("go", "go.mod", extract_go_deps),
    ("rust", "Cargo.toml", extract_rust_deps),
]

_PYTHON_MANIFEST_FILES = [
    "pyproject.toml",
    "requirements.txt",
    "requirements.in",
    "setup.cfg",
]


def _scan_manifest_deps(comp_dir: Path) -> list[tuple[str, str, str]]:
    """Scan a directory for manifest files and extract deps.

    Returns list of (ecosystem, dep_name, version_spec).
    """
    results: list[tuple[str, str, str]] = []

    for ecosystem, filenames, extractor in _MANIFEST_EXTRACTORS:
        if isinstance(filenames, str):
            filenames = [filenames]
        for fname in filenames:
            fpath = comp_dir / fname
            if fpath.is_file():
                content = safe_read_text(fpath)
                if not content:
                    continue
                try:
                    deps = extractor(content)
                    for dep_name, version in deps:
                        results.append((ecosystem, dep_name, version))
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to parse %s", fpath, exc_info=True)

    for fname in _PYTHON_MANIFEST_FILES:
        fpath = comp_dir / fname
        if fpath.is_file():
            content = safe_read_text(fpath)
            if not content:
                continue
            try:
                deps = extract_python_deps(content, fname)
                for dep_name, version in deps:
                    results.append(("python", dep_name, version))
            except Exception:  # noqa: BLE001
                logger.warning("Failed to parse %s", fpath, exc_info=True)

    for csproj in comp_dir.glob("*.csproj"):
        content = safe_read_text(csproj)
        if not content:
            continue
        try:
            deps = extract_dotnet_deps(content)
            for dep_name, version in deps:
                results.append(("dotnet", dep_name, version))
        except Exception:  # noqa: BLE001
            logger.warning("Failed to parse %s", csproj, exc_info=True)

    return results


# ---------------------------------------------------------------------------
# Cross-repo manifest correlation strategy
# ---------------------------------------------------------------------------


def _build_artifact_index(
    components: list[Component],
) -> dict[str, Component]:
    """Build a lookup from artifact/package names to components.

    Maps multiple possible artifact names for each component:
    - component name (lowercase)
    - repo name (lowercase)
    - component ID
    """
    index: dict[str, Component] = {}
    for comp in components:
        index[comp.name.lower()] = comp
        if comp.repo:
            index[comp.repo.lower()] = comp
        index[comp.id.lower()] = comp
    return index


def _match_dep_to_component(
    dep_name: str,
    ecosystem: str,
    artifact_index: dict[str, Component],
    source_comp: Component,
) -> Component | None:
    """Try to match a dependency name to a component in the analysis set."""
    candidates: list[str] = [dep_name.lower()]

    if ecosystem == "maven":
        parts = dep_name.split(":")
        if len(parts) == 2:
            candidates.append(parts[1].lower())
    elif ecosystem == "gradle":
        parts = dep_name.split(":")
        if len(parts) >= 2:
            candidates.append(parts[1].lower())
    elif ecosystem == "go":
        parts = dep_name.rsplit("/", 1)
        if len(parts) == 2:
            candidates.append(parts[1].lower())
    elif ecosystem == "dotnet":
        candidates.append(dep_name.lower())

    for candidate in candidates:
        match = artifact_index.get(candidate)
        if match and match.id != source_comp.id:
            return match
    return None


def discover_manifest_cross_repo_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Discover cross-repo dependencies from build manifest declarations.

    For each component, parses manifest files to extract declared
    dependencies.  When a dependency name matches another component
    in the analysis set, emits an IntegrationPoint with
    ``style='build_dependency'``.

    Parameters
    ----------
    repo_path:
        Path to the repository root.
    components:
        Components from all repos in the analysis set.
    repo_name:
        Optional human-friendly name for the repository.
    """
    artifact_index = _build_artifact_index(components)
    integrations: list[IntegrationPoint] = []
    seen: set[tuple[str, str]] = set()

    for comp in components:
        for boundary in comp.boundaries:
            comp_dir = repo_path / boundary.path
            if not comp_dir.is_dir() and boundary.path != ".":
                continue
            if boundary.path == ".":
                comp_dir = repo_path

            manifest_deps = _scan_manifest_deps(comp_dir)
            dep_count = len(manifest_deps)
            if dep_count:
                logger.debug(
                    "Component %s: %d manifest deps from %s",
                    comp.id,
                    dep_count,
                    comp_dir,
                )

            for ecosystem, dep_name, _version in manifest_deps:
                target = _match_dep_to_component(dep_name, ecosystem, artifact_index, comp)
                if target is None:
                    continue

                edge_key = (comp.id, target.id)
                if edge_key in seen:
                    continue
                seen.add(edge_key)

                integrations.append(
                    IntegrationPoint(
                        id=make_id("integ", f"{comp.id}-{target.id}-manifest"),
                        source_component_id=comp.id,
                        target_component_id=target.id,
                        style="build_dependency",
                        protocol=f"manifest-{ecosystem}",
                        description=(
                            f"{comp.name} declares dependency on "
                            f"{target.name} via {ecosystem} manifest"
                        ),
                    )
                )

    if integrations:
        logger.info(
            "Manifest strategy: %d cross-repo build dependencies",
            len(integrations),
        )
    return integrations


__all__ = [
    "discover_manifest_cross_repo_integrations",
    "extract_maven_deps",
    "extract_gradle_deps",
    "extract_npm_deps",
    "extract_python_deps",
    "extract_go_deps",
    "extract_rust_deps",
    "extract_dotnet_deps",
]
