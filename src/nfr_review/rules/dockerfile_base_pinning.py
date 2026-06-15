# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: dockerfile-base-pinning — flags unpinned base images in Dockerfiles."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_FLOATING_TAGS = frozenset({"latest", "stable", "edge", "beta", "nightly"})

_VERSION_RE = re.compile(r"\d")


class DockerfileBasePinningRule:
    """Flag base images that use floating tags instead of pinned versions or digests."""

    id = "dockerfile-base-pinning"
    band: Band = 1
    required_collectors: list[str] = ["dockerfile"]
    required_tech: list[str] = ["dockerfile"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        df_evidence = filter_evidence(evidence, "dockerfile", "dockerfile-analysis")
        if not df_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no dockerfile evidence available",
            )

        findings: list[Finding] = []
        for ev in df_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for stage in ev.payload.get("stages", []):
                base_image = stage.get("base_image", "")
                base_tag = stage.get("base_tag")
                has_digest = stage.get("has_digest", False)
                line = stage.get("line", 0)

                if base_image == "scratch":
                    continue

                if has_digest:
                    continue

                is_floating = (
                    base_tag is None
                    or base_tag.lower() in _FLOATING_TAGS
                    or not _VERSION_RE.search(base_tag)
                )

                if is_floating:
                    tag_display = base_tag or "(no tag)"
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Base image '{base_image}:{tag_display}' in"
                                f" {file_path}:{line} uses a floating tag."
                            ),
                            recommendation=(
                                "Pin the base image to a specific version tag"
                                " (e.g. python:3.11-slim) or use a digest for"
                                " reproducible builds."
                            ),
                            evidence_locator=f"{file_path}:{line}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="dockerfile-base-pinning",
                        )
                    )

        if not findings:
            first = df_evidence[0]
            findings.append(
                make_green_finding(
                    self.id,
                    "dockerfile-base-pinning",
                    first,
                    summary="All base images are pinned to specific versions or digests.",
                    recommendation="No action required — base images are pinned.",
                    confidence=0.9,
                    evidence_locator="all-dockerfiles",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "dockerfile-base-pinning" not in rule_registry:
        rule_registry.register("dockerfile-base-pinning", DockerfileBasePinningRule())


_register()

__all__ = ["DockerfileBasePinningRule"]
