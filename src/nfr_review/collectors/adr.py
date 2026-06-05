# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""ADR collector — scans markdown Architecture Decision Records and emits
per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="adr-document"):
    file_path: str — path relative to repo_path
    title: str | None — first # heading
    status: str | None — from YAML frontmatter or ## Status section
    date: str | None — from frontmatter or filename prefix
    superseded_by: str | None — from frontmatter or body text
    has_frontmatter: bool

Evidence payload contract (kind="adr-summary"):
    total_adrs: int
    statuses: dict[str, int] — status value → count
    has_lifecycle_tracking: bool — True if any ADR has a status field
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.adr import AdrDocumentPayload, AdrSummaryPayload
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.adr")

_HIDDEN_DIRS = frozenset({".git", ".svn", ".hg", ".idea", ".vscode", "node_modules"})

_ADR_DIRS = ("docs/adr", "doc/adr", "adr", "docs/decisions", "decisions")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.+?)\n---\s*\n", re.DOTALL)
_STATUS_HEADING_RE = re.compile(r"^##\s+Status\s*$", re.MULTILINE)
_SUPERSEDED_BODY_RE = re.compile(r"[Ss]uperseded\s+by\s+\[?ADR[- ]?(\d+)\]?", re.IGNORECASE)
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _is_hidden(rel: Path) -> bool:
    return any(part.startswith(".") or part in _HIDDEN_DIRS for part in rel.parts)


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract simple key: value pairs from YAML frontmatter."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _extract_status_from_section(text: str) -> str | None:
    """Extract status from ## Status section (first non-empty line after heading)."""
    match = _STATUS_HEADING_RE.search(text)
    if not match:
        return None
    after = text[match.end() :]
    for line in after.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped.lower()
    return None


def _parse_adr(file_path: Path, repo_path: Path) -> AdrDocumentPayload:
    """Parse a single ADR markdown file and return a typed payload."""
    rel = file_path.relative_to(repo_path)
    text = file_path.read_text(encoding="utf-8", errors="replace")

    frontmatter = _parse_frontmatter(text)
    has_frontmatter = bool(frontmatter)

    # Title: first # heading
    title_match = _TITLE_RE.search(text)
    title = title_match.group(1).strip() if title_match else None

    # Status: prefer frontmatter, fallback to ## Status section
    status: str | None = frontmatter.get("status")
    if status:
        status = status.lower()
    else:
        status = _extract_status_from_section(text)

    # Date: prefer frontmatter, fallback to filename prefix pattern NNNN-
    date: str | None = frontmatter.get("date")
    if not date:
        name = file_path.stem
        if re.match(r"^\d{4}-", name):
            date = None  # NNNN- is an ADR number, not a date

    # Superseded-by: prefer frontmatter, fallback to body regex
    superseded_by: str | None = frontmatter.get("superseded-by")
    if not superseded_by:
        body_match = _SUPERSEDED_BODY_RE.search(text)
        if body_match:
            superseded_by = body_match.group(1)

    return AdrDocumentPayload(
        file_path=str(rel),
        title=title,
        status=status,
        date=date,
        superseded_by=superseded_by,
        has_frontmatter=has_frontmatter,
    )


class AdrCollector:
    """Collect evidence from Architecture Decision Record markdown files."""

    name = "adr"
    version = "0.1.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        md_files = self._discover_files(repo_path)

        for md_file in md_files:
            rel = md_file.relative_to(repo_path)
            try:
                payload = _parse_adr(md_file, repo_path)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error parsing %s: %s", rel, exc)
                continue

            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator=str(rel),
                    kind="adr-document",
                    payload=payload,
                )
            )

        # Emit summary evidence
        if evidence:
            statuses: dict[str, int] = {}
            has_lifecycle = False
            for ev in evidence:
                assert isinstance(ev.payload, AdrDocumentPayload)
                st = ev.payload.status
                if st:
                    has_lifecycle = True
                    statuses[st] = statuses.get(st, 0) + 1
                else:
                    statuses["unknown"] = statuses.get("unknown", 0) + 1

            evidence.append(
                Evidence(
                    collector_name=self.name,
                    collector_version=self.version,
                    locator="adr-summary",
                    kind="adr-summary",
                    payload=AdrSummaryPayload(
                        total_adrs=len(evidence),
                        statuses=statuses,
                        has_lifecycle_tracking=has_lifecycle,
                    ),
                )
            )

        return evidence

    def _discover_files(self, repo_path: Path) -> list[Path]:
        """Discover ADR markdown files in standard locations."""
        seen: set[Path] = set()
        files: list[Path] = []

        for adr_dir in _ADR_DIRS:
            candidate = repo_path / adr_dir
            if candidate.is_dir():
                for md_file in sorted(candidate.rglob("*.md")):
                    rel = md_file.relative_to(repo_path)
                    if not _is_hidden(rel) and md_file not in seen:
                        seen.add(md_file)
                        files.append(md_file)

        return files


def _register() -> None:
    if "adr" not in collector_registry:
        collector_registry.register("adr", AdrCollector())


_register()

__all__ = ["AdrCollector"]
