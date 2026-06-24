# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: terraform-state-backend -- flags repos with no remote state backend."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from nfr_review.collectors.payloads.terraform import TerraformAnalysisPayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit, make_finding


class TerraformStateBackendRule(FieldRule[TerraformAnalysisPayload]):
    """Flag Terraform repos that store state locally instead of using a remote backend."""

    id = "terraform-state-backend"
    collector_name = "terraform"
    evidence_kind = "terraform-analysis"
    payload_type = TerraformAnalysisPayload
    required_tech = ["terraform"]
    pattern_tag = "terraform-state-backend"
    default_confidence = 0.95
    all_clear_summary = "Remote state backend is configured."
    all_clear_recommendation = "No action required."

    def check(self, payload: TerraformAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        return ()

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
                skip_reason=f"no {self.evidence_kind} evidence available",
            )

        has_backend = any(
            tb.backend_type is not None
            for ev in relevant
            for tb in self._coerce(ev.payload).terraform_blocks
        )

        first = relevant[0]
        if has_backend:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    make_finding(
                        rule_id=self.id,
                        ev=first,
                        pattern_tag=self.pattern_tag,
                        default_confidence=self.default_confidence,
                        hit=Hit(
                            rag="green",
                            summary=self.all_clear_summary,
                            recommendation=self.all_clear_recommendation,
                            locator=first.locator,
                        ),
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_finding(
                    rule_id=self.id,
                    ev=first,
                    pattern_tag=self.pattern_tag,
                    default_confidence=self.default_confidence,
                    hit=Hit(
                        rag="red",
                        severity="high",
                        summary=(
                            "No remote state backend configured."
                            " All Terraform state is stored locally."
                        ),
                        recommendation=(
                            "Configure a remote backend (e.g. S3, GCS, Azure Blob)"
                            " in a terraform { backend ... } block to enable"
                            " team collaboration and state locking."
                        ),
                        locator="all-tf-files",
                    ),
                )
            ],
        )


__all__ = ["TerraformStateBackendRule"]
