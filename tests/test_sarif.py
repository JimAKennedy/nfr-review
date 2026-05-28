# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for SARIF 2.1.0 output format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nfr_review.engine import RunResult
from nfr_review.models import Finding, RuleResult, RunMetadata
from nfr_review.output._errors import OutputError
from nfr_review.output.sarif import write_sarif


def _make_finding(**overrides) -> Finding:
    defaults = {
        "rule_id": "TEST-001",
        "rag": "red",
        "severity": "high",
        "summary": "test finding",
        "recommendation": "fix it",
        "evidence_locator": "file://src/main.py:10:5",
        "collector_name": "test-collector",
        "collector_version": "0.1.0",
        "confidence": 0.9,
        "pattern_tag": "test-pattern",
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _make_result(
    findings: list[Finding] | None = None,
    skipped_rules: list[RuleResult] | None = None,
    run_metadata: RunMetadata | None = None,
) -> RunResult:
    if run_metadata is None:
        run_metadata = RunMetadata(
            tool_version="0.1.0",
            target_repo="/tmp/test-repo",
            timestamp="2026-01-01T00:00:00Z",
            rules_run=["TEST-001"],
        )
    return RunResult(
        findings=findings or [],
        rule_results=skipped_rules or [],
        run_metadata=run_metadata,
    )


class TestSarifStructure:
    """Test that write_sarif produces valid top-level SARIF structure."""

    def test_sarif_structure(self, tmp_path: Path) -> None:
        result = _make_result(findings=[_make_finding()])
        out = tmp_path / "out.sarif.json"
        write_sarif(result, out)

        sarif = json.loads(out.read_text(encoding="utf-8"))
        assert sarif["version"] == "2.1.0"
        assert "$schema" in sarif
        assert "sarif-schema-2.1.0" in sarif["$schema"]
        assert len(sarif["runs"]) == 1

        run = sarif["runs"][0]
        assert run["tool"]["driver"]["name"] == "nfr-review"
        assert run["tool"]["driver"]["version"] == "0.1.0"
        assert isinstance(run["tool"]["driver"]["rules"], list)
        assert isinstance(run["results"], list)


class TestSeverityMapping:
    """Test severity to SARIF level mapping."""

    @pytest.mark.parametrize(
        ("severity", "expected_level"),
        [
            ("critical", "error"),
            ("high", "error"),
            ("medium", "warning"),
            ("low", "note"),
            ("info", "note"),
        ],
    )
    def test_sarif_severity_mapping(
        self, tmp_path: Path, severity: str, expected_level: str
    ) -> None:
        finding = _make_finding(severity=severity)
        result = _make_result(findings=[finding])
        out = tmp_path / "out.sarif.json"
        write_sarif(result, out)

        sarif = json.loads(out.read_text(encoding="utf-8"))
        assert sarif["runs"][0]["results"][0]["level"] == expected_level


class TestEvidenceLocatorParsing:
    """Test evidence_locator parsing into SARIF locations."""

    def test_file_with_line_and_col(self, tmp_path: Path) -> None:
        finding = _make_finding(evidence_locator="file://src/main.py:10:5")
        result = _make_result(findings=[finding])
        out = tmp_path / "out.sarif.json"
        write_sarif(result, out)

        sarif = json.loads(out.read_text(encoding="utf-8"))
        loc = sarif["runs"][0]["results"][0]["locations"][0]
        assert "physicalLocation" in loc
        phys = loc["physicalLocation"]
        assert phys["artifactLocation"]["uri"] == "src/main.py"
        assert phys["region"]["startLine"] == 10
        assert phys["region"]["startColumn"] == 5

    def test_file_with_line_only(self, tmp_path: Path) -> None:
        finding = _make_finding(evidence_locator="file://src/main.py:42")
        result = _make_result(findings=[finding])
        out = tmp_path / "out.sarif.json"
        write_sarif(result, out)

        sarif = json.loads(out.read_text(encoding="utf-8"))
        loc = sarif["runs"][0]["results"][0]["locations"][0]
        phys = loc["physicalLocation"]
        assert phys["artifactLocation"]["uri"] == "src/main.py"
        assert phys["region"]["startLine"] == 42
        assert "startColumn" not in phys["region"]

    def test_file_without_region(self, tmp_path: Path) -> None:
        finding = _make_finding(evidence_locator="file://src/main.py")
        result = _make_result(findings=[finding])
        out = tmp_path / "out.sarif.json"
        write_sarif(result, out)

        sarif = json.loads(out.read_text(encoding="utf-8"))
        loc = sarif["runs"][0]["results"][0]["locations"][0]
        phys = loc["physicalLocation"]
        assert phys["artifactLocation"]["uri"] == "src/main.py"
        assert "region" not in phys

    def test_logical_location_fallback(self, tmp_path: Path) -> None:
        finding = _make_finding(evidence_locator="maven:org.example:foo:1.0")
        result = _make_result(findings=[finding])
        out = tmp_path / "out.sarif.json"
        write_sarif(result, out)

        sarif = json.loads(out.read_text(encoding="utf-8"))
        loc = sarif["runs"][0]["results"][0]["locations"][0]
        assert "physicalLocation" in loc
        assert (
            loc["physicalLocation"]["artifactLocation"]["uri"] == "maven:org.example:foo:1.0"
        )


class TestSkippedRules:
    """Test that skipped rules produce notApplicable results with suppressions."""

    def test_sarif_skipped_rules(self, tmp_path: Path) -> None:
        skipped = [
            RuleResult(
                rule_id="SKIP-001",
                skipped=True,
                skip_reason="no Java detected",
            )
        ]
        result = _make_result(skipped_rules=skipped)
        out = tmp_path / "out.sarif.json"
        write_sarif(result, out)

        sarif = json.loads(out.read_text(encoding="utf-8"))
        results = sarif["runs"][0]["results"]
        assert len(results) == 1

        r = results[0]
        assert r["ruleId"] == "SKIP-001"
        assert r["kind"] == "notApplicable"
        assert r["level"] == "none"
        assert len(r["suppressions"]) == 1
        assert r["suppressions"][0]["kind"] == "inSource"
        assert r["suppressions"][0]["justification"] == "no Java detected"


class TestEmptyFindings:
    """Test no findings produces valid SARIF with empty results."""

    def test_sarif_empty_findings(self, tmp_path: Path) -> None:
        result = _make_result()
        out = tmp_path / "out.sarif.json"
        write_sarif(result, out)

        sarif = json.loads(out.read_text(encoding="utf-8"))
        assert sarif["runs"][0]["results"] == []
        assert sarif["runs"][0]["tool"]["driver"]["rules"] == []


class TestRunMetadataProperties:
    """Test RunMetadata goes into run.properties."""

    def test_sarif_run_metadata_properties(self, tmp_path: Path) -> None:
        metadata = RunMetadata(
            tool_version="1.2.3",
            target_repo="/home/user/my-repo",
            git_sha="abc123",
            git_branch="main",
            timestamp="2026-01-15T12:00:00Z",
            rules_run=["TEST-001"],
        )
        result = _make_result(
            findings=[_make_finding()],
            run_metadata=metadata,
        )
        out = tmp_path / "out.sarif.json"
        write_sarif(result, out)

        sarif = json.loads(out.read_text(encoding="utf-8"))
        props = sarif["runs"][0]["properties"]
        assert props["target_repo"] == "/home/user/my-repo"
        assert props["git_sha"] == "abc123"
        assert props["git_branch"] == "main"
        assert props["timestamp"] == "2026-01-15T12:00:00Z"


class TestRulesDeduplication:
    """Test multiple findings with same rule_id produce single rule entry."""

    def test_sarif_rules_deduplication(self, tmp_path: Path) -> None:
        findings = [
            _make_finding(rule_id="DUP-001", evidence_locator="file://a.py:1"),
            _make_finding(rule_id="DUP-001", evidence_locator="file://b.py:2"),
            _make_finding(rule_id="DUP-002", evidence_locator="file://c.py:3"),
        ]
        result = _make_result(findings=findings)
        out = tmp_path / "out.sarif.json"
        write_sarif(result, out)

        sarif = json.loads(out.read_text(encoding="utf-8"))
        rules = sarif["runs"][0]["tool"]["driver"]["rules"]
        assert len(rules) == 2
        rule_ids = [r["id"] for r in rules]
        assert "DUP-001" in rule_ids
        assert "DUP-002" in rule_ids

        # Verify ruleIndex references are correct
        results = sarif["runs"][0]["results"]
        for r in results:
            if r["ruleId"] == "DUP-001":
                assert r["ruleIndex"] == rule_ids.index("DUP-001")
            elif r["ruleId"] == "DUP-002":
                assert r["ruleIndex"] == rule_ids.index("DUP-002")


class TestCliFlag:
    """Test --sarif flag on the run command."""

    def test_sarif_cli_flag(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        import nfr_review.rules  # noqa: F401  # side-effect: register rules
        from nfr_review.cli import cli

        sarif_out = tmp_path / "output.sarif.json"
        fixture = Path(__file__).parent / "fixtures" / "ci-sample-repo"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                str(fixture),
                "--csv",
                str(tmp_path / "out.csv"),
                "--jsonl",
                str(tmp_path / "out.jsonl"),
                "--sarif",
                str(sarif_out),
            ],
        )

        # The command should succeed (exit 0 or 2 for threshold)
        assert result.exit_code in (0, 2), f"CLI failed: {result.output}"
        assert sarif_out.exists(), "SARIF file was not created"

        sarif = json.loads(sarif_out.read_text(encoding="utf-8"))
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"]) == 1


class TestOutputError:
    """Test that writing to invalid path raises OutputError."""

    def test_sarif_output_error(self) -> None:
        result = _make_result(findings=[_make_finding()])
        # Use a path inside a non-existent read-only location
        bad_path = Path("/dev/null/impossible/out.sarif.json")
        with pytest.raises(OutputError, match="failed to write SARIF"):
            write_sarif(result, bad_path)

    def test_sarif_none_metadata(self, tmp_path: Path) -> None:
        result = RunResult(findings=[], rule_results=[], run_metadata=None)
        out = tmp_path / "out.sarif.json"
        with pytest.raises(OutputError, match="run_metadata is None"):
            write_sarif(result, out)
