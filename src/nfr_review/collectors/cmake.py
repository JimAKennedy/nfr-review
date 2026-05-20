"""CMake collector — parses CMakeLists.txt files and emits structured
evidence for downstream CMAKE-* rules.

Evidence payload contract (kind="cmake-config"):
    file_path: str — path relative to repo_path
    cmake_minimum_required: str | None — version string if found
    project_name: str | None
    project_version: str | None
    fetchcontent_declares: list[dict] — each with:
        name: str — dependency name
        url: str — GIT_REPOSITORY or URL value
        tag: str — GIT_TAG value
        line: int — 1-based line number
        is_pinned: bool — True if tag looks like a version or commit hash
    has_target_compile_features: bool
    has_target_compile_options: bool
    has_global_cmake_flags: bool — True if CMAKE_CXX_FLAGS is set directly
    has_install_targets: bool
    options: list[dict] — each with:
        name: str
        description: str
        line: int
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from nfr_review.models import Evidence
from nfr_review.path_filter import compile_exclude_patterns, should_exclude_path
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.cmake")

_HIDDEN_DIRS = frozenset(
    {".git", ".svn", ".hg", ".idea", ".vscode", "node_modules", "__pycache__"}
)

_CMAKE_MIN_RE = re.compile(r"cmake_minimum_required\s*\(\s*VERSION\s+([\d.]+)", re.IGNORECASE)
_PROJECT_RE = re.compile(r"project\s*\(\s*(\w+)(?:\s+VERSION\s+([\d.]+))?", re.IGNORECASE)
_FETCHCONTENT_DECLARE_RE = re.compile(
    r"FetchContent_Declare\s*\(\s*(\w+)", re.IGNORECASE | re.DOTALL
)
_GIT_REPO_RE = re.compile(r"GIT_REPOSITORY\s+([\S]+)", re.IGNORECASE)
_GIT_TAG_RE = re.compile(r"GIT_TAG\s+([\S]+)", re.IGNORECASE)
_OPTION_RE = re.compile(r'option\s*\(\s*(\w+)\s+"([^"]*)"', re.IGNORECASE)
_PINNED_TAG_RE = re.compile(r"^(v?\d+[\d.]*|[0-9a-f]{7,40})$")


def _parse_fetchcontent_blocks(content: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for m in _FETCHCONTENT_DECLARE_RE.finditer(content):
        name = m.group(1)
        line_num = content[: m.start()].count("\n") + 1
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
        url_m = _GIT_REPO_RE.search(block_text)
        tag_m = _GIT_TAG_RE.search(block_text)
        url = url_m.group(1) if url_m else ""
        tag = tag_m.group(1) if tag_m else ""
        is_pinned = bool(_PINNED_TAG_RE.match(tag)) if tag else False
        results.append(
            {
                "name": name,
                "url": url,
                "tag": tag,
                "line": line_num,
                "is_pinned": is_pinned,
            }
        )
    return results


class CmakeCollector:
    name = "cmake"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        exclude_pats = compile_exclude_patterns(getattr(config, "exclude_paths", []))
        exclude_test = getattr(config, "exclude_test_paths", True)
        evidence: list[Evidence] = []
        for cmake_file in sorted(repo_path.rglob("CMakeLists.txt")):
            rel = cmake_file.relative_to(repo_path)
            if any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts):
                continue
            if should_exclude_path(
                str(rel),
                exclude_test_paths=exclude_test,
                exclude_patterns=exclude_pats or None,
            ):
                continue
            try:
                content = cmake_file.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.debug("Cannot read %s: %s", rel, exc)
                continue
            cmake_min = None
            m = _CMAKE_MIN_RE.search(content)
            if m:
                cmake_min = m.group(1)
            project_name = None
            project_version = None
            pm = _PROJECT_RE.search(content)
            if pm:
                project_name = pm.group(1)
                project_version = pm.group(2)
            fetchcontent = _parse_fetchcontent_blocks(content)
            has_target_features = bool(
                re.search(r"target_compile_features\s*\(", content, re.IGNORECASE)
            )
            has_target_options = bool(
                re.search(r"target_compile_options\s*\(", content, re.IGNORECASE)
            )
            has_global_flags = bool(
                re.search(r"set\s*\(\s*CMAKE_CXX_FLAGS", content, re.IGNORECASE)
            )
            has_install = bool(re.search(r"install\s*\(", content, re.IGNORECASE))
            options: list[dict[str, Any]] = []
            for om in _OPTION_RE.finditer(content):
                line_num = content[: om.start()].count("\n") + 1
                options.append(
                    {
                        "name": om.group(1),
                        "description": om.group(2),
                        "line": line_num,
                    }
                )
            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=str(rel),
                    kind="cmake-config",
                    payload={
                        "file_path": str(rel),
                        "cmake_minimum_required": cmake_min,
                        "project_name": project_name,
                        "project_version": project_version,
                        "fetchcontent_declares": fetchcontent,
                        "has_target_compile_features": has_target_features,
                        "has_target_compile_options": has_target_options,
                        "has_global_cmake_flags": has_global_flags,
                        "has_install_targets": has_install,
                        "options": options,
                    },
                )
            )
        return evidence


def _register() -> None:
    if "cmake" not in collector_registry:
        collector_registry.register("cmake", CmakeCollector())


_register()

__all__ = ["CmakeCollector"]
