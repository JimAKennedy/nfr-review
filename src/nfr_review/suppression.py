# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Inline suppression marker parsing for nfr-review findings.

Source files can suppress individual findings by placing a comment marker
on the same line or the line immediately above::

    auto* widget = new CTextLabel(size);  // nfr-review:skip(cpp-raw-memory)

    # nfr-review:skip(python-broad-except)
    except Exception:
        pass

Multiple rule IDs can be suppressed on one line with comma separation::

    // nfr-review:skip(cpp-raw-memory, cpp-manual-delete)

Use ``nfr-review:skip(*)`` to suppress all rules for a given line.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nfr_review.models import Finding

_MARKER_RE = re.compile(
    r"nfr-review:skip\(([^)]+)\)",
    re.IGNORECASE,
)

_LINE_SUFFIX_RE = re.compile(r":(\d+)$")


def parse_suppression_marker(line: str) -> set[str]:
    """Extract suppressed rule IDs from a source line.

    Returns a set of rule ID strings, or ``{"*"}`` for wildcard suppression.
    Returns an empty set if no marker is found.
    """
    match = _MARKER_RE.search(line)
    if not match:
        return set()
    raw = match.group(1)
    return {tok.strip() for tok in raw.split(",") if tok.strip()}


def _extract_file_and_line(evidence_locator: str) -> tuple[str, int | None]:
    """Parse ``file_path:line`` from an evidence locator."""
    m = _LINE_SUFFIX_RE.search(evidence_locator)
    if m:
        line_num = int(m.group(1))
        file_path = evidence_locator[: m.start()]
        return file_path, line_num
    return evidence_locator, None


def _load_source_lines(file_path: str, cache: dict[str, list[str]]) -> list[str]:
    """Load source file lines into cache. Returns empty list on failure."""
    if file_path in cache:
        return cache[file_path]
    try:
        lines = Path(file_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    cache[file_path] = lines
    return lines


def is_finding_suppressed(
    finding: Finding,
    source_cache: dict[str, list[str]],
    *,
    target_root: Path | None = None,
) -> bool:
    """Check whether a finding is suppressed by an inline marker.

    Checks the finding's source line and the line immediately above it.
    If ``target_root`` is provided, file paths from the evidence locator
    are resolved relative to it.
    """
    file_path, line_num = _extract_file_and_line(finding.evidence_locator)
    if line_num is None:
        return False

    if target_root is not None:
        resolved = target_root / file_path
        file_path = str(resolved)

    lines = _load_source_lines(file_path, source_cache)
    if not lines:
        return False

    line_idx = line_num - 1
    lines_to_check: list[str] = []
    if 0 <= line_idx < len(lines):
        lines_to_check.append(lines[line_idx])
    if 0 <= line_idx - 1 < len(lines):
        lines_to_check.append(lines[line_idx - 1])

    for src_line in lines_to_check:
        suppressed_ids = parse_suppression_marker(src_line)
        if not suppressed_ids:
            continue
        if "*" in suppressed_ids or finding.rule_id in suppressed_ids:
            return True

    return False


def apply_suppressions(
    findings: list[Finding],
    *,
    target_root: Path | None = None,
) -> tuple[list[Finding], list[Finding]]:
    """Partition findings into active and suppressed lists.

    Returns (active_findings, suppressed_findings).
    """
    source_cache: dict[str, list[str]] = {}
    active: list[Finding] = []
    suppressed: list[Finding] = []

    for f in findings:
        if is_finding_suppressed(f, source_cache, target_root=target_root):
            suppressed.append(f)
        else:
            active.append(f)

    return active, suppressed


__all__ = [
    "apply_suppressions",
    "is_finding_suppressed",
    "parse_suppression_marker",
]
