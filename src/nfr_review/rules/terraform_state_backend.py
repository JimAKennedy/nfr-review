# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: terraform-state-backend — flags repos with no remote state backend."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class TerraformStateBackendRule:
    """Flag Terraform repos that store state locally instead of using a remote backend."""

    id = "terraform-state-backend"
    band: Band = 1
    required_collectors: list[str] = ["terraform"]
    required_tech: list[str] = ["terraform"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        tf_evidence = filter_evidence(evidence, "terraform", "terraform-analysis")
        if not tf_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no terraform-analysis evidence available",
            )

        has_backend = False
        for ev in tf_evidence:
            for tb in ev.payload.get("terraform_blocks", []):
                if tb.get("backend_type") is not None:
                    has_backend = True
                    break
            if has_backend:
                break

        first = tf_evidence[0]
        if not has_backend:
            return RuleResult(
                rule_id=self.id,
                findings=[
                    Finding(
                        rule_id=self.id,
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
                        evidence_locator="all-tf-files",
                        collector_name=first.collector_name,
                        collector_version=first.collector_version,
                        confidence=0.95,
                        pattern_tag="terraform-state-backend",
                    )
                ],
            )

        return RuleResult(
            rule_id=self.id,
            findings=[
                make_green_finding(
                    self.id,
                    "terraform-state-backend",
                    first,
                    summary="Remote state backend is configured.",
                    confidence=0.95,
                    evidence_locator="all-tf-files",
                )
            ],
        )


def _register() -> None:
    if "terraform-state-backend" not in rule_registry:
        rule_registry.register("terraform-state-backend", TerraformStateBackendRule())


_register()

__all__ = ["TerraformStateBackendRule"]
