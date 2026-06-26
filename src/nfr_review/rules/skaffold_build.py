# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: skaffold-build-config — checks Skaffold build configuration quality."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.skaffold import SkaffoldAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_EXPLICIT_TAG_POLICIES = frozenset(
    {
        "sha256",
        "envTemplate",
        "dateTime",
        "customTemplate",
        "inputDigest",
    }
)


class SkaffoldBuildConfigRule(FieldRule[SkaffoldAnalysisPayload]):
    """Flag Skaffold configs missing build sections or with weak tag policies."""

    id = "skaffold-build-config"
    collector_name = "skaffold"
    evidence_kind = "skaffold-analysis"
    payload_type = SkaffoldAnalysisPayload
    pattern_tag = "skaffold-build-config"
    required_tech = ["skaffold"]
    default_confidence = 0.9
    all_clear_summary = (
        "Skaffold build config uses an explicit tag policy for reproducible image tagging."
    )
    all_clear_recommendation = "No action required."

    def check(self, payload: SkaffoldAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        build = payload.build

        if not build or not build.get("artifacts"):
            yield Hit(
                rag="red",
                severity="high",
                summary=(
                    "Skaffold config has no build section or no artifacts defined."
                    " Builds may not be reproducible."
                ),
                recommendation=(
                    "Define a build section with explicit artifacts"
                    " in skaffold.yaml to ensure reproducible container builds."
                ),
                locator=ev.locator,
            )
            return

        tag_policy = build.get("tagPolicy", {}) or {}
        has_explicit_policy = any(key in tag_policy for key in _EXPLICIT_TAG_POLICIES)

        if "gitCommit" in tag_policy and not has_explicit_policy:
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(
                    "Skaffold uses gitCommit tag policy."
                    " Tags depend on local git state and may not be"
                    " reproducible across environments."
                ),
                recommendation=(
                    "Consider using sha256, envTemplate, or dateTime"
                    " tag policy for more deterministic image tags."
                ),
                locator=ev.locator,
                confidence=0.8,
            )
        elif not tag_policy or (not has_explicit_policy and "gitCommit" not in tag_policy):
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(
                    "Skaffold config has no explicit tag policy."
                    " Default tagging may produce non-deterministic image tags."
                ),
                recommendation=(
                    "Define an explicit tagPolicy (sha256, envTemplate,"
                    " or dateTime) in the build section for reproducible tags."
                ),
                locator=ev.locator,
                confidence=0.8,
            )
        # else: explicit policy is present — no hit, base class emits green


__all__ = ["SkaffoldBuildConfigRule"]
