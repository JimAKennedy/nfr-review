"""Path-based classification of findings into source vs test regions."""

from __future__ import annotations

from typing import Literal

from nfr_review.models import Finding
from nfr_review.path_filter import _TEST_PATH_PATTERNS

Region = Literal["source", "test"]


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
