# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Test coverage mapping for architecture documentation.

Scans component boundary paths for test files, classifies test types,
assesses coverage levels, and identifies gaps. Operates without LLM —
pure file-system analysis.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from nfr_review.arch_models import Component, ComponentTestCoverage, CoverageLevel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hidden / generated directories to skip during scanning
# ---------------------------------------------------------------------------

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        ".idea",
        ".vscode",
        ".gsd",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        "target",
        "build",
        "dist",
        ".gradle",
        ".pytest_cache",
        ".eggs",
        "egg-info",
        ".next",
        ".nuxt",
        "coverage",
    }
)

# ---------------------------------------------------------------------------
# Test directory names (used for identifying test-only subtrees)
# ---------------------------------------------------------------------------

_TEST_DIR_NAMES = frozenset(
    {
        "test",
        "tests",
        "spec",
        "specs",
        "__tests__",
        "e2e",
        "integration",
        "it",
    }
)

# ---------------------------------------------------------------------------
# Language-specific test file patterns
# ---------------------------------------------------------------------------

# Each entry: (compiled regex for basename, language hint)
_TEST_FILE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Python
    (re.compile(r"^test_.*\.py$"), "python"),
    (re.compile(r"^.*_test\.py$"), "python"),
    (re.compile(r"^conftest\.py$"), "python"),
    # Java
    (re.compile(r"^.*Test\.java$"), "java"),
    (re.compile(r"^.*Tests\.java$"), "java"),
    (re.compile(r"^.*IT\.java$"), "java"),
    (re.compile(r"^.*Spec\.java$"), "java"),
    # JavaScript / TypeScript
    (re.compile(r"^.*\.test\.[jt]sx?$"), "js"),
    (re.compile(r"^.*\.spec\.[jt]sx?$"), "js"),
    # Go
    (re.compile(r"^.*_test\.go$"), "go"),
    # C#
    (re.compile(r"^.*Test\.cs$"), "csharp"),
    (re.compile(r"^.*Tests\.cs$"), "csharp"),
    (re.compile(r"^.*Spec\.cs$"), "csharp"),
    (re.compile(r"^.*\.Tests\.csproj$"), "csharp"),
]

# Java conventional test source root
_JAVA_TEST_SRC = "src/test"

# JS config files that indicate test infrastructure
_JS_TEST_CONFIGS = frozenset(
    {
        "jest.config.js",
        "jest.config.ts",
        "jest.config.mjs",
        "jest.config.cjs",
        "vitest.config.js",
        "vitest.config.ts",
        "vitest.config.mjs",
    }
)

# ---------------------------------------------------------------------------
# Source file extensions (for computing ratio)
# ---------------------------------------------------------------------------

_SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".java",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".cs",
        ".rs",
        ".cpp",
        ".c",
        ".h",
        ".hpp",
        ".rb",
        ".kt",
        ".scala",
        ".swift",
        ".m",
    }
)

# ---------------------------------------------------------------------------
# Test-type classification keywords (applied to relative path of test file)
# ---------------------------------------------------------------------------

_TEST_TYPE_KEYWORDS: dict[str, list[str]] = {
    "unit": ["unit"],
    "integration": ["integration", "e2e", "end-to-end", "end_to_end"],
    "performance": ["perf", "benchmark", "load", "stress", "throughput", "latency"],
    "contract": ["contract", "pact", "cdc"],
    "security": ["security", "auth", "authz", "authn", "vulnerability", "penetration"],
    "resilience": ["chaos", "fault", "resilience", "retry", "circuit"],
    "accessibility": ["accessibility", "a11y", "wcag"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_hidden_or_generated(path: Path) -> bool:
    """Check if any part of the path is a hidden/generated directory."""
    return any(part in _SKIP_DIRS or part.startswith(".") for part in path.parts)


def _iter_files(root: Path) -> list[Path]:
    """Recursively list files under *root*, skipping hidden/generated dirs."""
    results: list[Path] = []
    if not root.is_dir():
        return results
    try:
        for child in sorted(root.iterdir()):
            if child.is_file():
                results.append(child)
            elif child.is_dir():
                if child.name in _SKIP_DIRS or child.name.startswith("."):
                    continue
                results.extend(_iter_files(child))
    except OSError:
        pass
    return results


def _is_test_file(path: Path) -> bool:
    """Return True if *path* looks like a test file (by name or location)."""
    name = path.name
    for pat, _ in _TEST_FILE_PATTERNS:
        if pat.match(name):
            return True
    # Files inside conventional test directories
    parts_lower = [p.lower() for p in path.parts]
    if any(p in _TEST_DIR_NAMES for p in parts_lower):
        return True
    # Java src/test convention
    path_str = str(path)
    if _JAVA_TEST_SRC in path_str:
        return True
    return False


def _is_source_file(path: Path) -> bool:
    """Return True if *path* has a recognised source extension and is not a test."""
    return path.suffix in _SOURCE_EXTENSIONS and not _is_test_file(path)


def _classify_test_type(rel_path: str) -> set[str]:
    """Classify the test type(s) for a single test file by its relative path."""
    path_lower = rel_path.lower()
    types: set[str] = set()

    for test_type, keywords in _TEST_TYPE_KEYWORDS.items():
        if any(kw in path_lower for kw in keywords):
            types.add(test_type)

    # Java integration test files (*IT.java)
    if rel_path.endswith("IT.java"):
        types.add("integration")

    # If nothing specific matched, default to unit
    if not types:
        types.add("unit")

    return types


def _nfr_coverage_level(test_types: set[str]) -> CoverageLevel:
    """Assess non-functional coverage based on which NFR-related test types are present."""
    nfr_types = {"performance", "security", "contract", "resilience", "accessibility"}
    present = test_types & nfr_types
    count = len(present)
    if count == 0:
        return "none"
    if count == 1:
        return "minimal"
    if count == 2:
        return "partial"
    if count <= 3:
        return "adequate"
    return "comprehensive"


def _functional_coverage_level(
    test_source_ratio: float, test_type_count: int
) -> CoverageLevel:
    """Determine functional coverage level from ratio and type diversity."""
    if test_source_ratio <= 0:
        return "none"
    if test_source_ratio < 0.10 or test_type_count <= 1:
        return "minimal"
    if test_source_ratio < 0.30 and test_type_count <= 2:
        return "partial"
    if test_source_ratio < 0.60 or test_type_count < 2:
        if test_source_ratio >= 0.30 and test_type_count >= 2:
            return "adequate"
        return "partial"
    if test_type_count >= 3:
        return "comprehensive"
    return "adequate"


def _detect_gaps(
    test_types: set[str],
    source_files: list[Path],
    test_files: list[Path],
    component: Component,
    base_dir: Path,
) -> list[str]:
    """Detect missing test coverage areas."""
    gaps: list[str] = []

    if "unit" not in test_types:
        gaps.append("No unit tests")
    if "integration" not in test_types:
        gaps.append("No integration tests")
    if "performance" not in test_types:
        gaps.append("No performance/load tests")
    if "security" not in test_types:
        gaps.append("No security tests")

    # Check for source directories with no corresponding tests
    if source_files and test_files:
        source_dirs = {
            f.parent.relative_to(base_dir)
            for f in source_files
            if base_dir in f.parents or f.parent == base_dir
        }
        test_rel_paths = {
            str(f.relative_to(base_dir)).lower()
            for f in test_files
            if base_dir in f.parents or f.parent == base_dir
        }

        for src_dir in sorted(source_dirs):
            src_dir_str = str(src_dir).lower()
            # Check if any test file path references this source directory
            has_test = any(src_dir_str in tp for tp in test_rel_paths)
            if not has_test and str(src_dir) != ".":
                gaps.append(f"No tests for source directory: {src_dir}")

    # UI components should have accessibility tests
    if component.component_type == "ui" and "accessibility" not in test_types:
        gaps.append("No accessibility tests for UI component")

    return gaps


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assess_test_coverage(
    repo_path: Path,
    components: list[Component],
    repo_name: str | None = None,
) -> list[ComponentTestCoverage]:
    """Assess test coverage for each component based on file-system analysis.

    For each component, scans its boundary paths within *repo_path* to find
    test files, classify test types, and compute a coverage level.

    Args:
        repo_path: Path to the repository root.
        components: Components to assess (typically from ``discover_components``).
        repo_name: Logical repo name used to match component boundaries.

    Returns:
        One ``ComponentTestCoverage`` per input component.
    """
    effective_name = repo_name or repo_path.name
    results: list[ComponentTestCoverage] = []

    for component in components:
        logger.info("Assessing test coverage for component %s", component.id)
        coverage = _assess_single_component(repo_path, component, effective_name)
        results.append(coverage)

    return results


def assess_test_coverage_multi_repo(
    repo_paths: list[Path],
    all_components: list[Component],
    repo_names: list[str] | None = None,
) -> list[ComponentTestCoverage]:
    """Assess test coverage across multiple repositories.

    Maps each component to its owning repository (via ``Component.repo``)
    and delegates to :func:`assess_test_coverage`.

    Args:
        repo_paths: Paths to each repository root.
        all_components: Components across all repos.
        repo_names: Optional logical names matching *repo_paths* order.

    Returns:
        One ``ComponentTestCoverage`` per input component.
    """
    if repo_names and len(repo_names) != len(repo_paths):
        raise ValueError("repo_names must match repo_paths in length")

    # Build mapping: name -> path
    name_to_path: dict[str, Path] = {}
    for i, rp in enumerate(repo_paths):
        name = repo_names[i] if repo_names else rp.name
        name_to_path[name] = rp

    # Group components by repo
    repo_components: dict[str, list[Component]] = {}
    for comp in all_components:
        repo_key = comp.repo or ""
        repo_components.setdefault(repo_key, []).append(comp)

    results: list[ComponentTestCoverage] = []
    for repo_key, comps in repo_components.items():
        repo_path = name_to_path.get(repo_key)
        if repo_path is None:
            # Fallback: if repo name not in mapping, use first repo path
            logger.warning(
                "No repo path found for %r; skipping %d components",
                repo_key,
                len(comps),
            )
            for comp in comps:
                results.append(
                    ComponentTestCoverage(
                        component_id=comp.id,
                        gaps=["Repository path not available for analysis"],
                    )
                )
            continue
        results.extend(assess_test_coverage(repo_path, comps, repo_name=repo_key))

    return results


# ---------------------------------------------------------------------------
# Single-component assessment
# ---------------------------------------------------------------------------


def _assess_single_component(
    repo_path: Path,
    component: Component,
    effective_name: str,
) -> ComponentTestCoverage:
    """Assess test coverage for one component."""
    # Find the directory to scan from the component's boundaries
    scan_dirs = _resolve_scan_dirs(repo_path, component, effective_name)

    if not scan_dirs:
        logger.info(
            "Component %s has no scannable directories",
            component.id,
        )
        return ComponentTestCoverage(
            component_id=component.id,
            gaps=["No scannable source directory for component"],
        )

    all_test_files: list[Path] = []
    all_source_files: list[Path] = []
    all_test_types: set[str] = set()
    evidence: list[str] = []

    for scan_dir in scan_dirs:
        if not scan_dir.is_dir():
            continue

        files = _iter_files(scan_dir)
        test_files = [f for f in files if _is_test_file(f)]
        source_files = [f for f in files if _is_source_file(f)]

        all_test_files.extend(test_files)
        all_source_files.extend(source_files)

        # Classify test types
        for tf in test_files:
            try:
                rel = str(tf.relative_to(scan_dir))
            except ValueError:
                rel = tf.name
            types = _classify_test_type(rel)
            all_test_types.update(types)
            evidence.append(str(tf.relative_to(repo_path)))

        # Check for JS test config files at scan root
        for config_name in _JS_TEST_CONFIGS:
            if (scan_dir / config_name).is_file():
                evidence.append(str((scan_dir / config_name).relative_to(repo_path)))

    # Compute ratio
    source_count = len(all_source_files)
    test_count = len(all_test_files)

    if source_count > 0:
        ratio = test_count / source_count
    else:
        ratio = float(test_count) if test_count > 0 else 0.0

    # Use total distinct test types for the diversity count
    total_type_count = len(all_test_types)

    functional = _functional_coverage_level(ratio, total_type_count)
    nonfunctional = _nfr_coverage_level(all_test_types)

    # Detect gaps using the first scan dir as reference base
    primary_base = scan_dirs[0] if scan_dirs else repo_path
    gaps = _detect_gaps(
        all_test_types, all_source_files, all_test_files, component, primary_base
    )

    logger.info(
        "Component %s: %d test files, %d source files, ratio=%.2f, "
        "types=%s, functional=%s, nfr=%s",
        component.id,
        test_count,
        source_count,
        ratio,
        sorted(all_test_types),
        functional,
        nonfunctional,
    )

    return ComponentTestCoverage(
        component_id=component.id,
        functional_coverage=functional,
        nonfunctional_coverage=nonfunctional,
        test_types_present=sorted(all_test_types),
        gaps=gaps,
        evidence_locators=sorted(set(evidence)),
    )


def _resolve_scan_dirs(
    repo_path: Path,
    component: Component,
    effective_name: str,
) -> list[Path]:
    """Resolve the file-system directories to scan for a component."""
    dirs: list[Path] = []

    for boundary in component.boundaries:
        # Only scan boundaries belonging to this repo
        if boundary.repo and boundary.repo != effective_name:
            continue

        if boundary.boundary_type == "build_target":
            # Build targets (K8s manifests, compose files) don't have source code
            # Return empty — caller will produce a "none" coverage result
            logger.info(
                "Component %s boundary is build_target (%s), no source to scan",
                component.id,
                boundary.path,
            )
            continue

        # Resolve path relative to repo root
        if boundary.path == ".":
            scan_dir = repo_path
        else:
            scan_dir = repo_path / boundary.path

        if scan_dir.is_dir():
            dirs.append(scan_dir)

    return dirs


__all__ = [
    "assess_test_coverage",
    "assess_test_coverage_multi_repo",
]
