# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Path-based classification of findings into source vs test regions and
first-party vs dependency origin."""

from __future__ import annotations

import re
from typing import Literal

from nfr_review.models import Finding, Origin, _strip_line_from_locator
from nfr_review.path_filter import _TEST_PATH_PATTERNS, compile_exclude_patterns

Region = Literal["source", "test"]

_DEP_COLLECTOR_SUFFIXES = ("-deps",)

_DEP_LOCATOR_PREFIX = "dep:"


def classify_region(path: str) -> Region:
    """Classify a file path as 'source' or 'test'.

    Matches against common test directory and file naming conventions
    for Python, Go, Java, C#, and JavaScript/TypeScript.
    """
    normalised = path.replace("\\", "/")
    for pattern in _TEST_PATH_PATTERNS:
        if pattern.search(normalised):
            return "test"
    return "source"


def classify_origin(
    finding: Finding,
    dependency_patterns: list[re.Pattern[str]] | None = None,
) -> Origin:
    """Classify whether a finding relates to first-party code or a dependency."""
    if finding.evidence_locator.startswith(_DEP_LOCATOR_PREFIX):
        return "dependency"
    if dependency_patterns:
        path = _strip_line_from_locator(finding.evidence_locator)
        normalised = path.replace("\\", "/")
        for pat in dependency_patterns:
            if pat.search(normalised):
                return "dependency"
    return "first_party"


def apply_origin_classification(
    findings: list[Finding],
    dependency_paths: list[str] | None = None,
) -> list[Finding]:
    """Set the ``origin`` field on each finding in-place and return the list."""
    dep_patterns = compile_exclude_patterns(dependency_paths) if dependency_paths else None
    for finding in findings:
        origin = classify_origin(finding, dep_patterns)
        if origin != finding.origin:
            object.__setattr__(finding, "origin", origin)
    return findings


def filter_findings_by_origin(
    findings: list[Finding],
    origin: Origin,
) -> list[Finding]:
    """Return only findings matching the given origin."""
    return [f for f in findings if f.origin == origin]


def partition_findings(
    findings: list[Finding],
) -> tuple[list[Finding], list[Finding]]:
    """Split findings into (source_findings, test_findings) by evidence_locator."""
    source: list[Finding] = []
    test: list[Finding] = []
    for finding in findings:
        if classify_region(finding.evidence_locator) == "test":
            test.append(finding)
        else:
            source.append(finding)
    return source, test


def partition_findings_by_origin(
    findings: list[Finding],
) -> tuple[list[Finding], list[Finding]]:
    """Split findings into (first_party, dependency) by origin field."""
    first_party: list[Finding] = []
    dependency: list[Finding] = []
    for finding in findings:
        if finding.origin == "dependency":
            dependency.append(finding)
        else:
            first_party.append(finding)
    return first_party, dependency
