# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-COM-004: SECURITY policy presence check."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band


class SecurityPresenceRule:
    id = "HYG-COM-004"
    band: Band = 1
    required_collectors: list[str] = ["community"]
    category = "community"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        ev = next((e for e in evidence if e.kind == "community-analysis"), None)
        if ev is None:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no community-analysis evidence available",
            )

        info = ev.payload.get("security", {})
        exists = info.get("exists", False)

        if exists:
            rag: RAG = "green"
            severity: Severity = "info"
            summary = f"Security policy found at {info.get('path')}."
            recommendation = "No action required."
        else:
            rag = "red"
            severity = "high"
            summary = "No SECURITY.md or SECURITY.txt found."
            recommendation = (
                "Add a security policy documenting how to report vulnerabilities responsibly."
            )

        finding = Finding(
            rule_id=self.id,
            rag=rag,
            severity=severity,
            summary=summary,
            recommendation=recommendation,
            evidence_locator=info.get("path") or ev.locator,
            collector_name=ev.collector_name,
            collector_version=ev.collector_version,
            confidence=1.0,
            pattern_tag="security-policy-presence",
        )
        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-COM-004" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-COM-004", SecurityPresenceRule())


_register()

__all__ = ["SecurityPresenceRule"]
