# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the build-readiness hygiene collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "BuildReadinessPayload",
    "BuildSystem",
    "EntryPoints",
    "PreCommit",
    "VersionInfo",
]


class BuildSystem(BasePayload):
    has_build_system: bool
    backend: str | None
    path: str | None


class VersionInfo(BasePayload):
    declared: bool
    value: str | None
    source: str | None


class EntryPoints(BasePayload):
    has_entry_points: bool
    scripts: dict[str, str]


class PreCommit(BasePayload):
    has_pre_commit: bool
    pre_commit_tool: str | None


class BuildReadinessPayload(BasePayload):
    build_system: BuildSystem
    version: VersionInfo
    entry_points: EntryPoints
    pre_commit: PreCommit
