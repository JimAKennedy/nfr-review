# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the compliance mapping module and --framework CLI filter."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.compliance_mapping import (
    FRAMEWORK_LABELS,
    FRAMEWORK_RULES,
    FRAMEWORK_SLUGS,
    frameworks_for_rule,
    rules_for_framework,
)


class TestComplianceMapping:
    def test_all_framework_slugs_present(self) -> None:
        assert set(FRAMEWORK_SLUGS) == {"soc2", "iso27001", "pci-dss", "nist-800-53"}

    def test_every_slug_has_label(self) -> None:
        for slug in FRAMEWORK_SLUGS:
            assert slug in FRAMEWORK_LABELS

    def test_every_slug_has_rule_set(self) -> None:
        for slug in FRAMEWORK_SLUGS:
            rules = FRAMEWORK_RULES[slug]
            assert isinstance(rules, frozenset)
            assert len(rules) >= 28

    def test_rules_for_framework_valid(self) -> None:
        rules = rules_for_framework("pci-dss")
        assert "probes-missing" in rules
        assert "ci-test-stage-missing" in rules

    def test_rules_for_framework_invalid_raises(self) -> None:
        with pytest.raises(KeyError):
            rules_for_framework("hipaa")

    def test_frameworks_for_mapped_rule(self) -> None:
        fws = frameworks_for_rule("probes-missing")
        assert set(fws) == set(FRAMEWORK_SLUGS)

    def test_frameworks_for_unmapped_rule(self) -> None:
        fws = frameworks_for_rule("go-http-no-timeout")
        assert fws == []

    def test_mapping_includes_patch_rules(self) -> None:
        rules = rules_for_framework("soc2")
        patch_rules = {r for r in rules if r.startswith("PATCH-")}
        assert len(patch_rules) == 22

    def test_mapping_includes_hygiene_rules(self) -> None:
        rules = rules_for_framework("iso27001")
        hyg_rules = {r for r in rules if r.startswith("HYG-")}
        assert len(hyg_rules) == 28

    def test_mapping_includes_otel_rules_with_correct_ids(self) -> None:
        rules = rules_for_framework("nist-800-53")
        assert "otel-exporter-config" in rules
        assert "otel-pipeline-completeness" in rules
        assert "correlation-id-missing" in rules
        assert "otel-sampling" in rules


class TestFrameworkCLIFilter:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_run_help_shows_framework(self, runner: CliRunner) -> None:
        from nfr_review.cli import cli

        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "--framework" in result.output
        assert "pci-dss" in result.output

    def test_report_help_shows_framework(self, runner: CliRunner) -> None:
        from nfr_review.cli import cli

        result = runner.invoke(cli, ["report", "--help"])
        assert result.exit_code == 0
        assert "--framework" in result.output
        assert "soc2" in result.output

    def test_run_invalid_framework_rejected(self, runner: CliRunner) -> None:
        from nfr_review.cli import cli

        result = runner.invoke(cli, ["run", "--framework", "hipaa", "."])
        assert result.exit_code != 0

    def test_run_framework_filters_output(self, runner: CliRunner, tmp_path: Path) -> None:
        from nfr_review.cli import cli

        target = tmp_path / "repo"
        target.mkdir()
        result = runner.invoke(
            cli,
            [
                "run",
                str(target),
                "--framework",
                "pci-dss",
                "-q",
            ],
        )
        assert result.exit_code == 0

    def test_framework_filter_function(self) -> None:
        from nfr_review.cli import _apply_framework_filter
        from nfr_review.models import Finding

        findings = [
            Finding(
                rule_id="probes-missing",
                rag="red",
                severity="high",
                summary="No probes",
                recommendation="Add probes",
                evidence_locator="file://k8s/deploy.yaml:1",
                collector_name="k8s",
                collector_version="1.0",
                confidence=0.9,
                pattern_tag="probes",
            ),
            Finding(
                rule_id="go-http-no-timeout",
                rag="amber",
                severity="medium",
                summary="No timeout",
                recommendation="Add timeout",
                evidence_locator="file://main.go:10",
                collector_name="go-ast",
                collector_version="1.0",
                confidence=0.8,
                pattern_tag="timeout",
            ),
        ]
        filtered, excluded = _apply_framework_filter(findings, "soc2")
        assert len(filtered) == 1
        assert filtered[0].rule_id == "probes-missing"
        assert excluded == 1


class TestMarkdownFrameworkHeader:
    def test_markdown_report_includes_framework_label(self) -> None:
        from nfr_review.engine import RunResult
        from nfr_review.output.markdown import render_markdown_report

        result = RunResult(findings=[], rule_results=[], run_metadata=None, warnings=[])
        md = render_markdown_report(nfr_result=result, framework="pci-dss")
        assert "PCI DSS v4.0" in md
        assert "Compliance filter" in md or "compliance filter" in md.lower()

    def test_markdown_report_no_framework_no_label(self) -> None:
        from nfr_review.engine import RunResult
        from nfr_review.output.markdown import render_markdown_report

        result = RunResult(findings=[], rule_results=[], run_metadata=None, warnings=[])
        md = render_markdown_report(nfr_result=result)
        assert "Compliance filter" not in md
