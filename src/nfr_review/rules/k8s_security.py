# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: non-root-container-violation -- checks containers enforce runAsNonRoot."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.k8s import K8sResourcePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class NonRootContainerViolationRule(FieldRule[K8sResourcePayload]):
    """Flag containers without securityContext.runAsNonRoot=true."""

    id = "non-root-container-violation"
    collector_name = "k8s-manifest"
    evidence_kind = "k8s-resource"
    payload_type = K8sResourcePayload
    pattern_tag = "k8s-non-root"
    required_tech: list[str] = ["kubernetes"]
    default_confidence = 0.9
    all_clear_summary = "All containers enforce runAsNonRoot."
    all_clear_recommendation = "No action required -- non-root is enforced."

    def check(self, payload: K8sResourcePayload, ev: Evidence) -> Iterable[Hit]:
        for container in payload.containers:
            sec_ctx = container.security_context
            runs_as_non_root = (
                isinstance(sec_ctx, dict) and sec_ctx.get("runAsNonRoot") is True
            )
            if not runs_as_non_root:
                yield Hit(
                    rag="amber",
                    summary=(
                        f"Container '{container.name}' in"
                        f" {payload.name} does not set"
                        f" runAsNonRoot=true."
                    ),
                    recommendation=(
                        "Set securityContext.runAsNonRoot: true to"
                        " prevent the container from running as the"
                        " root user, reducing attack surface."
                    ),
                    locator=f"{payload.file_path}:{payload.name}:{container.name}",
                )


__all__ = ["NonRootContainerViolationRule"]
