# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Terraform collector — parses .tf files using tree-sitter HCL and emits
per-file Evidence with structured payload for downstream NFR rules.

Evidence payload contract (kind="terraform-analysis"):
    file_path: str — path relative to repo_path
    terraform_blocks: list[dict] — each with:
        backend_type: str | None — backend type (e.g. "s3")
        required_version: str | None — required terraform version
        required_providers: list[dict] — each with name, source, version_constraint
    provider_blocks: list[dict] — each with:
        name: str — provider name (e.g. "aws")
        version: str | None — inline version constraint
        alias: str | None — provider alias
        line: int — 1-based line number
    resource_blocks: list[dict] — each with:
        type: str — resource type (e.g. "aws_instance")
        name: str — resource name
        body_text: str — full body text
        line: int — 1-based line number
    data_blocks: list[dict] — each with:
        type: str — data source type
        name: str — data source name
        body_text: str — full body text
        line: int — 1-based line number
    variable_blocks: list[dict] — each with:
        name: str — variable name
        has_description: bool
        has_type: bool
        has_default: bool
    module_blocks: list[dict] — each with:
        name: str — module name
        source: str | None — module source
        version: str | None — module version
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node

from nfr_review.collectors.ast_common import BaseASTCollector, find_nodes, text
from nfr_review.collectors.payloads.terraform import (
    TerraformAnalysisPayload,
    TerraformBlock,
    TerraformDataBlock,
    TerraformModuleBlock,
    TerraformProviderBlock,
    TerraformRequiredProvider,
    TerraformResourceBlock,
    TerraformVariableBlock,
)
from nfr_review.registry import collector_registry

logger = logging.getLogger("nfr_review.collectors.terraform")


def _get_string_labels(block: Node, source: bytes) -> list[str]:
    """Extract string_lit label values from a block node."""
    labels: list[str] = []
    for child in block.children:
        if child.type == "string_lit":
            for sub in child.children:
                if sub.type == "template_literal":
                    labels.append(text(sub, source))
    return labels


def _get_block_type(block: Node, source: bytes) -> str:
    """Get the identifier (block type) from a block node."""
    for child in block.children:
        if child.type == "identifier":
            return text(child, source)
    return ""


def _get_body(block: Node) -> Node | None:
    """Get the body node from a block."""
    for child in block.children:
        if child.type == "body":
            return child
    return None


def _get_attr_value(body: Node, attr_name: str, source: bytes) -> str | None:
    """Extract a string attribute value from a body node."""
    for child in body.children:
        if child.type == "attribute":
            ident = None
            for sub in child.children:
                if sub.type == "identifier":
                    ident = text(sub, source)
                    break
            if ident == attr_name:
                for tl in find_nodes(child, "template_literal"):
                    return text(tl, source)
                for ve in find_nodes(child, "variable_expr"):
                    for id_node in ve.children:
                        if id_node.type == "identifier":
                            return text(id_node, source)
    return None


def _has_attr(body: Node, attr_name: str, source: bytes) -> bool:
    """Check if a body node has an attribute with the given name."""
    for child in body.children:
        if child.type == "attribute":
            for sub in child.children:
                if sub.type == "identifier" and text(sub, source) == attr_name:
                    return True
    return False


def _extract_terraform_blocks(
    root: Node,
    source: bytes,
) -> list[TerraformBlock]:
    blocks: list[TerraformBlock] = []
    for block in find_nodes(root, "block"):
        if _get_block_type(block, source) != "terraform":
            continue

        body = _get_body(block)
        if body is None:
            continue

        backend_type: str | None = None
        required_version = _get_attr_value(body, "required_version", source)
        required_providers: list[TerraformRequiredProvider] = []

        for sub_block in body.children:
            if sub_block.type != "block":
                continue
            sub_type = _get_block_type(sub_block, source)

            if sub_type == "backend":
                labels = _get_string_labels(sub_block, source)
                backend_type = labels[0] if labels else None

            elif sub_type == "required_providers":
                sub_body = _get_body(sub_block)
                if sub_body is None:
                    continue
                for attr in sub_body.children:
                    if attr.type != "attribute":
                        continue
                    prov_name = ""
                    for c in attr.children:
                        if c.type == "identifier":
                            prov_name = text(c, source)
                            break
                    prov_source: str | None = None
                    prov_version: str | None = None
                    for obj_elem in find_nodes(attr, "object_elem"):
                        key_node = None
                        val_node = None
                        for c in obj_elem.children:
                            if c.type == "expression":
                                if key_node is None:
                                    key_node = c
                                else:
                                    val_node = c
                        if key_node is not None and val_node is not None:
                            key_text = ""
                            for id_n in find_nodes(key_node, "identifier"):
                                key_text = text(id_n, source)
                                break
                            val_text = ""
                            for tl in find_nodes(val_node, "template_literal"):
                                val_text = text(tl, source)
                                break
                            if key_text == "source":
                                prov_source = val_text
                            elif key_text == "version":
                                prov_version = val_text

                    required_providers.append(
                        TerraformRequiredProvider(
                            name=prov_name,
                            source=prov_source,
                            version_constraint=prov_version,
                        )
                    )

        blocks.append(
            TerraformBlock(
                backend_type=backend_type,
                required_version=required_version,
                required_providers=required_providers,
            )
        )
    return blocks


def _extract_provider_blocks(
    root: Node,
    source: bytes,
) -> list[TerraformProviderBlock]:
    providers: list[TerraformProviderBlock] = []
    for block in root.children:
        if block.type != "block":
            continue
        if _get_block_type(block, source) != "provider":
            continue

        labels = _get_string_labels(block, source)
        name = labels[0] if labels else ""
        body = _get_body(block)
        version: str | None = None
        alias: str | None = None
        if body is not None:
            version = _get_attr_value(body, "version", source)
            alias = _get_attr_value(body, "alias", source)

        providers.append(
            TerraformProviderBlock(
                name=name,
                version=version,
                alias=alias,
                line=block.start_point[0] + 1,
            )
        )
    return providers


def _extract_resource_blocks(
    root: Node,
    source: bytes,
) -> list[TerraformResourceBlock]:
    resources: list[TerraformResourceBlock] = []
    for block in root.children:
        if block.type != "block":
            continue
        if _get_block_type(block, source) != "resource":
            continue

        labels = _get_string_labels(block, source)
        res_type = labels[0] if len(labels) >= 1 else ""
        res_name = labels[1] if len(labels) >= 2 else ""
        body = _get_body(block)
        body_text = text(body, source) if body is not None else ""

        resources.append(
            TerraformResourceBlock(
                type=res_type,
                name=res_name,
                body_text=body_text,
                line=block.start_point[0] + 1,
            )
        )
    return resources


def _extract_data_blocks(
    root: Node,
    source: bytes,
) -> list[TerraformDataBlock]:
    data_blocks: list[TerraformDataBlock] = []
    for block in root.children:
        if block.type != "block":
            continue
        if _get_block_type(block, source) != "data":
            continue

        labels = _get_string_labels(block, source)
        data_type = labels[0] if len(labels) >= 1 else ""
        data_name = labels[1] if len(labels) >= 2 else ""
        body = _get_body(block)
        body_text = text(body, source) if body is not None else ""

        data_blocks.append(
            TerraformDataBlock(
                type=data_type,
                name=data_name,
                body_text=body_text,
                line=block.start_point[0] + 1,
            )
        )
    return data_blocks


def _extract_variable_blocks(
    root: Node,
    source: bytes,
) -> list[TerraformVariableBlock]:
    variables: list[TerraformVariableBlock] = []
    for block in root.children:
        if block.type != "block":
            continue
        if _get_block_type(block, source) != "variable":
            continue

        labels = _get_string_labels(block, source)
        name = labels[0] if labels else ""
        body = _get_body(block)
        has_description = False
        has_type = False
        has_default = False
        if body is not None:
            has_description = _has_attr(body, "description", source)
            has_type = _has_attr(body, "type", source)
            has_default = _has_attr(body, "default", source)

        variables.append(
            TerraformVariableBlock(
                name=name,
                has_description=has_description,
                has_type=has_type,
                has_default=has_default,
            )
        )
    return variables


def _extract_module_blocks(
    root: Node,
    source: bytes,
) -> list[TerraformModuleBlock]:
    modules: list[TerraformModuleBlock] = []
    for block in root.children:
        if block.type != "block":
            continue
        if _get_block_type(block, source) != "module":
            continue

        labels = _get_string_labels(block, source)
        name = labels[0] if labels else ""
        body = _get_body(block)
        mod_source: str | None = None
        mod_version: str | None = None
        if body is not None:
            mod_source = _get_attr_value(body, "source", source)
            mod_version = _get_attr_value(body, "version", source)

        modules.append(
            TerraformModuleBlock(
                name=name,
                source=mod_source,
                version=mod_version,
            )
        )
    return modules


class TerraformCollector(BaseASTCollector):
    name = "terraform"
    version = "0.1.0"
    language = "hcl"
    file_extensions = (".tf",)
    evidence_kind = "terraform-analysis"

    def _parse_file(self, source: bytes, rel_path: str) -> TerraformAnalysisPayload:
        assert self._parser is not None
        tree = self._parser.parse(source)
        root = tree.root_node

        body = _get_body(root)
        if body is None:
            body = root

        return TerraformAnalysisPayload(
            file_path=rel_path,
            terraform_blocks=_extract_terraform_blocks(body, source),
            provider_blocks=_extract_provider_blocks(body, source),
            resource_blocks=_extract_resource_blocks(body, source),
            data_blocks=_extract_data_blocks(body, source),
            variable_blocks=_extract_variable_blocks(body, source),
            module_blocks=_extract_module_blocks(body, source),
        )


def _register() -> None:
    if "terraform" not in collector_registry:
        collector_registry.register("terraform", TerraformCollector())


_register()

__all__ = ["TerraformCollector"]
