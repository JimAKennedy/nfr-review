# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: skaffold-build-config — checks Skaffold build configuration quality."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_EXPLICIT_TAG_POLICIES = frozenset(
    {
        "sha256",
        "envTemplate",
        "dateTime",
        "customTemplate",
        "inputDigest",
    }
)


class SkaffoldBuildConfigRule:
    """Flag Skaffold configs missing build sections or with weak tag policies."""

    id = "skaffold-build-config"
    band: Band = 1
    required_collectors: list[str] = ["skaffold"]
    required_tech: list[str] = ["skaffold"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        skaffold_evidence = [
            e
            for e in evidence
            if e.collector_name == "skaffold" and e.kind == "skaffold-analysis"
        ]
        if not skaffold_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no skaffold-analysis evidence available",
            )

        findings: list[Finding] = []

        for ev in skaffold_evidence:
            build = ev.payload.get("build", {})

            if not build or not build.get("artifacts"):
                findings.append(
                    Finding(
                        rule_id=self.id,
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
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="skaffold-build-config",
                    )
                )
                continue

            tag_policy = build.get("tagPolicy", {}) or {}
            has_explicit_policy = any(key in tag_policy for key in _EXPLICIT_TAG_POLICIES)

            if "gitCommit" in tag_policy and not has_explicit_policy:
                findings.append(
                    Finding(
                        rule_id=self.id,
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
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="skaffold-build-config",
                    )
                )
            elif not tag_policy or (not has_explicit_policy and "gitCommit" not in tag_policy):
                findings.append(
                    Finding(
                        rule_id=self.id,
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
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.8,
                        pattern_tag="skaffold-build-config",
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(
                            "Skaffold build config uses an explicit tag policy"
                            " for reproducible image tagging."
                        ),
                        recommendation="No action required.",
                        evidence_locator=ev.locator,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="skaffold-build-config",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "skaffold-build-config" not in rule_registry:
        rule_registry.register("skaffold-build-config", SkaffoldBuildConfigRule())


_register()

__all__ = ["SkaffoldBuildConfigRule"]
