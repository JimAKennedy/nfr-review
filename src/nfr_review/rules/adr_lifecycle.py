# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: adr-lifecycle-gap — checks ADRs have lifecycle status tracking."""

from __future__ import annotations

from typing import Any

from nfr_review.collectors.payloads.adr import AdrDocumentPayload
from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.rules.framework import register
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


@register
class AdrLifecycleGapRule:
    """Flag when ADRs exist but lack lifecycle status tracking."""

    id = "adr-lifecycle-gap"
    band: Band = 1
    required_collectors: list[str] = ["adr"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        adr_docs = filter_evidence(evidence, "adr", "adr-document")
        if not adr_docs:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no ADR evidence available",
            )

        with_status = [
            e
            for e in adr_docs
            if isinstance(e.payload, AdrDocumentPayload) and e.payload.status
        ]
        without_status = [
            e
            for e in adr_docs
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
                            f"{len(adr_docs)} ADR(s) found but none have status tracking."
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
                            f"{len(without_status)} of {len(adr_docs)} ADR(s)"
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
                    adr_docs[0],
                    summary=f"All {len(adr_docs)} ADR(s) have status tracking.",
                    confidence=0.9,
                    recommendation="No action required — ADR lifecycle is well-managed.",
                    evidence_locator="adr-summary",
                )
            ],
        )


__all__ = ["AdrLifecycleGapRule"]
