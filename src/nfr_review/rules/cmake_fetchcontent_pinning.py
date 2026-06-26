# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: cmake-fetchcontent-pinning -- checks FetchContent dependencies are version-pinned."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.cmake import CmakeConfigPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class CmakeFetchcontentPinningRule(FieldRule[CmakeConfigPayload]):
    """Check that FetchContent dependencies are version-pinned."""

    id = "cmake-fetchcontent-pinning"
    collector_name = "cmake"
    evidence_kind = "cmake-config"
    payload_type = CmakeConfigPayload
    pattern_tag = "cmake-fetchcontent-pinning"
    required_tech = ["cpp"]
    default_confidence = 0.9
    all_clear_summary = "All FetchContent dependencies are version-pinned."
    all_clear_recommendation = "No action required."

    def check(self, payload: CmakeConfigPayload, ev: Evidence) -> Iterable[Hit]:
        for dep in payload.fetchcontent_declares:
            if not dep.is_pinned:
                tag = dep.tag or "(none)"
                yield Hit(
                    rag="red" if not dep.tag else "amber",
                    severity="high" if not dep.tag else "medium",
                    summary=(
                        f"FetchContent dependency '{dep.name}' uses "
                        f"unpinned tag '{tag}' in {payload.file_path}:{dep.line}"
                    ),
                    recommendation=(
                        f"Pin '{dep.name}' to a specific version tag "
                        f"or commit hash instead of a branch name."
                    ),
                    locator=f"{payload.file_path}:{dep.line}",
                    pattern_tag="cmake-unpinned-fetchcontent",
                )


__all__ = ["CmakeFetchcontentPinningRule"]
