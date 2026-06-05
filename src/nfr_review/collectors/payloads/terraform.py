# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the terraform collector.

Mirrors the per-file evidence emitted by ``TerraformCollector`` including
terraform, provider, resource, data, variable, and module blocks.
"""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "TerraformAnalysisPayload",
    "TerraformBlock",
    "TerraformDataBlock",
    "TerraformModuleBlock",
    "TerraformProviderBlock",
    "TerraformRequiredProvider",
    "TerraformResourceBlock",
    "TerraformVariableBlock",
]


class TerraformRequiredProvider(BasePayload):
    name: str
    source: str | None = None
    version_constraint: str | None = None


class TerraformBlock(BasePayload):
    backend_type: str | None = None
    required_version: str | None = None
    required_providers: list[TerraformRequiredProvider]


class TerraformProviderBlock(BasePayload):
    name: str
    version: str | None = None
    alias: str | None = None
    line: int


class TerraformResourceBlock(BasePayload):
    type: str
    name: str
    body_text: str
    line: int


class TerraformDataBlock(BasePayload):
    type: str
    name: str
    body_text: str
    line: int


class TerraformVariableBlock(BasePayload):
    name: str
    has_description: bool
    has_type: bool
    has_default: bool


class TerraformModuleBlock(BasePayload):
    name: str
    source: str | None = None
    version: str | None = None


class TerraformAnalysisPayload(BasePayload):
    file_path: str
    terraform_blocks: list[TerraformBlock]
    provider_blocks: list[TerraformProviderBlock]
    resource_blocks: list[TerraformResourceBlock]
    data_blocks: list[TerraformDataBlock]
    variable_blocks: list[TerraformVariableBlock]
    module_blocks: list[TerraformModuleBlock]
