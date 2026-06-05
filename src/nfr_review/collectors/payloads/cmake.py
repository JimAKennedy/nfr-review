# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the CMake collector."""

from __future__ import annotations

from nfr_review.models import BasePayload


class CmakeFetchContentDeclare(BasePayload):
    """A single FetchContent_Declare block."""

    name: str
    url: str
    tag: str
    line: int
    is_pinned: bool


class CmakeOption(BasePayload):
    """A CMake option() declaration."""

    name: str
    description: str
    line: int


class CmakeConfigPayload(BasePayload):
    """Payload for kind='cmake-config' evidence."""

    file_path: str
    cmake_minimum_required: str | None = None
    project_name: str | None = None
    project_version: str | None = None
    fetchcontent_declares: list[CmakeFetchContentDeclare]
    has_target_compile_features: bool
    has_target_compile_options: bool
    has_global_cmake_flags: bool
    has_install_targets: bool
    options: list[CmakeOption]


__all__ = [
    "CmakeFetchContentDeclare",
    "CmakeOption",
    "CmakeConfigPayload",
]
