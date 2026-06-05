# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Build readiness collector — checks for build system, version strategy,
and entry point configuration in Python packages.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
import xml.etree.ElementTree as ET  # nosec B405
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.build_readiness import (
    BuildReadinessPayload,
    BuildSystem,
    EntryPoints,
    PreCommit,
    VersionInfo,
)
from nfr_review.hygiene import hygiene_collector_registry
from nfr_review.models import Evidence

logger = logging.getLogger(__name__)


def _parse_pyproject(repo_path: Path) -> dict[str, Any] | None:
    pp = repo_path / "pyproject.toml"
    if not pp.is_file():
        return None
    try:
        return tomllib.loads(pp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.debug("Failed to parse pyproject.toml: %s", e)
        return None


def _detect_build_system(repo_path: Path, pyproject: dict[str, Any] | None) -> BuildSystem:
    if pyproject and "build-system" in pyproject:
        backend = pyproject["build-system"].get("build-backend", "unknown")
        return BuildSystem(has_build_system=True, backend=backend, path="pyproject.toml")

    if (repo_path / "setup.py").is_file():
        return BuildSystem(
            has_build_system=True, backend="setuptools (setup.py)", path="setup.py"
        )

    if (repo_path / "setup.cfg").is_file():
        return BuildSystem(
            has_build_system=True, backend="setuptools (setup.cfg)", path="setup.cfg"
        )

    pom = repo_path / "pom.xml"
    if pom.is_file():
        try:
            ET.parse(pom)  # noqa: S314  # nosec B314
            return BuildSystem(has_build_system=True, backend="maven", path="pom.xml")
        except ET.ParseError:
            pass

    if (repo_path / "build.gradle.kts").is_file():
        return BuildSystem(has_build_system=True, backend="gradle", path="build.gradle.kts")
    if (repo_path / "build.gradle").is_file():
        return BuildSystem(has_build_system=True, backend="gradle", path="build.gradle")

    if (repo_path / "go.mod").is_file():
        return BuildSystem(has_build_system=True, backend="go", path="go.mod")

    if (repo_path / "Cargo.toml").is_file():
        return BuildSystem(has_build_system=True, backend="cargo", path="Cargo.toml")

    for pattern in ("*.csproj", "*.sln"):
        matches = list(repo_path.glob(pattern))
        if matches:
            matched_name = matches[0].name
            return BuildSystem(has_build_system=True, backend="dotnet", path=matched_name)

    if (repo_path / "CMakeLists.txt").is_file():
        return BuildSystem(has_build_system=True, backend="cmake", path="CMakeLists.txt")

    if (repo_path / "meson.build").is_file():
        return BuildSystem(has_build_system=True, backend="meson", path="meson.build")

    if (repo_path / "Makefile").is_file():
        return BuildSystem(has_build_system=True, backend="make", path="Makefile")

    return BuildSystem(has_build_system=False, backend=None, path=None)


_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


def _detect_version(repo_path: Path, pyproject: dict[str, Any] | None) -> VersionInfo:
    if pyproject:
        project = pyproject.get("project", {})
        if "version" in project:
            return VersionInfo(
                declared=True, value=project["version"], source="pyproject.toml"
            )

        dynamic = project.get("dynamic", [])
        if "version" in dynamic:
            return VersionInfo(
                declared=True, value="(dynamic)", source="pyproject.toml[dynamic]"
            )

    for setup_file in ("setup.py", "setup.cfg"):
        p = repo_path / setup_file
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8")
            except OSError as e:  # nosec B112
                logger.debug("Failed to read %s for version detection: %s", setup_file, e)
                continue
            m = re.search(r'version\s*=\s*["\']?([^"\'\s,\n]+)["\']?', text)
            if m:
                return VersionInfo(declared=True, value=m.group(1), source=setup_file)

    for init_path in repo_path.glob("src/*/__init__.py"):
        try:
            text = init_path.read_text(encoding="utf-8")
        except OSError as e:  # nosec B112
            logger.debug("Failed to read %s for version detection: %s", init_path, e)
            continue
        m = _VERSION_RE.search(text)
        if m:
            rel = str(init_path.relative_to(repo_path))
            return VersionInfo(declared=True, value=m.group(1), source=rel)

    for init_path in repo_path.glob("*/__init__.py"):
        if init_path.parent.name.startswith(".") or init_path.parent.name == "tests":
            continue
        try:
            text = init_path.read_text(encoding="utf-8")
        except OSError as e:  # nosec B112
            logger.debug("Failed to read %s for version detection: %s", init_path, e)
            continue
        m = _VERSION_RE.search(text)
        if m:
            rel = str(init_path.relative_to(repo_path))
            return VersionInfo(declared=True, value=m.group(1), source=rel)

    # --- Maven (pom.xml) ---
    pom = repo_path / "pom.xml"
    if pom.is_file():
        try:
            tree = ET.parse(pom)  # noqa: S314  # nosec B314
            root = tree.getroot()
            # Try with Maven namespace first
            ns = {"m": "http://maven.apache.org/POM/4.0.0"}
            ver_el = root.find("m:version", ns)
            if ver_el is None:
                # Try without namespace (pom without namespace declaration)
                ver_el = root.find("version")
            if ver_el is not None and ver_el.text:
                return VersionInfo(declared=True, value=ver_el.text.strip(), source="pom.xml")
        except (ET.ParseError, OSError) as e:  # nosec B110
            logger.debug("Failed to parse pom.xml for version: %s", e)
            pass

    # --- Gradle (build.gradle / build.gradle.kts) ---
    for gradle_file in ("build.gradle.kts", "build.gradle"):
        gp = repo_path / gradle_file
        if gp.is_file():
            try:
                text = gp.read_text(encoding="utf-8")
            except OSError as e:  # nosec B112
                logger.debug("Failed to read %s for version detection: %s", gradle_file, e)
                continue
            m = re.search(r'version\s*[=]?\s*["\']([^"\']+)["\']', text)
            if m:
                return VersionInfo(declared=True, value=m.group(1), source=gradle_file)

    # --- Rust (Cargo.toml) ---
    cargo = repo_path / "Cargo.toml"
    if cargo.is_file():
        try:
            cargo_data = tomllib.loads(cargo.read_text(encoding="utf-8"))
            pkg_version = cargo_data.get("package", {}).get("version")
            if pkg_version:
                return VersionInfo(declared=True, value=pkg_version, source="Cargo.toml")
        except (OSError, ValueError) as e:  # nosec B110
            logger.debug("Failed to parse Cargo.toml for version: %s", e)
            pass

    # --- .NET (*.csproj) ---
    for csproj_path in repo_path.glob("*.csproj"):
        try:
            tree = ET.parse(csproj_path)  # noqa: S314  # nosec B314
            root = tree.getroot()
            for pg in root.iter("PropertyGroup"):
                ver_el = pg.find("Version")
                if ver_el is not None and ver_el.text:
                    return VersionInfo(
                        declared=True,
                        value=ver_el.text.strip(),
                        source=csproj_path.name,
                    )
                asm_el = pg.find("AssemblyVersion")
                if asm_el is not None and asm_el.text:
                    return VersionInfo(
                        declared=True,
                        value=asm_el.text.strip(),
                        source=csproj_path.name,
                    )
        except (ET.ParseError, OSError) as e:  # nosec B110
            logger.debug("Failed to parse %s for version: %s", csproj_path.name, e)
            pass

    # --- Go (go.mod) --- Go uses git tags for versioning
    if (repo_path / "go.mod").is_file():
        return VersionInfo(declared=True, value="(git-tags)", source="go.mod")

    return VersionInfo(declared=False, value=None, source=None)


def _detect_entry_points(repo_path: Path, pyproject: dict[str, Any] | None) -> EntryPoints:
    if pyproject:
        project = pyproject.get("project", {})
        scripts = project.get("scripts", {})
        gui_scripts = project.get("gui-scripts", {})
        all_scripts = {**scripts, **gui_scripts}
        if all_scripts:
            return EntryPoints(has_entry_points=True, scripts=all_scripts)

    for setup_file in ("setup.py", "setup.cfg"):
        p = repo_path / setup_file
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8")
            except OSError as e:  # nosec B112
                logger.debug("Failed to read %s for entry point detection: %s", setup_file, e)
                continue
            if "console_scripts" in text or "gui_scripts" in text:
                label = f"(parsed from {setup_file})"
                return EntryPoints(has_entry_points=True, scripts={label: "..."})

    return EntryPoints(has_entry_points=False, scripts={})


def _detect_pre_commit(repo_path: Path) -> PreCommit:
    if (repo_path / ".pre-commit-config.yaml").is_file():
        return PreCommit(has_pre_commit=True, pre_commit_tool="pre-commit")

    if (repo_path / ".husky").is_dir():
        return PreCommit(has_pre_commit=True, pre_commit_tool="husky")

    if (repo_path / "lefthook.yml").is_file() or (repo_path / "lefthook.yaml").is_file():
        return PreCommit(has_pre_commit=True, pre_commit_tool="lefthook")

    pkg_json = repo_path / "package.json"
    if pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            if "lint-staged" in data:
                return PreCommit(has_pre_commit=True, pre_commit_tool="lint-staged")
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("Failed to parse package.json for lint-staged: %s", e)

    return PreCommit(has_pre_commit=False, pre_commit_tool=None)


class BuildReadinessCollector:
    name = "build-readiness"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        pyproject = _parse_pyproject(repo_path)

        payload = BuildReadinessPayload(
            build_system=_detect_build_system(repo_path, pyproject),
            version=_detect_version(repo_path, pyproject),
            entry_points=_detect_entry_points(repo_path, pyproject),
            pre_commit=_detect_pre_commit(repo_path),
        )

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="build-readiness-analysis",
                payload=payload,
            )
        ]


def _register() -> None:
    if "build-readiness" not in hygiene_collector_registry:
        hygiene_collector_registry.register("build-readiness", BuildReadinessCollector())


_register()

__all__ = ["BuildReadinessCollector"]
