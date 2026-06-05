# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Community health file collector — checks for README, CONTRIBUTING,
CODE_OF_CONDUCT, SECURITY, CHANGELOG, and CODEOWNERS.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nfr_review.collectors.payloads.community import (
    ChangelogStructure,
    CommunityFileInfo,
    CommunityPayload,
    ReadmeSections,
)
from nfr_review.hygiene import hygiene_collector_registry
from nfr_review.models import Evidence

_README_NAMES = ("README.md", "README", "README.rst")
_SECURITY_PATHS = ("SECURITY.md", "SECURITY.txt", ".github/SECURITY.md")
_CHANGELOG_NAMES = ("CHANGELOG.md", "CHANGES.md", "HISTORY.md")
_CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS")

_WELL_KNOWN_SECTIONS = frozenset(
    {
        "installation",
        "install",
        "usage",
        "contributing",
        "license",
        "examples",
        "example",
        "api",
        "api reference",
        "getting started",
        "configuration",
        "config",
        "requirements",
        "prerequisites",
        "testing",
        "tests",
        "changelog",
        "faq",
        "troubleshooting",
        "security",
        "acknowledgements",
        "acknowledgments",
        "credits",
    }
)

_VERSION_HEADER_PATTERN = re.compile(
    r"^##\s+\[?(\d+\.\d+(?:\.\d+)?)\]?"
    r"(?:\s*[-–—]\s*(\d{4}-\d{2}-\d{2}))?",
    re.MULTILINE,
)

_KEEP_A_CHANGELOG_SECTIONS = frozenset(
    {"added", "changed", "deprecated", "removed", "fixed", "security"}
)

_BADGE_PATTERN = re.compile(
    r"!\[[^\]]*\]\("
    r"(?:https?://)?(?:img\.shields\.io|shields\.io|badge\.fury\.io"
    r"|github\.com/[^)]+/(?:actions/)?workflows/[^)]+/badge\.svg"
    r"|coveralls\.io|codecov\.io|travis-ci\.\w+|circleci\.com"
    r"|dl\.circleci\.com|app\.codacy\.com|api\.codeclimate\.com"
    r"|snyk\.io|david-dm\.org|badgen\.net|flat\.badgen\.net)"
    r"[^)]*\)",
)


def _find_file(repo_path: Path, candidates: tuple[str, ...] | list[str]) -> CommunityFileInfo:
    for name in candidates:
        p = repo_path / name
        if p.is_file():
            size = p.stat().st_size
            return CommunityFileInfo(exists=True, path=str(name), size=size)
    return CommunityFileInfo(exists=False, path=None, size=0)


def _extract_readme_sections(text: str) -> ReadmeSections:
    headings: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+)", line)
        if m:
            headings.append(m.group(2).strip())

    heading_lower = [h.lower() for h in headings]
    matched = sorted({s for s in _WELL_KNOWN_SECTIONS if s in heading_lower})

    return ReadmeSections(
        headings=headings, section_count=len(headings), well_known_sections=matched
    )


def _extract_readme_badges(text: str) -> list[str]:
    return _BADGE_PATTERN.findall(text)


def _extract_changelog_structure(text: str) -> ChangelogStructure:
    versions = _VERSION_HEADER_PATTERN.findall(text)
    has_versions = len(versions) > 0

    subsections: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^###\s+(.+)", line)
        if m:
            subsections.add(m.group(1).strip().lower())

    kac_sections_found = sorted(subsections & _KEEP_A_CHANGELOG_SECTIONS)
    follows_kac = len(kac_sections_found) >= 2

    has_recent_entries = False
    now = datetime.now(tz=UTC)
    for _ver, date_str in versions:
        if date_str:
            try:
                entry_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
                days_ago = (now - entry_date).days
                if days_ago <= 180:
                    has_recent_entries = True
                    break
            except ValueError:
                continue

    return ChangelogStructure(
        has_versions=has_versions,
        version_count=len(versions),
        follows_keep_a_changelog=follows_kac,
        kac_sections_found=kac_sections_found,
        has_recent_entries=has_recent_entries,
    )


class CommunityCollector:
    name = "community"
    version = "0.3.0"

    def collect(self, repo_path: Path, config: Any) -> list[Evidence]:
        readme_info = _find_file(repo_path, _README_NAMES)

        readme_sections: ReadmeSections = ReadmeSections(
            headings=[], section_count=0, well_known_sections=[]
        )
        readme_badges: list[str] = []

        if readme_info.exists and readme_info.path:
            try:
                content = (repo_path / readme_info.path).read_text(
                    encoding="utf-8", errors="replace"
                )
                readme_sections = _extract_readme_sections(content)
                readme_badges = _extract_readme_badges(content)
            except OSError:
                pass

        changelog_info = _find_file(repo_path, _CHANGELOG_NAMES)
        changelog_structure: ChangelogStructure = ChangelogStructure(
            has_versions=False,
            version_count=0,
            follows_keep_a_changelog=False,
            kac_sections_found=[],
            has_recent_entries=False,
        )
        if changelog_info.exists and changelog_info.path:
            try:
                cl_content = (repo_path / changelog_info.path).read_text(
                    encoding="utf-8", errors="replace"
                )
                changelog_structure = _extract_changelog_structure(cl_content)
            except OSError:
                pass

        payload = CommunityPayload(
            readme=readme_info,
            readme_sections=readme_sections,
            readme_badges=readme_badges,
            contributing=_find_file(repo_path, ("CONTRIBUTING.md",)),
            code_of_conduct=_find_file(repo_path, ("CODE_OF_CONDUCT.md",)),
            security=_find_file(repo_path, _SECURITY_PATHS),
            changelog=changelog_info,
            changelog_structure=changelog_structure,
            codeowners=_find_file(repo_path, _CODEOWNERS_PATHS),
        )

        return [
            Evidence(
                collector_name=self.name,
                collector_version=self.version,
                locator=".",
                kind="community-analysis",
                payload=payload,
            )
        ]


def _register() -> None:
    if "community" not in hygiene_collector_registry:
        hygiene_collector_registry.register("community", CommunityCollector())


_register()

__all__ = ["CommunityCollector", "_extract_changelog_structure"]
