# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: cmake-minimum-version -- checks cmake_minimum_required is present and modern."""

from __future__ import annotations

from collections.abc import Iterable

from packaging.version import InvalidVersion, Version

from nfr_review.collectors.payloads.cmake import CmakeConfigPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_MODERN_CMAKE_VERSION = Version("3.14")


class CmakeMinimumVersionRule(FieldRule[CmakeConfigPayload]):
    """Check cmake_minimum_required is present and modern."""

    id = "cmake-minimum-version"
    collector_name = "cmake"
    evidence_kind = "cmake-config"
    payload_type = CmakeConfigPayload
    pattern_tag = "cmake-minimum-version"
    required_tech = ["cpp"]
    default_confidence = 0.95
    all_clear_summary = "cmake_minimum_required is present and modern."
    all_clear_recommendation = "No action required."

    def check(self, payload: CmakeConfigPayload, ev: Evidence) -> Iterable[Hit]:
        version_str = payload.cmake_minimum_required
        if version_str is None:
            yield Hit(
                rag="red",
                severity="high",
                summary="cmake_minimum_required is missing",
                recommendation=(
                    "Add cmake_minimum_required(VERSION 3.21) or later "
                    "to ensure reproducible builds."
                ),
                locator=payload.file_path,
                confidence=0.95,
                pattern_tag="cmake-no-minimum-version",
            )
        else:
            try:
                ver = Version(version_str)
            except InvalidVersion:
                ver = Version("0.0")
            if ver < _MODERN_CMAKE_VERSION:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary=(f"cmake_minimum_required is {version_str} -- pre-modern CMake"),
                    recommendation=(
                        "Upgrade to cmake_minimum_required(VERSION 3.14) "
                        "or later for modern CMake target-based workflow."
                    ),
                    locator=payload.file_path,
                    confidence=0.85,
                    pattern_tag="cmake-old-minimum-version",
                )


__all__ = ["CmakeMinimumVersionRule"]
