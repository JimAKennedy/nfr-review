# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: health-endpoint-missing -- checks for health endpoint in Spring controllers."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.java_ast import JavaAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_HEALTH_PATHS = frozenset({"/health", "/actuator/health"})


class HealthEndpointMissingRule(FieldRule[JavaAstFilePayload]):
    """Flag when no @RestController exposes a health-check endpoint."""

    id = "health-endpoint-missing"
    collector_name = "java-ast"
    evidence_kind = "java-ast-file"
    payload_type = JavaAstFilePayload
    pattern_tag = "health-endpoint"
    default_confidence = 0.9
    all_clear_summary = (
        "No health endpoint (/health or /actuator/health) detected in any @RestController."
    )
    all_clear_recommendation = (
        "Add a health-check endpoint (e.g. Spring"
        " Boot Actuator /actuator/health) to enable"
        " liveness/readiness probes."
    )

    def check(self, payload: JavaAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for cls in payload.classes:
            if "RestController" not in cls.annotations:
                continue
            for method in cls.methods:
                for path in method.mapping_paths:
                    if path in _HEALTH_PATHS:
                        yield Hit(
                            rag="green",
                            summary=f"Health endpoint found: {path} in {cls.name}",
                            recommendation="No action required -- health endpoint is present.",
                            locator=f"{payload.file_path}:{cls.name}",
                        )
                        return

        # No health endpoint found across all classes in this file --
        # yield an amber hit so the framework aggregates across files.
        yield Hit(
            rag="amber",
            severity="medium",
            summary=(
                "No health endpoint (/health or"
                " /actuator/health) detected in any"
                " @RestController."
            ),
            recommendation=(
                "Add a health-check endpoint (e.g. Spring"
                " Boot Actuator /actuator/health) to enable"
                " liveness/readiness probes."
            ),
            locator="project-wide",
        )


__all__ = ["HealthEndpointMissingRule"]
