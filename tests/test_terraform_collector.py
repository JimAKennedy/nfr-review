"""Tests for the TerraformCollector — tree-sitter HCL parsing, detection, and edge cases."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from nfr_review.collectors.terraform import TerraformCollector
from nfr_review.detect import ALL_TECH_KEYS
from nfr_review.models import Evidence
from nfr_review.registry import collector_registry

FIXTURES = Path(__file__).parent / "fixtures" / "terraform-sample-repo"
GOOD_FIXTURES = Path(__file__).parent / "fixtures" / "terraform-good-repo"


@pytest.fixture
def collector() -> TerraformCollector:
    return TerraformCollector()


def _payload(results: list[Evidence], locator_contains: str = "") -> dict[str, Any]:
    if locator_contains:
        for r in results:
            if locator_contains in r.locator:
                return r.payload
        pytest.fail(f"No evidence with locator containing {locator_contains!r}")
    assert len(results) >= 1
    return results[0].payload


class TestRegistration:
    def test_terraform_registered_in_collector_registry(self) -> None:
        import nfr_review.collectors.terraform

        importlib.reload(nfr_review.collectors.terraform)
        assert "terraform" in collector_registry


class TestDetection:
    def test_terraform_in_all_tech_keys(self) -> None:
        assert "terraform" in ALL_TECH_KEYS

    def test_all_tech_keys_count(self) -> None:
        assert len(ALL_TECH_KEYS) == 17


class TestCollectSampleRepo:
    def test_returns_evidence_list(self, collector: TerraformCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        assert isinstance(results, list)
        assert len(results) == 4  # main.tf, iam.tf, providers.tf, variables.tf

    def test_evidence_kind(self, collector: TerraformCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert ev.kind == "terraform-analysis"

    def test_collector_metadata(self, collector: TerraformCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert ev.collector_name == "terraform"
            assert ev.collector_version == "0.1.0"

    def test_resource_blocks_extracted(self, collector: TerraformCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results, "main.tf")
        resources = payload["resource_blocks"]
        assert len(resources) >= 2
        types = [r["type"] for r in resources]
        assert "aws_instance" in types
        assert "aws_s3_bucket" in types

    def test_resource_block_fields(self, collector: TerraformCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results, "main.tf")
        resource = next(r for r in payload["resource_blocks"] if r["type"] == "aws_instance")
        assert resource["name"] == "web"
        assert resource["line"] >= 1
        assert isinstance(resource["body_text"], str)
        assert len(resource["body_text"]) > 0

    def test_provider_blocks_extracted(self, collector: TerraformCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results, "providers.tf")
        providers = payload["provider_blocks"]
        assert len(providers) == 1
        assert providers[0]["name"] == "aws"
        assert providers[0]["version"] is None

    def test_terraform_blocks_extracted(self, collector: TerraformCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results, "providers.tf")
        tf_blocks = payload["terraform_blocks"]
        assert len(tf_blocks) == 1
        req_provs = tf_blocks[0]["required_providers"]
        assert len(req_provs) == 1
        assert req_provs[0]["name"] == "aws"
        assert req_provs[0]["source"] == "hashicorp/aws"
        assert req_provs[0]["version_constraint"] is None

    def test_variable_blocks_extracted(self, collector: TerraformCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results, "variables.tf")
        variables = payload["variable_blocks"]
        assert len(variables) == 2
        for var in variables:
            assert var["has_type"] is True
            assert var["has_description"] is True
            assert var["has_default"] is True

    def test_data_blocks_extracted(self, collector: TerraformCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results, "iam.tf")
        data_blocks = payload["data_blocks"]
        assert len(data_blocks) >= 1
        doc = next(d for d in data_blocks if d["type"] == "aws_iam_policy_document")
        assert doc["name"] == "wide_open"
        assert isinstance(doc["body_text"], str)

    def test_payload_contains_all_fields(self, collector: TerraformCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        payload = _payload(results, "main.tf")
        expected_keys = {
            "file_path",
            "terraform_blocks",
            "provider_blocks",
            "resource_blocks",
            "data_blocks",
            "variable_blocks",
            "module_blocks",
        }
        assert expected_keys.issubset(set(payload.keys()))

    def test_locator_is_relative(self, collector: TerraformCollector) -> None:
        results = collector.collect(FIXTURES, config=None)
        for ev in results:
            assert not ev.locator.startswith("/")


class TestCollectGoodRepo:
    def test_backend_detected(self, collector: TerraformCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        payload = _payload(results, "backend.tf")
        tf_blocks = payload["terraform_blocks"]
        assert len(tf_blocks) == 1
        assert tf_blocks[0]["backend_type"] == "s3"

    def test_provider_pinned(self, collector: TerraformCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        payload = _payload(results, "providers.tf")
        tf_blocks = payload["terraform_blocks"]
        assert len(tf_blocks) == 1
        req_provs = tf_blocks[0]["required_providers"]
        assert len(req_provs) == 1
        assert req_provs[0]["version_constraint"] == "~> 5.0"

    def test_required_version_parsed(self, collector: TerraformCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        payload = _payload(results, "providers.tf")
        tf_blocks = payload["terraform_blocks"]
        assert tf_blocks[0]["required_version"] == ">= 1.5.0"

    def test_least_privilege_iam(self, collector: TerraformCollector) -> None:
        results = collector.collect(GOOD_FIXTURES, config=None)
        payload = _payload(results, "iam.tf")
        data_blocks = payload["data_blocks"]
        assert len(data_blocks) >= 1
        doc = next(d for d in data_blocks if d["type"] == "aws_iam_policy_document")
        assert doc["name"] == "least_privilege"


class TestEdgeCases:
    def test_empty_directory_returns_empty(
        self, collector: TerraformCollector, tmp_path: Path
    ) -> None:
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_empty_tf_file(self, collector: TerraformCollector, tmp_path: Path) -> None:
        (tmp_path / "empty.tf").write_text("")
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        payload = results[0].payload
        assert payload["resource_blocks"] == []
        assert payload["provider_blocks"] == []
        assert payload["terraform_blocks"] == []
        assert payload["variable_blocks"] == []
        assert payload["data_blocks"] == []
        assert payload["module_blocks"] == []

    def test_malformed_tf_file_skipped(
        self, collector: TerraformCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "good.tf").write_text('resource "aws_instance" "x" {\n  ami = "abc"\n}\n')
        (tmp_path / "bad.tf").write_text("{{{invalid hcl ][[ }}}\n")
        results = collector.collect(tmp_path, config=None)
        assert len(results) >= 1

    def test_hidden_dirs_excluded(self, collector: TerraformCollector, tmp_path: Path) -> None:
        hidden = tmp_path / ".git" / "terraform"
        hidden.mkdir(parents=True)
        (hidden / "main.tf").write_text('resource "aws_instance" "x" { ami = "abc" }\n')
        visible = tmp_path / "infra"
        visible.mkdir()
        (visible / "main.tf").write_text('resource "aws_instance" "y" { ami = "def" }\n')
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        assert "infra" in results[0].locator

    def test_unreadable_file_skipped(
        self, collector: TerraformCollector, tmp_path: Path
    ) -> None:
        f = tmp_path / "secret.tf"
        f.write_text('resource "aws_instance" "x" { ami = "abc" }\n')
        f.chmod(0o000)
        try:
            results = collector.collect(tmp_path, config=None)
            assert results == []
        finally:
            f.chmod(0o644)

    def test_collector_name_and_version(self, collector: TerraformCollector) -> None:
        assert collector.name == "terraform"
        assert collector.version == "0.1.0"

    def test_no_tf_files_returns_empty(
        self, collector: TerraformCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "readme.md").write_text("# Readme\n")
        results = collector.collect(tmp_path, config=None)
        assert results == []

    def test_module_blocks_extracted(
        self, collector: TerraformCollector, tmp_path: Path
    ) -> None:
        (tmp_path / "modules.tf").write_text(
            'module "vpc" {\n'
            '  source  = "terraform-aws-modules/vpc/aws"\n'
            '  version = "5.0.0"\n'
            "}\n"
        )
        results = collector.collect(tmp_path, config=None)
        assert len(results) == 1
        modules = results[0].payload["module_blocks"]
        assert len(modules) == 1
        assert modules[0]["name"] == "vpc"
        assert modules[0]["source"] == "terraform-aws-modules/vpc/aws"
        assert modules[0]["version"] == "5.0.0"
