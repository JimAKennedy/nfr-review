# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: apim-hardcoded-backend-url -- checks APIM policies for hardcoded backend URLs."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_NAMED_VALUE_RE = re.compile(r"\{\{.+?\}\}")


class ApimHardcodedBackendUrlRule:
    """Flag when APIM policies use hardcoded backend URLs instead of named values."""

    id = "apim-hardcoded-backend-url"
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
            backend_urls = ev.payload.get("backend_urls", [])

            if not backend_urls:
                # No backend URLs to check -- skip this file
                continue

            hardcoded = [url for url in backend_urls if not _NAMED_VALUE_RE.search(url)]

            if hardcoded:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=(
                            f"Hardcoded backend URL(s): {', '.join(hardcoded)}."
                            " Environment-specific values should use named values."
                        ),
                        recommendation=(
                            "Replace hardcoded backend URLs with named values"
                            " (e.g. {{backend-url}}) to support environment"
                            " promotion and avoid secrets in source control."
                        ),
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="apim-backend-url",
                    )
                )
            else:
                findings.append(
                    make_green_finding(
                        self.id,
                        "apim-backend-url",
                        ev,
                        summary="All backend URLs use named values.",
                        confidence=0.9,
                        recommendation="No action required -- named values are used.",
                        evidence_locator=file_path,
                    )
                )

        if not findings:
            first = apim_evidence[0]
            findings.append(
                make_green_finding(
                    self.id,
                    "apim-backend-url",
                    first,
                    summary="No backend URLs found in any APIM policy.",
                    confidence=0.9,
                    evidence_locator="all-policies",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "apim-hardcoded-backend-url" not in rule_registry:
        rule_registry.register("apim-hardcoded-backend-url", ApimHardcodedBackendUrlRule())


_register()

__all__ = ["ApimHardcodedBackendUrlRule"]
