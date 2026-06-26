# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: cmake-build-config -- checks for modern CMake build configuration practices."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.cmake import CmakeConfigPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class CmakeBuildConfigRule(FieldRule[CmakeConfigPayload]):
    """Check CMake build configuration follows modern practices."""

    id = "cmake-build-config"
    collector_name = "cmake"
    evidence_kind = "cmake-config"
    payload_type = CmakeConfigPayload
    pattern_tag = "cmake-build-config"
    required_tech = ["cpp"]
    default_confidence = 0.85
    all_clear_summary = "CMake build configuration follows modern practices."
    all_clear_recommendation = "No action required."

    def check(self, payload: CmakeConfigPayload, ev: Evidence) -> Iterable[Hit]:
        if payload.has_global_cmake_flags:
            yield Hit(
                rag="amber",
                severity="medium",
                summary=("Global CMAKE_CXX_FLAGS used -- prefer target_compile_options"),
                recommendation=(
                    "Replace set(CMAKE_CXX_FLAGS ...) with "
                    "target_compile_options() for per-target control."
                ),
                locator=payload.file_path,
                confidence=0.85,
                pattern_tag="cmake-global-flags",
            )

        has_target = payload.has_target_compile_features or payload.has_target_compile_options
        if not has_target and not payload.has_global_cmake_flags:
            yield Hit(
                rag="amber",
                severity="low",
                summary="No target_compile_features or target_compile_options found",
                recommendation=(
                    "Use target_compile_features(mylib PUBLIC cxx_std_17) "
                    "to specify C++ standard requirements per target."
                ),
                locator=payload.file_path,
                confidence=0.75,
                pattern_tag="cmake-no-target-features",
            )

        if not payload.project_version:
            yield Hit(
                rag="amber",
                severity="low",
                summary="project() missing VERSION",
                recommendation=(
                    "Add VERSION to project() call for proper versioning: "
                    "project(MyProject VERSION 1.0.0)"
                ),
                locator=payload.file_path,
                confidence=0.8,
                pattern_tag="cmake-no-project-version",
            )


__all__ = ["CmakeBuildConfigRule"]
