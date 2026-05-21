# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: ci-security-scan-missing — checks CI pipelines include security scanning."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class CiSecurityScanMissingRule:
    """Flag when CI pipelines exist but no security scan step is found."""

    id = "ci-security-scan-missing"
    band: Band = 1
    required_collectors: list[str] = ["ci-artifact"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ci_pipelines = [
            e
            for e in evidence
            if e.collector_name == "ci-artifact" and e.kind == "ci-pipeline"
        ]
        if not ci_pipelines:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no CI pipeline evidence available",
            )

        any_security = any(e.payload.get("has_security_scan") for e in ci_pipelines)

        if any_security:
            pipelines_with = [
                e.payload.get("file_path", e.locator)
                for e in ci_pipelines
                if e.payload.get("has_security_scan")
            ]
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="green",
                        severity="info",
                        summary=(
                            f"Security scanning found in: {', '.join(pipelines_with[:3])}"
                        ),
                        recommendation="No action required — security scanning is present.",
                        evidence_locator=pipelines_with[0],
                        collector_name="ci-artifact",
                        collector_version="0.1.0",
                        confidence=0.9,
                        pattern_tag="ci-security-scan",
                    )
                ],
            )

        pipeline_files = [e.payload.get("file_path", e.locator) for e in ci_pipelines]
        return RuleResult(
            rule_id=self.id,
            findings=[
                Finding(
                    rule_id=self.id,
                    rag="red",
                    severity="high",
                    summary=(
                        f"{len(ci_pipelines)} CI pipeline(s) found but none"
                        " include security scanning (SAST/DAST/SCA)."
                    ),
                    recommendation=(
                        "Add a security scan step (e.g., CodeQL, Snyk, Trivy)"
                        " to at least one CI pipeline."
                    ),
                    evidence_locator=pipeline_files[0],
                    collector_name="ci-artifact",
                    collector_version="0.1.0",
                    confidence=0.9,
                    pattern_tag="ci-security-scan",
                )
            ],
        )


def _register() -> None:
    if "ci-security-scan-missing" not in rule_registry:
        rule_registry.register("ci-security-scan-missing", CiSecurityScanMissingRule())


_register()

__all__ = ["CiSecurityScanMissingRule"]
