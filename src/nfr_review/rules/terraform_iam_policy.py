# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: terraform-iam-policy -- flags wildcard IAM policy actions/resources."""

from __future__ import annotations

import re
from collections.abc import Iterable

from nfr_review.collectors.payloads.terraform import TerraformAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_IAM_RESOURCE_PREFIXES = ("aws_iam_", "azurerm_role_")
_IAM_DATA_TYPES = frozenset({"aws_iam_policy_document"})

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
) -> Iterable[Hit]:
    """Yield Hits for wildcard actions/resources in an IAM block body."""
    if _WILDCARD_ACTION_RE.search(body_text):
        yield Hit(
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
            locator=f"{file_path}:{block_type}.{block_name}",
        )
    if _WILDCARD_RESOURCE_RE.search(body_text):
        yield Hit(
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
            locator=f"{file_path}:{block_type}.{block_name}",
        )


class TerraformIamPolicyRule(FieldRule[TerraformAnalysisPayload]):
    """Flag IAM policies with wildcard actions or resources."""

    id = "terraform-iam-policy"
    collector_name = "terraform"
    evidence_kind = "terraform-analysis"
    payload_type = TerraformAnalysisPayload
    required_tech = ["terraform"]
    pattern_tag = "terraform-iam-policy"
    default_confidence = 0.9
    all_clear_summary = "No wildcard IAM policies detected."
    all_clear_recommendation = "No action required."

    def check(self, payload: TerraformAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        for rb in payload.resource_blocks:
            if not _is_iam_resource(rb.type):
                continue
            yield from _scan_body_for_wildcards(
                rb.body_text, "resource", rb.type, rb.name, payload.file_path
            )

        for db in payload.data_blocks:
            if not _is_iam_data(db.type):
                continue
            yield from _scan_body_for_wildcards(
                db.body_text, "data", db.type, db.name, payload.file_path
            )


__all__ = ["TerraformIamPolicyRule"]
