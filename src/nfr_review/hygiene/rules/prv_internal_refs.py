# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-PRV-002: Internal organization reference detection."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band


class InternalRefsRule:
    id = "HYG-PRV-002"
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

        refs = ev.payload.get("internal_references", [])

        if refs:
            types = sorted({m["pattern_type"] for m in refs})
            rag: RAG = "amber"
            severity: Severity = "medium"
            summary = (
                f"Found {len(refs)} internal reference(s) "
                f"({', '.join(types)}) in source files."
            )
            recommendation = (
                "Remove or replace internal domain names and IP addresses "
                "with configurable values or environment variables."
            )
            finding = Finding(
                rule_id=self.id,
                rag=rag,
                severity=severity,
                summary=summary,
                recommendation=recommendation,
                evidence_locator=refs[0]["file"],
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.8,
                pattern_tag="internal-refs-found",
            )
        else:
            finding = Finding(
                rule_id=self.id,
                rag="green",
                severity="info",
                summary="No internal organization references detected.",
                recommendation="No action required.",
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.8,
                pattern_tag="internal-refs-clean",
            )

        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-PRV-002" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-PRV-002", InternalRefsRule())


_register()

__all__ = ["InternalRefsRule"]
