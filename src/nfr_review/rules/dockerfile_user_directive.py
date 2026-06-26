# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: dockerfile-user-directive -- flags Dockerfiles running as root."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.dockerfile import DockerfileAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class DockerfileUserDirectiveRule(FieldRule[DockerfileAnalysisPayload]):
    """Flag Dockerfiles that lack a USER directive (running as root)."""

    id = "dockerfile-user-directive"
    collector_name = "dockerfile"
    evidence_kind = "dockerfile-analysis"
    payload_type = DockerfileAnalysisPayload
    pattern_tag = "dockerfile-user-directive"
    required_tech: list[str] = ["dockerfile"]
    default_confidence = 0.95
    all_clear_summary = "All Dockerfiles specify a USER directive."
    all_clear_recommendation = "No action required -- non-root user configured."

    def check(self, payload: DockerfileAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        if not payload.has_user_directive:
            yield Hit(
                rag="amber",
                severity="high",
                summary=(
                    f"Dockerfile '{payload.file_path}' has no USER directive --"
                    " container runs as root."
                ),
                recommendation=(
                    "Add a USER directive to run the container as a"
                    " non-root user, reducing the blast radius of"
                    " container escapes."
                ),
                locator=payload.file_path,
            )


__all__ = ["DockerfileUserDirectiveRule"]
