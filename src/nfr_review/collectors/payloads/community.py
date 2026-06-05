# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the community hygiene collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "ChangelogStructure",
    "CommunityFileInfo",
    "CommunityPayload",
    "ReadmeSections",
]


class CommunityFileInfo(BasePayload):
    exists: bool
    path: str | None
    size: int


class ReadmeSections(BasePayload):
    headings: list[str]
    section_count: int
    well_known_sections: list[str]


class ChangelogStructure(BasePayload):
    has_versions: bool
    version_count: int
    follows_keep_a_changelog: bool
    kac_sections_found: list[str]
    has_recent_entries: bool


class CommunityPayload(BasePayload):
    readme: CommunityFileInfo
    readme_sections: ReadmeSections
    readme_badges: list[str]
    contributing: CommunityFileInfo
    code_of_conduct: CommunityFileInfo
    security: CommunityFileInfo
    changelog: CommunityFileInfo
    changelog_structure: ChangelogStructure
    codeowners: CommunityFileInfo
