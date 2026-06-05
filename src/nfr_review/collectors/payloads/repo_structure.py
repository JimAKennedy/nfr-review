# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the repo-structure collector."""

from __future__ import annotations

from nfr_review.models import BasePayload


class RepoStructureSummaryPayload(BasePayload):
    """Payload for kind='repo-structure-summary' evidence."""

    top_level_files: list[str]
    top_level_dirs: list[str]
    has_readme: bool
    readme_name: str | None = None
    has_git_dir: bool
    has_pyproject: bool


__all__ = ["RepoStructureSummaryPayload"]
