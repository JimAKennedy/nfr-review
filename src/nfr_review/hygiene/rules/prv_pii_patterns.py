# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-PRV-001: PII pattern detection in source files."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band
from nfr_review.rules.rule_helpers import make_green_finding

_HIGH_RISK_TYPES = frozenset({"ssn", "credit_card"})
_MEDIUM_RISK_TYPES = frozenset({"email", "phone"})


class PiiPatternsRule:
    id = "HYG-PRV-001"
    band: Band = 1
    required_collectors: list[str] = ["privacy"]
    category = "privacy"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "privacy-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no privacy-analysis evidence available",
            )

        matches = ev.payload.get("pii_matches", [])
        high_risk = [m for m in matches if m.get("pattern_type") in _HIGH_RISK_TYPES]
        medium_risk = [m for m in matches if m.get("pattern_type") in _MEDIUM_RISK_TYPES]

        findings: list[Finding] = []

        if high_risk:
            rag: RAG = "red"
            severity: Severity = "high"
            types = sorted({m["pattern_type"] for m in high_risk})
            summary = (
                f"Found {len(high_risk)} high-risk PII pattern(s) "
                f"({', '.join(types)}) in source files."
            )
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag=rag,
                    severity=severity,
                    summary=summary,
                    recommendation=(
                        "Remove or externalize sensitive data. "
                        "Never commit SSNs or credit card numbers."
                    ),
                    evidence_locator=high_risk[0]["file"],
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.7,
                    pattern_tag="pii-high-risk",
                )
            )

        if medium_risk:
            rag = "amber"
            severity = "medium"
            types = sorted({m["pattern_type"] for m in medium_risk})
            summary = (
                f"Found {len(medium_risk)} medium-risk PII pattern(s) "
                f"({', '.join(types)}) in source files."
            )
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag=rag,
                    severity=severity,
                    summary=summary,
                    recommendation=(
                        "Review flagged patterns. Move real PII to "
                        "secure storage or environment variables."
                    ),
                    evidence_locator=medium_risk[0]["file"],
                    collector_name=ev.collector_name,
                    collector_version=ev.collector_version,
                    confidence=0.7,
                    pattern_tag="pii-medium-risk",
                )
            )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "pii-clean",
                    ev,
                    summary="No PII patterns detected in source files.",
                    evidence_locator=ev.locator,
                    confidence=0.7,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "HYG-PRV-001" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-PRV-001", PiiPatternsRule())


_register()

__all__ = ["PiiPatternsRule"]
