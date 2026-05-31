# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for baseline loading, diff-mode filtering, and CLI --baseline flag."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.baseline import (
    BaselineData,
    classify_findings,
    filter_new_findings,
    load_baseline,
)
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
        baseline = BaselineData(legacy_keys={f_known.identity_key}, finding_count=1)

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
        baseline = BaselineData(
            legacy_keys={f1.identity_key, f2.identity_key}, finding_count=2
        )
        result = filter_new_findings([f1, f2], baseline)
        assert len(result) == 0


# ---- Stable fingerprint: dual-key matching ---------------------------------


class TestStableBaselineDiffing:
    """Tests for content-hash-based baseline matching (line-shift-immune)."""

    def test_content_hash_loaded_from_jsonl(self, tmp_path: Path) -> None:
        findings = [
            _make_finding(
                rule_id="R001",
                evidence_locator="c.cpp:42",
                pattern_tag="raw-new",
                content_hash="abc123def456",
            )
        ]
        jsonl_path = tmp_path / "baseline.jsonl"
        _write_jsonl(jsonl_path, findings)
        baseline = load_baseline(jsonl_path)
        assert ("R001", "c.cpp", "raw-new", "abc123def456") in baseline.stable_keys
        assert ("R001", "c.cpp:42", "raw-new") in baseline.legacy_keys

    def test_line_shift_matched_via_stable_key(self) -> None:
        """Same content at different line numbers should match via stable key."""
        baseline = BaselineData(
            legacy_keys={("R001", "c.cpp:140", "raw-new")},
            stable_keys={("R001", "c.cpp", "raw-new", "abc123")},
            finding_count=1,
        )
        shifted = _make_finding(
            rule_id="R001",
            evidence_locator="c.cpp:142",
            pattern_tag="raw-new",
            content_hash="abc123",
        )
        result = filter_new_findings([shifted], baseline)
        assert len(result) == 0

    def test_legacy_fallback_when_no_content_hash(self) -> None:
        """Findings without content_hash still match via legacy key."""
        baseline = BaselineData(
            legacy_keys={("R001", "a.py:10", "tag")},
            finding_count=1,
        )
        f = _make_finding(rule_id="R001", evidence_locator="a.py:10", pattern_tag="tag")
        result = filter_new_findings([f], baseline)
        assert len(result) == 0

    def test_old_baseline_new_scan_with_content_hash(self) -> None:
        """Old baseline without content_hash, new scan with content_hash.
        Falls back to legacy key match.
        """
        baseline = BaselineData(
            legacy_keys={("R001", "c.cpp:140", "raw-new")},
            finding_count=1,
        )
        f = _make_finding(
            rule_id="R001",
            evidence_locator="c.cpp:140",
            pattern_tag="raw-new",
            content_hash="abc123",
        )
        result = filter_new_findings([f], baseline)
        assert len(result) == 0

    def test_old_baseline_line_shifted_is_new(self) -> None:
        """Old baseline without content_hash, line shifted — finding IS new
        (no stable key in baseline to match against).
        """
        baseline = BaselineData(
            legacy_keys={("R001", "c.cpp:140", "raw-new")},
            finding_count=1,
        )
        shifted = _make_finding(
            rule_id="R001",
            evidence_locator="c.cpp:142",
            pattern_tag="raw-new",
            content_hash="abc123",
        )
        result = filter_new_findings([shifted], baseline)
        assert len(result) == 1

    def test_truly_new_finding_not_suppressed(self) -> None:
        baseline = BaselineData(
            legacy_keys={("R001", "c.cpp:140", "raw-new")},
            stable_keys={("R001", "c.cpp", "raw-new", "abc123")},
            finding_count=1,
        )
        new_f = _make_finding(
            rule_id="R001",
            evidence_locator="c.cpp:200",
            pattern_tag="raw-new",
            content_hash="xyz789",
        )
        result = filter_new_findings([new_f], baseline)
        assert len(result) == 1

    def test_backward_compat_keys_alias(self) -> None:
        """The .keys property returns legacy_keys for backward compat."""
        baseline = BaselineData(
            legacy_keys={("R001", "a.py:10", "tag")},
            finding_count=1,
        )
        assert baseline.keys == baseline.legacy_keys


# ---- classify_findings -------------------------------------------------------


class TestClassifyFindings:
    def test_truly_new_finding(self) -> None:
        baseline = BaselineData(
            legacy_keys={("R001", "old.py:1", "tag")},
            stable_keys={("R001", "old.py", "tag", "aaa111")},
            finding_count=1,
        )
        new_f = _make_finding(
            rule_id="R002",
            evidence_locator="new.py:5",
            pattern_tag="other",
            content_hash="bbb222",
        )
        result = classify_findings([new_f], baseline)
        assert len(result.new) == 1
        assert result.new[0].rule_id == "R002"
        assert len(result.shifted) == 0

    def test_shifted_finding(self) -> None:
        """Same content_hash at a different line → shifted, not new."""
        baseline = BaselineData(
            legacy_keys={("R001", "c.cpp:140", "raw-new")},
            stable_keys={("R001", "c.cpp", "raw-new", "abc123")},
            finding_count=1,
        )
        shifted_f = _make_finding(
            rule_id="R001",
            evidence_locator="c.cpp:142",
            pattern_tag="raw-new",
            content_hash="abc123",
        )
        result = classify_findings([shifted_f], baseline)
        assert len(result.new) == 0
        assert len(result.shifted) == 1
        assert result.shifted[0].finding.evidence_locator == "c.cpp:142"
        assert result.shifted[0].baseline_locator == "c.cpp:140"

    def test_unchanged_finding_neither_new_nor_shifted(self) -> None:
        """Matches both stable and legacy key — not shifted."""
        baseline = BaselineData(
            legacy_keys={("R001", "a.py:10", "tag")},
            stable_keys={("R001", "a.py", "tag", "hash1")},
            finding_count=1,
        )
        f = _make_finding(
            rule_id="R001",
            evidence_locator="a.py:10",
            pattern_tag="tag",
            content_hash="hash1",
        )
        result = classify_findings([f], baseline)
        assert len(result.new) == 0
        assert len(result.shifted) == 0

    def test_resolved_finding(self) -> None:
        """Baseline entry not matched by any current finding."""
        baseline = BaselineData(
            legacy_keys={("R001", "old.py:1", "tag")},
            stable_keys={("R001", "old.py", "tag", "aaa111")},
            finding_count=1,
        )
        result = classify_findings([], baseline)
        assert len(result.resolved) >= 1

    def test_mixed_classification(self) -> None:
        """Mixed new, shifted, resolved in one call."""
        baseline = BaselineData(
            legacy_keys={
                ("R001", "a.cpp:10", "raw-new"),
                ("R002", "b.cpp:20", "raw-new"),
            },
            stable_keys={
                ("R001", "a.cpp", "raw-new", "hash_a"),
                ("R002", "b.cpp", "raw-new", "hash_b"),
            },
            finding_count=2,
        )
        # a.cpp shifted (same content hash, different line)
        shifted_f = _make_finding(
            rule_id="R001",
            evidence_locator="a.cpp:12",
            pattern_tag="raw-new",
            content_hash="hash_a",
        )
        # c.cpp is truly new
        new_f = _make_finding(
            rule_id="R003",
            evidence_locator="c.cpp:1",
            pattern_tag="raw-new",
            content_hash="hash_c",
        )
        result = classify_findings([shifted_f, new_f], baseline)
        assert len(result.new) == 1
        assert result.new[0].rule_id == "R003"
        assert len(result.shifted) == 1
        assert result.shifted[0].finding.rule_id == "R001"
        # R002/b.cpp was in baseline but not in current scan → resolved
        assert len(result.resolved) >= 1

    def test_no_content_hash_falls_back_to_legacy(self) -> None:
        """Finding without content_hash matched via legacy key → not new."""
        baseline = BaselineData(
            legacy_keys={("R001", "a.py:10", "tag")},
            finding_count=1,
        )
        f = _make_finding(
            rule_id="R001",
            evidence_locator="a.py:10",
            pattern_tag="tag",
        )
        result = classify_findings([f], baseline)
        assert len(result.new) == 0
        assert len(result.shifted) == 0

    def test_empty_baseline_all_new(self) -> None:
        baseline = BaselineData()
        f = _make_finding()
        result = classify_findings([f], baseline)
        assert len(result.new) == 1
        assert len(result.shifted) == 0
        assert len(result.resolved) == 0


# ---- T02/T03: CLI --baseline integration -----------------------------------


class TestCLIBaseline:
    def test_baseline_filters_known_findings_exit_0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When all findings match the baseline, exit 0 (no regressions)."""
        # Suppress LLM-powered rules (adr-gap etc.) which are non-deterministic
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("NFR_LLM_BACKEND", "api")
        import nfr_review.llm_client as _lc

        monkeypatch.setattr(_lc, "_ENV_LOADED", True)

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
