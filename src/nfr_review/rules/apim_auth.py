# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: apim-auth-policy-missing -- checks APIM policies for authentication."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class ApimAuthPolicyMissingRule:
    """Flag when no APIM policy has authentication configured."""

    id = "apim-auth-policy-missing"
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
            if ev.payload.get("has_auth_policy"):
                findings.append(
                    make_green_finding(
                        self.id,
                        "apim-auth-policy",
                        ev,
                        summary="Authentication policy is configured.",
                        confidence=0.95,
                        recommendation="No action required -- authentication is present.",
                        evidence_locator=file_path,
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="critical",
                        summary=(
                            "No authentication policy found. API endpoints are unprotected."
                        ),
                        recommendation=(
                            "Add a <validate-jwt> or"
                            " <authentication-managed-identity> policy to the"
                            " <inbound> section to enforce authentication."
                        ),
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="apim-auth-policy",
                    )
                )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "apim-auth-policy-missing" not in rule_registry:
        rule_registry.register("apim-auth-policy-missing", ApimAuthPolicyMissingRule())


_register()

__all__ = ["ApimAuthPolicyMissingRule"]
