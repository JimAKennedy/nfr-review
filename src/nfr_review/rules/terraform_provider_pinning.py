# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: terraform-provider-pinning -- flags providers without version constraints."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.terraform import TerraformAnalysisPayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class TerraformProviderPinningRule(FieldRule[TerraformAnalysisPayload]):
    """Flag Terraform providers that lack version constraints."""

    id = "terraform-provider-pinning"
    collector_name = "terraform"
    evidence_kind = "terraform-analysis"
    payload_type = TerraformAnalysisPayload
    required_tech = ["terraform"]
    pattern_tag = "terraform-provider-pinning"
    default_confidence = 0.9
    all_clear_summary = "All Terraform providers have version constraints."
    all_clear_recommendation = "No action required."

    def check(self, payload: TerraformAnalysisPayload, ev: Evidence) -> Iterable[Hit]:
        provider_versions: dict[str, str | None] = {}

        for pb in payload.provider_blocks:
            if not pb.name:
                continue
            if pb.name not in provider_versions or pb.version is not None:
                provider_versions[pb.name] = pb.version

        for tb in payload.terraform_blocks:
            for rp in tb.required_providers:
                if not rp.name:
                    continue
                if rp.name not in provider_versions or rp.version_constraint:
                    provider_versions[rp.name] = rp.version_constraint

        for name, version in sorted(provider_versions.items()):
            if not version:
                yield Hit(
                    rag="amber",
                    summary=(
                        f"Provider '{name}' has no version constraint."
                        " Upgrades may introduce breaking changes."
                    ),
                    recommendation=(
                        f"Pin provider '{name}' to a version range in"
                        ' required_providers (e.g. "~> 5.0") to prevent'
                        " unexpected breaking changes."
                    ),
                    locator=f"provider:{name}",
                )


__all__ = ["TerraformProviderPinningRule"]
