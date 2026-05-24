# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: jacoco-threshold-missing — flags Java/Maven projects without JaCoCo plugin."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_JACOCO_GROUP = "org.jacoco"


class JacocoThresholdRule:
    """Flag Java projects that have no JaCoCo dependency/plugin configured."""

    id = "jacoco-threshold-missing"
    band: Band = 1
    required_collectors: list[str] = ["java-deps"]
    required_tech: list[str] = ["java"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        java_deps_evidence = [
            e for e in evidence if e.collector_name == "java-deps" and e.kind == "java-deps"
        ]
        if not java_deps_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no java-deps evidence available",
            )

        ev = java_deps_evidence[0]
        dependencies: list[dict[str, Any]] = ev.payload.get("dependencies", [])

        has_jacoco = any(
            dep.get("name", "").startswith(f"{_JACOCO_GROUP}:") for dep in dependencies
        )

        if has_jacoco:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary="JaCoCo plugin is present in Maven dependencies.",
                        recommendation=(
                            "No action required — JaCoCo coverage tooling is configured."
                        ),
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.85,
                        pattern_tag="jacoco-coverage",
                    )
                ],
            )

        manifest_files = ev.payload.get("manifest_files_found", [])
        locator = manifest_files[0] if manifest_files else ev.locator

        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
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
                    evidence_locator=locator,
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.85,
                    pattern_tag="jacoco-coverage",
                )
            ],
        )


def _register() -> None:
    if "jacoco-threshold-missing" not in rule_registry:
        rule_registry.register("jacoco-threshold-missing", JacocoThresholdRule())


_register()

__all__ = ["JacocoThresholdRule"]
