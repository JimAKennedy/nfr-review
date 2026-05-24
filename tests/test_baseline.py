# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for baseline loading, diff-mode filtering, and CLI --baseline flag."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.baseline import BaselineData, filter_new_findings, load_baseline
from nfr_review.cli import cli
from nfr_review.models import Finding


def _make_finding(
    rule_id: str = "R001",
    evidence_locator: str = "file.py:10",
    pattern_tag: str = "missing-readme",
    **kwargs,
) -> Finding:
    defaults = {
        "rule_id": rule_id,
        "rag": "amber",
        "severity": "medium",
        "summary": "Test finding",
        "recommendation": "Fix it",
        "evidence_locator": evidence_locator,
        "collector_name": "test-collector",
        "collector_version": "0.1.0",
        "confidence": 0.9,
        "pattern_tag": pattern_tag,
    }
    defaults.update(kwargs)
    return Finding(**defaults)


def _write_jsonl(path: Path, findings: list[Finding]) -> None:
    """Write a minimal JSONL file with run_metadata + findings."""
    with path.open("w", encoding="utf-8") as fh:
        metadata = {
            "record_type": "run_metadata",
            "tool_version": "0.1.0",
            "target_repo": "test-repo",
            "timestamp": "2026-01-01 00:00:00 UTC",
        }
        fh.write(json.dumps(metadata) + "\n")
        for f in findings:
            record = {"record_type": "finding", **f.model_dump()}
            fh.write(json.dumps(record) + "\n")


# ---- T01: Finding.identity_key -------------------------------------------


class TestIdentityKey:
    def test_returns_correct_tuple(self) -> None:
        f = _make_finding(
            rule_id="R007", evidence_locator="src/main.py:42", pattern_tag="no-tls"
        )
        assert f.identity_key == ("R007", "src/main.py:42", "no-tls")

    def test_consistent_across_calls(self) -> None:
        f = _make_finding()
        assert f.identity_key == f.identity_key

    def test_different_findings_different_keys(self) -> None:
        f1 = _make_finding(rule_id="R001")
        f2 = _make_finding(rule_id="R002")
        assert f1.identity_key != f2.identity_key


# ---- T01: load_baseline ---------------------------------------------------


class TestLoadBaseline:
    def test_parses_jsonl_file(self, tmp_path: Path) -> None:
        findings = [
            _make_finding(rule_id="R001", evidence_locator="a.py:1", pattern_tag="tag-a"),
            _make_finding(rule_id="R002", evidence_locator="b.py:2", pattern_tag="tag-b"),
        ]
        jsonl_path = tmp_path / "baseline.jsonl"
        _write_jsonl(jsonl_path, findings)

        baseline = load_baseline(jsonl_path)
        assert baseline.finding_count == 2
        assert ("R001", "a.py:1", "tag-a") in baseline.keys
        assert ("R002", "b.py:2", "tag-b") in baseline.keys
        assert baseline.run_metadata["record_type"] == "run_metadata"

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="baseline file not found"):
            load_baseline(tmp_path / "nonexistent.jsonl")

    def test_empty_file_returns_empty_baseline(self, tmp_path: Path) -> None:
        jsonl_path = tmp_path / "empty.jsonl"
        jsonl_path.write_text("")
        baseline = load_baseline(jsonl_path)
        assert baseline.finding_count == 0
        assert len(baseline.keys) == 0

    def test_skips_records_with_missing_fields(self, tmp_path: Path) -> None:
        jsonl_path = tmp_path / "partial.jsonl"
        with jsonl_path.open("w") as fh:
            # Valid metadata
            fh.write(json.dumps({"record_type": "run_metadata"}) + "\n")
            # Finding with missing rule_id — should be skipped
            fh.write(
                json.dumps(
                    {
                        "record_type": "finding",
                        "evidence_locator": "x.py:1",
                        "pattern_tag": "t",
                    }
                )
                + "\n"
            )
            # Valid finding
            fh.write(
                json.dumps(
                    {
                        "record_type": "finding",
                        "rule_id": "R001",
                        "evidence_locator": "y.py:2",
                        "pattern_tag": "u",
                    }
                )
                + "\n"
            )
        baseline = load_baseline(jsonl_path)
        assert baseline.finding_count == 1
        assert ("R001", "y.py:2", "u") in baseline.keys


# ---- T01: filter_new_findings ---------------------------------------------


class TestFilterNewFindings:
    def test_removes_known_findings(self) -> None:
        f_known = _make_finding(rule_id="R001", evidence_locator="a.py:1", pattern_tag="t1")
        f_new = _make_finding(rule_id="R002", evidence_locator="b.py:2", pattern_tag="t2")
        baseline = BaselineData(keys={f_known.identity_key}, finding_count=1)

        result = filter_new_findings([f_known, f_new], baseline)
        assert len(result) == 1
        assert result[0].rule_id == "R002"

    def test_keeps_all_when_baseline_empty(self) -> None:
        findings = [_make_finding(rule_id="R001"), _make_finding(rule_id="R002")]
        baseline = BaselineData()
        result = filter_new_findings(findings, baseline)
        assert len(result) == 2

    def test_removes_all_when_all_known(self) -> None:
        f1 = _make_finding(rule_id="R001", evidence_locator="a.py:1", pattern_tag="t1")
        f2 = _make_finding(rule_id="R002", evidence_locator="b.py:2", pattern_tag="t2")
        baseline = BaselineData(keys={f1.identity_key, f2.identity_key}, finding_count=2)
        result = filter_new_findings([f1, f2], baseline)
        assert len(result) == 0


# ---- T02/T03: CLI --baseline integration -----------------------------------


class TestCLIBaseline:
    def test_baseline_filters_known_findings_exit_0(self, tmp_path: Path) -> None:
        """When all findings match the baseline, exit 0 (no regressions)."""
        target = tmp_path / "repo"
        target.mkdir()
        # No README -> sample rule emits a finding

        # First run: generate JSONL baseline
        jsonl_first = tmp_path / "first.jsonl"
        csv_first = tmp_path / "first.csv"
        runner = CliRunner()
        result1 = runner.invoke(
            cli,
            [
                "run",
                str(target),
                "--csv",
                str(csv_first),
                "--jsonl",
                str(jsonl_first),
            ],
        )
        # Should produce findings (no README)
        assert jsonl_first.exists(), result1.stderr

        # Second run with --baseline pointing to first run
        csv_second = tmp_path / "second.csv"
        jsonl_second = tmp_path / "second.jsonl"
        result2 = runner.invoke(
            cli,
            [
                "run",
                str(target),
                "--csv",
                str(csv_second),
                "--jsonl",
                str(jsonl_second),
                "--baseline",
                str(jsonl_first),
            ],
        )
        assert result2.exit_code == 0, result2.stderr
        assert "Baseline loaded:" in result2.stderr
        assert "New findings: 0" in result2.stderr

    def test_baseline_new_regression_exits_1(self, tmp_path: Path) -> None:
        """When new findings appear that aren't in the baseline, exit 1."""
        target = tmp_path / "repo"
        target.mkdir()
        (target / "README.md").write_text("# OK\n")

        # Create a baseline with no findings (clean run)
        baseline_path = tmp_path / "baseline.jsonl"
        with baseline_path.open("w") as fh:
            fh.write(
                json.dumps(
                    {
                        "record_type": "run_metadata",
                        "tool_version": "0.1.0",
                        "target_repo": "test-repo",
                        "timestamp": "2026-01-01 00:00:00 UTC",
                    }
                )
                + "\n"
            )

        # Now remove README to create a regression
        (target / "README.md").unlink()

        csv_path = tmp_path / "out.csv"
        jsonl_path = tmp_path / "out.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                str(target),
                "--csv",
                str(csv_path),
                "--jsonl",
                str(jsonl_path),
                "--baseline",
                str(baseline_path),
            ],
        )
        assert result.exit_code == 1, result.stderr
        assert "New findings:" in result.stderr
        # The "New findings" count should be > 0
        assert "New findings: 0" not in result.stderr
