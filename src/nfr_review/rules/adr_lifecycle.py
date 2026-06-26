# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: adr-lifecycle-gap — checks ADRs have lifecycle status tracking."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.adr import AdrDocumentPayload
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.rules.framework import FieldRule
from nfr_review.rules.rule_helpers import make_green_finding


class AdrLifecycleGapRule(FieldRule[AdrDocumentPayload]):
    id = "adr-lifecycle-gap"
    collector_name = "adr"
    evidence_kind = "adr-document"
    payload_type = AdrDocumentPayload
    pattern_tag = "adr-lifecycle"
    default_confidence = 0.9
    all_clear_summary = "All ADRs have status tracking."
    all_clear_recommendation = "No action required — ADR lifecycle is well-managed."

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        relevant = [
            e
            for e in evidence
            if e.collector_name == self.collector_name and e.kind == self.evidence_kind
        ]
        if not relevant:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no ADR evidence available",
            )

        with_status = [
            e
            for e in relevant
            if isinstance(e.payload, AdrDocumentPayload) and e.payload.status
        ]
        without_status = [
            e
            for e in relevant
            if isinstance(e.payload, AdrDocumentPayload) and not e.payload.status
        ]

        if not with_status:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="medium",
                        summary=(
                            f"{len(relevant)} ADR(s) found but none have status tracking."
                        ),
                        recommendation=(
                            "Add a status field (accepted/deprecated/superseded)"
                            " to each ADR to enable lifecycle tracking."
                        ),
                        evidence_locator="adr-summary",
                        collector_name="adr",
                        collector_version="0.1.0",
                        confidence=0.9,
                        pattern_tag="adr-lifecycle",
                    )
                ],
            )

        if without_status:
            missing_files = ", ".join(
                (
                    e.payload.file_path
                    if isinstance(e.payload, AdrDocumentPayload)
                    else e.locator
                )
                for e in without_status[:3]
            )
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="low",
                        summary=(
                            f"{len(without_status)} of {len(relevant)} ADR(s)"
                            f" lack status fields: {missing_files}"
                        ),
                        recommendation=(
                            "Add status tracking to all ADRs for consistent"
                            " lifecycle management."
                        ),
                        evidence_locator="adr-summary",
                        collector_name="adr",
                        collector_version="0.1.0",
                        confidence=0.85,
                        pattern_tag="adr-lifecycle",
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_green_finding(
                    self.id,
                    "adr-lifecycle",
                    relevant[0],
                    summary=f"All {len(relevant)} ADR(s) have status tracking.",
                    confidence=0.9,
                    recommendation="No action required — ADR lifecycle is well-managed.",
                    evidence_locator="adr-summary",
                )
            ],
        )


__all__ = ["AdrLifecycleGapRule"]
