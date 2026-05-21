# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""HYG-PRV-003: Hardcoded tracking/analytics ID detection."""

from __future__ import annotations

from typing import Any

from nfr_review.hygiene import hygiene_rule_registry
from nfr_review.models import RAG, Evidence, Finding, RuleResult, Severity
from nfr_review.protocols import Band


class TrackingIdsRule:
    id = "HYG-PRV-003"
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

        ids = ev.payload.get("tracking_ids", [])

        if ids:
            types = sorted({m["pattern_type"] for m in ids})
            rag: RAG = "amber"
            severity: Severity = "medium"
            summary = (
                f"Found {len(ids)} hardcoded tracking/analytics ID(s) "
                f"({', '.join(types)}) in source files."
            )
            recommendation = (
                "Load tracking and analytics IDs from environment variables "
                "or configuration files rather than hardcoding them."
            )
            finding = Finding(
                rule_id=self.id,
                rag=rag,
                severity=severity,
                summary=summary,
                recommendation=recommendation,
                evidence_locator=ids[0]["file"],
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.9,
                pattern_tag="tracking-ids-found",
            )
        else:
            finding = Finding(
                rule_id=self.id,
                rag="green",
                severity="info",
                summary="No hardcoded tracking or analytics IDs detected.",
                recommendation="No action required.",
                evidence_locator=ev.locator,
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.9,
                pattern_tag="tracking-ids-clean",
            )

        return RuleResult(rule_id=self.id, findings=[finding])


def _register() -> None:
    if "HYG-PRV-003" not in hygiene_rule_registry:
        hygiene_rule_registry.register("HYG-PRV-003", TrackingIdsRule())


_register()

__all__ = ["TrackingIdsRule"]
