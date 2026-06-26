# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: jacoco-threshold-missing — flags Java/Maven projects without JaCoCo plugin."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.deps import DepsPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_JACOCO_GROUP = "org.jacoco"


class JacocoThresholdRule(FieldRule[DepsPayload]):
    id = "jacoco-threshold-missing"
    collector_name = "java-deps"
    evidence_kind = "java-deps"
    payload_type = DepsPayload
    pattern_tag = "jacoco-coverage"
    required_tech = ["java"]
    default_confidence = 0.85
    all_clear_summary = "JaCoCo plugin is present in Maven dependencies."
    all_clear_recommendation = "No action required — JaCoCo coverage tooling is configured."

    def check(self, payload: DepsPayload, ev: Evidence) -> Iterable[Hit]:
        has_jacoco = any(
            dep.name.startswith(f"{_JACOCO_GROUP}:") for dep in payload.dependencies
        )
        if not has_jacoco:
            locator = (
                payload.manifest_files_found[0] if payload.manifest_files_found else ev.locator
            )
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(
                    "No JaCoCo Maven plugin found. Code coverage thresholds"
                    " cannot be enforced in CI."
                ),
                recommendation=(
                    "Add org.jacoco:jacoco-maven-plugin to the build and configure"
                    " <rules> with a minimum line/branch coverage threshold"
                    " (e.g., 80%). Bind the check goal to the verify phase."
                ),
                locator=locator,
            )


__all__ = ["JacocoThresholdRule"]
