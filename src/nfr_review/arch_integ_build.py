# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Build-system integration discovery (Maven, Gradle, CMake).

Extracts inter-module and cross-repo dependencies from Maven POM files,
Gradle build scripts, and CMake FetchContent / add_subdirectory directives.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from nfr_review.arch_models import (
    Component,
    IntegrationPoint,
)
from nfr_review.arch_utils import (
    component_by_name,
    component_by_repo_name,
    is_comment_line,
    make_id,
    safe_read_text,
)
from nfr_review.path_filter import should_exclude_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategy 3: Maven / Gradle inter-module dependencies
# ---------------------------------------------------------------------------


def _parse_maven_coordinates(pom_text: str) -> dict[str, str]:
    """Extract groupId and artifactId from a POM file."""
    result: dict[str, str] = {}
    gid_match = re.search(r"<groupId>([^<]+)</groupId>", pom_text)
    aid_match = re.search(r"<artifactId>([^<]+)</artifactId>", pom_text)
    if gid_match:
        result["groupId"] = gid_match.group(1).strip()
    if aid_match:
        result["artifactId"] = aid_match.group(1).strip()
    return result


def discover_maven_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Find inter-module Maven dependencies (sibling module references)."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    root_pom = repo_path / "pom.xml"
    if not root_pom.is_file():
        return []

    root_content = safe_read_text(root_pom)
    if not root_content:
        return []

    # Find declared modules
    module_pattern = re.compile(r"<module>([^<]+)</module>")
    modules = module_pattern.findall(root_content)
    if not modules:
        return []

    # Build a map of groupId:artifactId -> component for sibling modules
    module_coords: dict[str, str] = {}  # "groupId:artifactId" -> module_name
    # Also extract root groupId as default
    root_coords = _parse_maven_coordinates(root_content)
    root_gid = root_coords.get("groupId", "")

    for module_name in modules:
        module_pom = repo_path / module_name / "pom.xml"
        if not module_pom.is_file():
            continue
        mod_content = safe_read_text(module_pom)
        if not mod_content:
            continue

        coords = _parse_maven_coordinates(mod_content)
        gid = coords.get("groupId", root_gid)
        aid = coords.get("artifactId", module_name)
        module_coords[f"{gid}:{aid}"] = module_name

    # Now scan each module's dependencies for references to siblings
    dep_pattern = re.compile(
        r"<dependency>\s*"
        r"<groupId>([^<]+)</groupId>\s*"
        r"<artifactId>([^<]+)</artifactId>",
        re.DOTALL,
    )

    for module_name in modules:
        module_pom = repo_path / module_name / "pom.xml"
        if not module_pom.is_file():
            continue
        mod_content = safe_read_text(module_pom)
        if not mod_content:
            continue

        source_comp = component_by_name(components, module_name)
        if source_comp is None:
            continue

        for dep_match in dep_pattern.finditer(mod_content):
            dep_gid = dep_match.group(1).strip()
            dep_aid = dep_match.group(2).strip()
            dep_key = f"{dep_gid}:{dep_aid}"

            target_module = module_coords.get(dep_key)
            if target_module is None or target_module == module_name:
                continue

            target_comp = component_by_name(components, target_module)
            if target_comp is None:
                continue

            intg_id = make_id(
                "intg",
                f"{effective_name}/maven/{module_name}->{target_module}",
            )
            integrations.append(
                IntegrationPoint(
                    id=intg_id,
                    source_component_id=source_comp.id,
                    target_component_id=target_comp.id,
                    style="api_call",
                    protocol="jvm",
                    description=(
                        f"Maven module '{module_name}' depends on "
                        f"'{target_module}' ({dep_key})"
                    ),
                )
            )

    if integrations:
        logger.info("Found %d Maven inter-module integrations", len(integrations))
    return integrations


def discover_gradle_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Find Gradle project(':sub') dependencies between sub-projects."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name

    # Find sub-projects from settings file
    settings_file = None
    for name in ("settings.gradle", "settings.gradle.kts"):
        candidate = repo_path / name
        if candidate.is_file():
            settings_file = candidate
            break

    if settings_file is None:
        return []

    settings_content = safe_read_text(settings_file)
    if not settings_content:
        return []

    include_pattern = re.compile(r"""include\s*\(?\s*['"]([^'"]+)['"]\s*\)?""")
    project_names: list[str] = []
    for match in include_pattern.finditer(settings_content):
        project_names.append(match.group(1).lstrip(":"))

    # Scan each sub-project's build file for project(':...') dependencies
    project_dep_pattern = re.compile(
        r"""(?:implementation|api|compile|compileOnly|runtimeOnly|testImplementation)"""
        r"""[\s(]*project\s*\(\s*['":]+([^'")\s]+)['")]+""",
    )

    for proj_name in project_names:
        proj_dir = repo_path / proj_name.replace(":", "/")
        if not proj_dir.is_dir():
            continue

        for build_name in ("build.gradle", "build.gradle.kts"):
            build_file = proj_dir / build_name
            if not build_file.is_file():
                continue

            build_content = safe_read_text(build_file)
            if not build_content:
                continue

            source_comp = component_by_name(components, proj_name)
            if source_comp is None:
                continue

            for dep_match in project_dep_pattern.finditer(build_content):
                dep_project = dep_match.group(1).lstrip(":").replace(":", "/")
                target_comp = component_by_name(components, dep_project)
                if target_comp is None or target_comp.id == source_comp.id:
                    continue

                intg_id = make_id(
                    "intg",
                    f"{effective_name}/gradle/{proj_name}->{dep_project}",
                )
                integrations.append(
                    IntegrationPoint(
                        id=intg_id,
                        source_component_id=source_comp.id,
                        target_component_id=target_comp.id,
                        style="api_call",
                        protocol="jvm",
                        description=(
                            f"Gradle project '{proj_name}' depends on project '{dep_project}'"
                        ),
                    )
                )

            break  # Only process first build file found per sub-project

    if integrations:
        logger.info("Found %d Gradle inter-project integrations", len(integrations))
    return integrations


# ---------------------------------------------------------------------------
# Strategy 10: CMake FetchContent / add_subdirectory cross-repo deps
# ---------------------------------------------------------------------------

_FETCHCONTENT_DECLARE_RE = re.compile(
    r"FetchContent_Declare\s*\(\s*(\w+)", re.IGNORECASE | re.DOTALL
)
_CMAKE_GIT_REPO_RE = re.compile(r"GIT_REPOSITORY\s+([\S]+)", re.IGNORECASE)
_ADD_SUBDIR_RE = re.compile(r"add_subdirectory\s*\(\s*([^\s)]+)", re.IGNORECASE)


def repo_name_from_url(url: str) -> str | None:
    """Extract a repository name from a Git URL.

    Handles https://host/org/repo.git, git@host:org/repo.git, and bare names.
    """
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # Last path segment
    slash_idx = url.rfind("/")
    colon_idx = url.rfind(":")
    sep = max(slash_idx, colon_idx)
    if sep >= 0:
        return url[sep + 1 :]
    return url or None


def discover_cmake_integrations(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[IntegrationPoint]:
    """Discover cross-repo dependencies from CMake FetchContent and add_subdirectory."""
    integrations: list[IntegrationPoint] = []
    effective_name = repo_name or repo_path.name
    seen_pairs: set[tuple[str, str]] = set()

    source_comp = component_by_name(components, effective_name)
    if source_comp is None:
        for comp in components:
            if comp.repo and comp.repo.lower() == effective_name.lower():
                source_comp = comp
                break

    if source_comp is None:
        return integrations

    cmake_files: list[Path] = []
    for cmake_path in repo_path.rglob("CMakeLists.txt"):
        if should_exclude_path(str(cmake_path.relative_to(repo_path))):
            continue
        cmake_files.append(cmake_path)

    for cmake_path in sorted(cmake_files):
        content = safe_read_text(cmake_path)
        if not content:
            continue

        # FetchContent_Declare — match GIT_REPOSITORY URLs to known components
        for m in _FETCHCONTENT_DECLARE_RE.finditer(content):
            dep_name = m.group(1)
            start = m.start()
            paren_depth = 0
            end = start
            for idx in range(start, len(content)):
                if content[idx] == "(":
                    paren_depth += 1
                elif content[idx] == ")":
                    paren_depth -= 1
                    if paren_depth == 0:
                        end = idx + 1
                        break
            block_text = content[start:end]

            if is_comment_line(content, m.start()):
                continue

            url_m = _CMAKE_GIT_REPO_RE.search(block_text)
            if not url_m:
                continue
            url = url_m.group(1)
            extracted_name = repo_name_from_url(url)
            if not extracted_name:
                continue

            target_comp = component_by_repo_name(components, extracted_name)
            if target_comp is None:
                target_comp = component_by_name(components, dep_name)
            if target_comp is None or target_comp.id == source_comp.id:
                continue

            pair = (source_comp.id, target_comp.id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            rel_path = cmake_path.relative_to(repo_path)
            integrations.append(
                IntegrationPoint(
                    id=make_id("cmake-fetch", f"{effective_name}-{extracted_name}"),
                    source_component_id=source_comp.id,
                    target_component_id=target_comp.id,
                    style="build_dependency",
                    protocol="cmake-fetchcontent",
                    description=(
                        f"FetchContent dependency on {extracted_name} via {rel_path}"
                    ),
                )
            )

        # add_subdirectory — match relative paths to sibling repos
        for m in _ADD_SUBDIR_RE.finditer(content):
            if is_comment_line(content, m.start()):
                continue
            subdir_arg = m.group(1)
            resolved = (cmake_path.parent / subdir_arg).resolve()
            target_name = resolved.name

            target_comp = component_by_repo_name(components, target_name)
            if target_comp is None or target_comp.id == source_comp.id:
                continue

            pair = (source_comp.id, target_comp.id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            rel_path = cmake_path.relative_to(repo_path)
            integrations.append(
                IntegrationPoint(
                    id=make_id("cmake-subdir", f"{effective_name}-{target_name}"),
                    source_component_id=source_comp.id,
                    target_component_id=target_comp.id,
                    style="build_dependency",
                    protocol="cmake-add-subdirectory",
                    description=(
                        f"add_subdirectory dependency on {target_name} via {rel_path}"
                    ),
                )
            )

    if integrations:
        logger.info(
            "Found %d CMake cross-repo dependencies in %s",
            len(integrations),
            effective_name,
        )
    return integrations
