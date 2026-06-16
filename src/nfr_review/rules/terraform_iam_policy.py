# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: terraform-iam-policy — flags wildcard IAM policy actions/resources."""

from __future__ import annotations

import re
from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding

_IAM_RESOURCE_PREFIXES = ("aws_iam_", "azurerm_role_")
_IAM_DATA_TYPES = frozenset({"aws_iam_policy_document"})

_WILDCARD_PATTERNS = [
    re.compile(r'"Action"\s*:\s*\[?\s*"\*"', re.IGNORECASE),
    re.compile(r'"Resource"\s*:\s*"\*"', re.IGNORECASE),
    re.compile(r'actions\s*=\s*\[\s*"\*"'),
    re.compile(r'resources\s*=\s*\[?\s*"\*"'),
    re.compile(r'effect\s*=\s*"Allow"', re.IGNORECASE),
]

_WILDCARD_ACTION_RE = re.compile(
    r'("Action"\s*:\s*\[?\s*"\*"|actions\s*=\s*\[\s*"\*")', re.IGNORECASE
)
_WILDCARD_RESOURCE_RE = re.compile(
    r'("Resource"\s*:\s*"\*"|resources\s*=\s*\[?\s*"\*")', re.IGNORECASE
)


def _is_iam_resource(res_type: str) -> bool:
    return any(res_type.startswith(prefix) for prefix in _IAM_RESOURCE_PREFIXES)


def _is_iam_data(data_type: str) -> bool:
    return data_type in _IAM_DATA_TYPES


def _scan_body_for_wildcards(
    body_text: str,
    block_kind: str,
    block_type: str,
    block_name: str,
    file_path: str,
    ev: Evidence,
) -> list[Finding]:
    findings: list[Finding] = []
    if _WILDCARD_ACTION_RE.search(body_text):
        findings.append(
            Finding(
                rule_id="terraform-iam-policy",
                rag="amber",
                severity="high",
                summary=(
                    f"Wildcard Action ('*') in {block_kind} {block_type}.{block_name}"
                    f" ({file_path})."
                ),
                recommendation=(
                    "Replace wildcard Actions with specific permissions"
                    " following the principle of least privilege."
                ),
                evidence_locator=f"{file_path}:{block_type}.{block_name}",
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.9,
                pattern_tag="terraform-iam-policy",
            )
        )
    if _WILDCARD_RESOURCE_RE.search(body_text):
        findings.append(
            Finding(
                rule_id="terraform-iam-policy",
                rag="amber",
                severity="high",
                summary=(
                    f"Wildcard Resource ('*') in {block_kind} {block_type}.{block_name}"
                    f" ({file_path})."
                ),
                recommendation=(
                    "Scope Resource ARNs to specific resources instead of"
                    " using '*' to limit blast radius."
                ),
                evidence_locator=f"{file_path}:{block_type}.{block_name}",
                collector_name=ev.collector_name,
                collector_version=ev.collector_version,
                confidence=0.9,
                pattern_tag="terraform-iam-policy",
            )
        )
    return findings


class TerraformIamPolicyRule:
    """Flag IAM policies with wildcard actions or resources."""

    id = "terraform-iam-policy"
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

        findings: list[Finding] = []
        found_iam = False

        for ev in tf_evidence:
            file_path = ev.payload.file_path

            for rb in ev.payload.resource_blocks:
                res_type = rb.get("type", "")
                if not _is_iam_resource(res_type):
                    continue
                found_iam = True
                findings.extend(
                    _scan_body_for_wildcards(
                        rb.get("body_text", ""),
                        "resource",
                        res_type,
                        rb.get("name", ""),
                        file_path,
                        ev,
                    )
                )

            for db in ev.payload.data_blocks:
                data_type = db.get("type", "")
                if not _is_iam_data(data_type):
                    continue
                found_iam = True
                findings.extend(
                    _scan_body_for_wildcards(
                        db.get("body_text", ""),
                        "data",
                        data_type,
                        db.get("name", ""),
                        file_path,
                        ev,
                    )
                )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "terraform-iam-policy",
                    tf_evidence[0],
                    summary=(
                        "No wildcard IAM policies detected."
                        if found_iam
                        else "No IAM resources found in Terraform files."
                    ),
                    evidence_locator="all-tf-files",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "terraform-iam-policy" not in rule_registry:
        rule_registry.register("terraform-iam-policy", TerraformIamPolicyRule())


_register()

__all__ = ["TerraformIamPolicyRule"]
