# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: dockerfile-base-pinning -- flags unpinned base images in Dockerfiles."""

from __future__ import annotations

import re
from collections.abc import Iterable

from nfr_review.collectors.payloads.dockerfile import DockerfileAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_FLOATING_TAGS = frozenset({"latest", "stable", "edge", "beta", "nightly"})

_VERSION_RE = re.compile(r"\d")


class DockerfileBasePinningRule(FieldRule[DockerfileAnalysisPayload]):
    """Flag base images that use floating tags instead of pinned versions or digests."""

    id = "dockerfile-base-pinning"
    collector_name = "dockerfile"
    evidence_kind = "dockerfile-analysis"
    payload_type = DockerfileAnalysisPayload
    pattern_tag = "dockerfile-base-pinning"
    required_tech: list[str] = ["dockerfile"]
    default_confidence = 0.9
    all_clear_summary = "All base images are pinned to specific versions or digests."
    all_clear_recommendation = "No action required -- base images are pinned."

    def check(self, payload: DockerfileAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        for stage in payload.stages:
            if stage.base_image == "scratch":
                continue

            if stage.has_digest:
                continue

            is_floating = (
                stage.base_tag is None
                or stage.base_tag.lower() in _FLOATING_TAGS
                or not _VERSION_RE.search(stage.base_tag)
            )

            if is_floating:
                tag_display = stage.base_tag or "(no tag)"
                yield Hit(
                    rag="amber",
                    summary=(
                        f"Base image '{stage.base_image}:{tag_display}' in"
                        f" {payload.file_path}:{stage.line} uses a floating tag."
                    ),
                    recommendation=(
                        "Pin the base image to a specific version tag"
                        " (e.g. python:3.11-slim) or use a digest for"
                        " reproducible builds."
                    ),
                    locator=f"{payload.file_path}:{stage.line}",
                )


__all__ = ["DockerfileBasePinningRule"]
