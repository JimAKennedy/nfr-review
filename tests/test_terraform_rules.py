"""Tests for Terraform NFR rules: state-backend, iam-policy, provider-pinning."""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from nfr_review.models import Evidence
from nfr_review.registry import rule_registry
from nfr_review.rules.terraform_iam_policy import TerraformIamPolicyRule
from nfr_review.rules.terraform_provider_pinning import TerraformProviderPinningRule
from nfr_review.rules.terraform_state_backend import TerraformStateBackendRule


def _make_evidence(
    *,
    file_path: str = "main.tf",
    terraform_blocks: list[dict[str, Any]] | None = None,
    provider_blocks: list[dict[str, Any]] | None = None,
    resource_blocks: list[dict[str, Any]] | None = None,
    data_blocks: list[dict[str, Any]] | None = None,
    variable_blocks: list[dict[str, Any]] | None = None,
    module_blocks: list[dict[str, Any]] | None = None,
) -> list[Evidence]:
    payload: dict[str, Any] = {
        "file_path": file_path,
        "terraform_blocks": terraform_blocks or [],
        "provider_blocks": provider_blocks or [],
        "resource_blocks": resource_blocks or [],
        "data_blocks": data_blocks or [],
        "variable_blocks": variable_blocks or [],
        "module_blocks": module_blocks or [],
    }
    return [
        Evidence(
            collector_name="terraform",
            collector_version="0.1.0",
            locator=file_path,
            kind="terraform-analysis",
            payload=payload,
        )
    ]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_state_backend_registered(self) -> None:
        import nfr_review.rules.terraform_state_backend

        importlib.reload(nfr_review.rules.terraform_state_backend)
        assert "terraform-state-backend" in rule_registry

    def test_iam_policy_registered(self) -> None:
        import nfr_review.rules.terraform_iam_policy

        importlib.reload(nfr_review.rules.terraform_iam_policy)
        assert "terraform-iam-policy" in rule_registry

    def test_provider_pinning_registered(self) -> None:
        import nfr_review.rules.terraform_provider_pinning

        importlib.reload(nfr_review.rules.terraform_provider_pinning)
        assert "terraform-provider-pinning" in rule_registry


# ---------------------------------------------------------------------------
# TerraformStateBackendRule
# ---------------------------------------------------------------------------


class TestTerraformStateBackendRule:
    @pytest.fixture()
    def rule(self) -> TerraformStateBackendRule:
        return TerraformStateBackendRule()

    def test_skip_no_evidence(self, rule: TerraformStateBackendRule) -> None:
        result = rule.evaluate([], None)
        assert result.skipped is True
        assert result.rule_id == "terraform-state-backend"

    def test_skip_wrong_collector(self, rule: TerraformStateBackendRule) -> None:
        ev = [
            Evidence(
                collector_name="other",
                collector_version="1.0",
                locator="x",
                kind="other",
                payload={},
            )
        ]
        result = rule.evaluate(ev, None)
        assert result.skipped is True

    def test_red_no_backend(self, rule: TerraformStateBackendRule) -> None:
        evidence = _make_evidence(terraform_blocks=[])
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "red"
        assert result.findings[0].severity == "high"
        assert "no remote state backend" in result.findings[0].summary.lower()

    def test_red_backend_type_none(self, rule: TerraformStateBackendRule) -> None:
        evidence = _make_evidence(
            terraform_blocks=[
                {
                    "backend_type": None,
                    "required_version": None,
                    "required_providers": [],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert result.findings[0].rag == "red"

    def test_green_with_backend(self, rule: TerraformStateBackendRule) -> None:
        evidence = _make_evidence(
            terraform_blocks=[
                {
                    "backend_type": "s3",
                    "required_version": ">= 1.0",
                    "required_providers": [],
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_finding_fields_match_r007(self, rule: TerraformStateBackendRule) -> None:
        evidence = _make_evidence(terraform_blocks=[])
        result = rule.evaluate(evidence, None)
        finding = result.findings[0]
        assert finding.rule_id == "terraform-state-backend"
        assert finding.pattern_tag == "terraform-state-backend"
        assert finding.collector_name == "terraform"
        assert 0.0 <= finding.confidence <= 1.0


# ---------------------------------------------------------------------------
# TerraformIamPolicyRule
# ---------------------------------------------------------------------------


class TestTerraformIamPolicyRule:
    @pytest.fixture()
    def rule(self) -> TerraformIamPolicyRule:
        return TerraformIamPolicyRule()

    def test_skip_no_evidence(self, rule: TerraformIamPolicyRule) -> None:
        result = rule.evaluate([], None)
        assert result.skipped is True
        assert result.rule_id == "terraform-iam-policy"

    def test_skip_wrong_collector(self, rule: TerraformIamPolicyRule) -> None:
        ev = [
            Evidence(
                collector_name="other",
                collector_version="1.0",
                locator="x",
                kind="other",
                payload={},
            )
        ]
        result = rule.evaluate(ev, None)
        assert result.skipped is True

    def test_amber_wildcard_action(self, rule: TerraformIamPolicyRule) -> None:
        evidence = _make_evidence(
            resource_blocks=[
                {
                    "type": "aws_iam_role_policy",
                    "name": "admin",
                    "body_text": """
                        policy = jsonencode({
                            Statement = [{
                                Effect   = "Allow"
                                "Action" : ["*"]
                                "Resource" : "arn:aws:s3:::my-bucket"
                            }]
                        })
                    """,
                    "line": 1,
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) >= 1
        assert any("wildcard action" in f.summary.lower() for f in amber)
        assert all(f.severity == "high" for f in amber)

    def test_amber_wildcard_resource(self, rule: TerraformIamPolicyRule) -> None:
        evidence = _make_evidence(
            data_blocks=[
                {
                    "type": "aws_iam_policy_document",
                    "name": "too_broad",
                    "body_text": """
                        statement {
                            effect    = "Allow"
                            actions   = ["s3:GetObject"]
                            "Resource": "*"
                        }
                    """,
                    "line": 1,
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) >= 1
        assert any("wildcard resource" in f.summary.lower() for f in amber)

    def test_amber_hcl_style_wildcard_action(self, rule: TerraformIamPolicyRule) -> None:
        evidence = _make_evidence(
            data_blocks=[
                {
                    "type": "aws_iam_policy_document",
                    "name": "wide_open",
                    "body_text": """
                        statement {
                            effect    = "Allow"
                            actions   = ["*"]
                            resources = ["arn:aws:s3:::*"]
                        }
                    """,
                    "line": 1,
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert any("wildcard action" in f.summary.lower() for f in amber)

    def test_green_specific_actions(self, rule: TerraformIamPolicyRule) -> None:
        evidence = _make_evidence(
            resource_blocks=[
                {
                    "type": "aws_iam_role_policy",
                    "name": "scoped",
                    "body_text": """
                        policy = jsonencode({
                            Statement = [{
                                Effect   = "Allow"
                                "Action" : ["s3:GetObject", "s3:PutObject"]
                                "Resource" : "arn:aws:s3:::my-bucket/*"
                            }]
                        })
                    """,
                    "line": 1,
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        green = [f for f in result.findings if f.rag == "green"]
        assert len(green) == 1

    def test_no_iam_resources_green(self, rule: TerraformIamPolicyRule) -> None:
        evidence = _make_evidence(
            resource_blocks=[
                {
                    "type": "aws_instance",
                    "name": "web",
                    "body_text": 'ami = "ami-123"\ninstance_type = "t3.micro"',
                    "line": 1,
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_azure_iam_wildcard(self, rule: TerraformIamPolicyRule) -> None:
        evidence = _make_evidence(
            resource_blocks=[
                {
                    "type": "azurerm_role_assignment",
                    "name": "admin",
                    "body_text": """
                        "Action" : "*"
                    """,
                    "line": 1,
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) >= 1

    def test_finding_fields_match_r007(self, rule: TerraformIamPolicyRule) -> None:
        evidence = _make_evidence(
            resource_blocks=[
                {
                    "type": "aws_iam_policy",
                    "name": "test",
                    "body_text": '"Action": ["*"]',
                    "line": 1,
                }
            ]
        )
        result = rule.evaluate(evidence, None)
        finding = result.findings[0]
        assert finding.rule_id == "terraform-iam-policy"
        assert finding.pattern_tag == "terraform-iam-policy"
        assert finding.collector_name == "terraform"
        assert 0.0 <= finding.confidence <= 1.0


# ---------------------------------------------------------------------------
# TerraformProviderPinningRule
# ---------------------------------------------------------------------------


class TestTerraformProviderPinningRule:
    @pytest.fixture()
    def rule(self) -> TerraformProviderPinningRule:
        return TerraformProviderPinningRule()

    def test_skip_no_evidence(self, rule: TerraformProviderPinningRule) -> None:
        result = rule.evaluate([], None)
        assert result.skipped is True
        assert result.rule_id == "terraform-provider-pinning"

    def test_skip_wrong_collector(self, rule: TerraformProviderPinningRule) -> None:
        ev = [
            Evidence(
                collector_name="other",
                collector_version="1.0",
                locator="x",
                kind="other",
                payload={},
            )
        ]
        result = rule.evaluate(ev, None)
        assert result.skipped is True

    def test_amber_unpinned_provider(self, rule: TerraformProviderPinningRule) -> None:
        evidence = _make_evidence(
            provider_blocks=[{"name": "aws", "version": None, "alias": None, "line": 1}]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert amber[0].severity == "medium"
        assert "aws" in amber[0].summary

    def test_green_all_pinned(self, rule: TerraformProviderPinningRule) -> None:
        evidence = _make_evidence(
            terraform_blocks=[
                {
                    "backend_type": None,
                    "required_version": None,
                    "required_providers": [
                        {
                            "name": "aws",
                            "source": "hashicorp/aws",
                            "version_constraint": "~> 5.0",
                        },
                        {
                            "name": "random",
                            "source": "hashicorp/random",
                            "version_constraint": ">= 3.0",
                        },
                    ],
                }
            ],
            provider_blocks=[{"name": "aws", "version": None, "alias": None, "line": 1}],
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_mixed_pinned_unpinned(self, rule: TerraformProviderPinningRule) -> None:
        evidence = _make_evidence(
            terraform_blocks=[
                {
                    "backend_type": None,
                    "required_version": None,
                    "required_providers": [
                        {
                            "name": "aws",
                            "source": "hashicorp/aws",
                            "version_constraint": "~> 5.0",
                        },
                    ],
                }
            ],
            provider_blocks=[
                {"name": "aws", "version": None, "alias": None, "line": 1},
                {"name": "random", "version": None, "alias": None, "line": 5},
            ],
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        amber = [f for f in result.findings if f.rag == "amber"]
        assert len(amber) == 1
        assert "random" in amber[0].summary
        assert not any("aws" in f.summary for f in amber)

    def test_inline_version_counts_as_pinned(self, rule: TerraformProviderPinningRule) -> None:
        evidence = _make_evidence(
            provider_blocks=[{"name": "aws", "version": "~> 5.0", "alias": None, "line": 1}]
        )
        result = rule.evaluate(evidence, None)
        assert not result.skipped
        assert len(result.findings) == 1
        assert result.findings[0].rag == "green"

    def test_finding_fields_match_r007(self, rule: TerraformProviderPinningRule) -> None:
        evidence = _make_evidence(
            provider_blocks=[{"name": "aws", "version": None, "alias": None, "line": 1}]
        )
        result = rule.evaluate(evidence, None)
        finding = result.findings[0]
        assert finding.rule_id == "terraform-provider-pinning"
        assert finding.pattern_tag == "terraform-provider-pinning"
        assert finding.collector_name == "terraform"
        assert 0.0 <= finding.confidence <= 1.0
