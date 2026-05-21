# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared test-path detection and path exclusion logic."""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import subprocess  # nosec B404 — args are hardcoded, not user input
from pathlib import Path

log = logging.getLogger(__name__)

_TEST_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)tests?/"),
    re.compile(r"(^|/)__tests__/"),
    re.compile(r"(^|/)spec/"),
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"(^|/)[^/]+_test\.py$"),
    re.compile(r"(^|/)[^/]+_test\.go$"),
    re.compile(r"(^|/)conftest\.py$"),
    re.compile(r"(^|/)[^/]*Test\.java$"),
    re.compile(r"(^|/)[^/]*Tests\.java$"),
    re.compile(r"(^|/)[^/]*Test\.cs$"),
    re.compile(r"(^|/)[^/]*Tests\.cs$"),
    re.compile(r"(^|/)[^/]+\.test\.[jt]sx?$"),
    re.compile(r"(^|/)[^/]+\.spec\.[jt]sx?$"),
)

_ALWAYS_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".gsd",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "node_modules",
        ".regression-repos",
    }
)

__all__ = [
    "ALWAYS_SKIP_DIRS",
    "get_git_tracked_files",
    "iter_repo_files",
    "is_test_path",
    "should_exclude_path",
    "compile_exclude_patterns",
]

ALWAYS_SKIP_DIRS = _ALWAYS_SKIP_DIRS


def get_git_tracked_files(repo_path: Path) -> frozenset[str] | None:
    """Return relative paths of files git considers part of the project.

    Includes tracked files and untracked non-ignored files.
    Returns ``None`` if *repo_path* is not a git repo or git is unavailable.
    """
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.rstrip("\0")
        if not raw:
            return frozenset()
        return frozenset(raw.split("\0"))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def iter_repo_files(repo_path: Path) -> list[Path]:
    """Return files in a repo, respecting ``.gitignore`` when available.

    Git repos: tracked + untracked-but-not-ignored files.
    Non-git dirs: ``os.walk`` with ``_ALWAYS_SKIP_DIRS`` exclusion.
    """
    tracked = get_git_tracked_files(repo_path)
    if tracked is not None:
        return sorted(repo_path / rel for rel in tracked if (repo_path / rel).is_file())
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [d for d in dirnames if d not in _ALWAYS_SKIP_DIRS]
        for fname in filenames:
            files.append(Path(dirpath) / fname)
    return sorted(files)


def _in_skipped_dir(path: str) -> bool:
    """Return True if any path component is a directory that should always be skipped."""
    parts = path.split("/")
    return bool(_ALWAYS_SKIP_DIRS.intersection(parts))


def is_test_path(path: str) -> bool:
    """Return True if *path* matches a known test-file convention."""
    normalised = path.replace("\\", "/")
    for pattern in _TEST_PATH_PATTERNS:
        if pattern.search(normalised):
            return True
    return False


def should_exclude_path(
    rel_path: str,
    *,
    exclude_test_paths: bool = True,
    exclude_patterns: list[re.Pattern[str]] | None = None,
) -> bool:
    """Return True if *rel_path* should be excluded from analysis."""
    normalised = rel_path.replace("\\", "/")
    if _in_skipped_dir(normalised):
        return True
    if exclude_test_paths and is_test_path(normalised):
        return True
    if exclude_patterns:
        for pattern in exclude_patterns:
            if pattern.search(normalised):
                return True
    return False


def compile_exclude_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    """Compile glob-style strings into regex patterns.

    Invalid patterns are logged at WARNING level and skipped.
    """
    compiled: list[re.Pattern[str]] = []
    for raw in patterns:
        try:
            regex = fnmatch.translate(raw)
            compiled.append(re.compile(regex))
        except re.error as exc:
            log.warning("Skipping invalid exclude pattern %r: %s", raw, exc)
    return compiled
