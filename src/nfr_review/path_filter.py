"""Shared test-path detection and path exclusion logic."""

from __future__ import annotations

import fnmatch
import logging
import re

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

__all__ = [
    "is_test_path",
    "should_exclude_path",
    "compile_exclude_patterns",
]


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
