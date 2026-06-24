# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: dockerfile-multistage -- suggests multi-stage builds for single-stage Dockerfiles."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.dockerfile import DockerfileAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class DockerfileMultistageRule(FieldRule[DockerfileAnalysisPayload]):
    """Suggest multi-stage builds when a single-stage Dockerfile has RUN commands."""

    id = "dockerfile-multistage"
    collector_name = "dockerfile"
    evidence_kind = "dockerfile-analysis"
    payload_type = DockerfileAnalysisPayload
    pattern_tag = "dockerfile-multistage"
    required_tech: list[str] = ["dockerfile"]
    default_confidence = 0.7
    all_clear_summary = "All Dockerfiles use multi-stage builds."
    all_clear_recommendation = "No action required -- multi-stage builds in use."

    def check(self, payload: DockerfileAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        if not payload.is_multistage and len(payload.run_commands) > 0:
            yield Hit(
                rag="amber",
                severity="low",
                summary=(
                    f"Dockerfile '{payload.file_path}' uses a single-stage"
                    f" build with {len(payload.run_commands)} RUN command(s)."
                ),
                recommendation=(
                    "Consider a multi-stage build to separate build"
                    " dependencies from the runtime image, reducing"
                    " final image size and attack surface."
                ),
                locator=payload.file_path,
            )


__all__ = ["DockerfileMultistageRule"]
