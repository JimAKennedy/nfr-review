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

Optionally, a justification reason can follow the marker for audit trails::

    // nfr-review:skip(cpp-raw-memory) reason: JIRA-1234 legacy allocation
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nfr_review.models import Finding

_MARKER_RE = re.compile(
    r"nfr-review:skip\(([^)]+)\)(?:\s+reason:\s*(.+))?",
    re.IGNORECASE,
)

_COMMENT_CLOSE_RE = re.compile(r"\s*(?:\*/|-->)\s*$")

_LINE_SUFFIX_RE = re.compile(r":(\d+)$")


@dataclass(frozen=True, slots=True)
class SuppressionInfo:
    """Full suppression context for a finding."""

    rule_ids: frozenset[str]
    reason: str | None
    source_file: str
    source_line: int


def parse_suppression_marker(line: str) -> tuple[set[str], str | None]:
    """Extract suppressed rule IDs and optional reason from a source line.

    Returns ``(rule_ids, reason)``.  ``rule_ids`` is a set of rule ID
    strings (or ``{"*"}`` for wildcard).  ``reason`` is the justification
    text after ``reason:``, or ``None`` when absent.  Returns
    ``(set(), None)`` when no marker is found.
    """
    match = _MARKER_RE.search(line)
    if not match:
        return set(), None
    raw = match.group(1)
    rule_ids = {tok.strip() for tok in raw.split(",") if tok.strip()}
    reason_raw = match.group(2)
    reason: str | None = None
    if reason_raw:
        reason = _COMMENT_CLOSE_RE.sub("", reason_raw).strip() or None
    return rule_ids, reason


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
) -> SuppressionInfo | None:
    """Check whether a finding is suppressed by an inline marker.

    Checks the finding's source line and the line immediately above it.
    If ``target_root`` is provided, file paths from the evidence locator
    are resolved relative to it.

    Returns a :class:`SuppressionInfo` when suppressed, or ``None``.
    """
    file_path, line_num = _extract_file_and_line(finding.evidence_locator)
    if line_num is None:
        return None

    if target_root is not None:
        resolved = (target_root / file_path).resolve()
        if not resolved.is_relative_to(target_root.resolve()):
            return None
        file_path = str(resolved)

    lines = _load_source_lines(file_path, source_cache)
    if not lines:
        return None

    line_idx = line_num - 1
    lines_to_check: list[tuple[str, int]] = []
    if 0 <= line_idx < len(lines):
        lines_to_check.append((lines[line_idx], line_num))
    if 0 <= line_idx - 1 < len(lines):
        lines_to_check.append((lines[line_idx - 1], line_num - 1))

    for src_line, src_line_num in lines_to_check:
        rule_ids, reason = parse_suppression_marker(src_line)
        if not rule_ids:
            continue
        if "*" in rule_ids or finding.rule_id in rule_ids:
            return SuppressionInfo(
                rule_ids=frozenset(rule_ids),
                reason=reason,
                source_file=file_path,
                source_line=src_line_num,
            )

    return None


def apply_suppressions(
    findings: list[Finding],
    *,
    target_root: Path | None = None,
) -> tuple[list[Finding], list[tuple[Finding, SuppressionInfo]]]:
    """Partition findings into active and suppressed lists.

    Returns ``(active_findings, suppressed_findings)`` where each
    suppressed entry is a ``(Finding, SuppressionInfo)`` tuple carrying
    the justification and source location of the marker.
    """
    source_cache: dict[str, list[str]] = {}
    active: list[Finding] = []
    suppressed: list[tuple[Finding, SuppressionInfo]] = []

    for f in findings:
        info = is_finding_suppressed(f, source_cache, target_root=target_root)
        if info is not None:
            suppressed.append((f, info))
        else:
            active.append(f)

    return active, suppressed


__all__ = [
    "SuppressionInfo",
    "apply_suppressions",
    "is_finding_suppressed",
    "parse_suppression_marker",
]
