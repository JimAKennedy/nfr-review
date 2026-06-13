# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: apim-rate-limit-missing -- checks APIM policies for rate limiting."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class ApimRateLimitMissingRule:
    """Flag when no APIM policy has rate limiting configured in inbound section."""

    id = "apim-rate-limit-missing"
    band: Band = 1
    required_collectors: list[str] = ["apim-policy"]
    required_tech: list[str] = ["apim"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        apim_evidence = filter_evidence(evidence, "apim-policy", "apim-policy")
        if not apim_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no apim-policy evidence available",
            )

        findings: list[Finding] = []
        for ev in apim_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            if ev.payload.get("has_rate_limit"):
                findings.append(
                    make_green_finding(
                        self.id,
                        "apim-rate-limit",
                        ev,
                        summary="Rate limiting is configured.",
                        confidence=0.95,
                        recommendation="No action required -- rate limiting is present.",
                        evidence_locator=file_path,
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=(
                            "No rate limiting policy found."
                            " API is unprotected against request flooding."
                        ),
                        recommendation=(
                            "Add a <rate-limit> or <rate-limit-by-key> policy"
                            " to the <inbound> section to protect against"
                            " excessive traffic."
                        ),
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="apim-rate-limit",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "apim-rate-limit-missing" not in rule_registry:
        rule_registry.register("apim-rate-limit-missing", ApimRateLimitMissingRule())


_register()

__all__ = ["ApimRateLimitMissingRule"]
