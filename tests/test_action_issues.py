# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/action_issues.py — remediation issue filing."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
action_issues = importlib.import_module("action_issues")
sys.path.pop(0)


def _write_jsonl(tmp_path: Path, records: list[dict[str, Any]]) -> Path:
    p = tmp_path / "output.jsonl"
    with p.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return p


_METADATA: dict[str, Any] = {
    "record_type": "run_metadata",
    "tool_version": "0.1.0",
    "target_repo": "demo",
    "timestamp": "2026-05-23T12:00:00Z",
    "collector_versions": {},
    "rules_run": ["R001"],
    "rules_skipped": [],
}

_RED_CRITICAL: dict[str, Any] = {
    "record_type": "finding",
    "rule_id": "R001",
    "rag": "red",
    "severity": "critical",
    "summary": "No circuit breaker configured",
    "recommendation": "Add resilience4j or equivalent",
    "evidence_locator": "src/main/java/App.java:42",
    "collector_name": "java_ast",
    "collector_version": "0.1.0",
    "confidence": 0.9,
    "pattern_tag": "resilience",
}

_RED_HIGH: dict[str, Any] = {
    "record_type": "finding",
    "rule_id": "R010",
    "rag": "red",
    "severity": "high",
    "summary": "Missing retry policy on HTTP client",
    "recommendation": "Configure retry with exponential backoff",
    "evidence_locator": "src/main/java/HttpClient.java:15",
    "collector_name": "java_ast",
    "collector_version": "0.1.0",
    "confidence": 0.85,
    "pattern_tag": "resilience",
}

_RED_MEDIUM: dict[str, Any] = {
    "record_type": "finding",
    "rule_id": "R020",
    "rag": "red",
    "severity": "medium",
    "summary": "Thread pool size not bounded",
    "recommendation": "Set explicit thread pool limits",
    "evidence_locator": "src/main/resources/application.yaml",
    "collector_name": "spring_config",
    "collector_version": "0.1.0",
    "confidence": 0.7,
    "pattern_tag": "concurrency",
}

_AMBER_FINDING: dict[str, Any] = {
    "record_type": "finding",
    "rule_id": "R002",
    "rag": "amber",
    "severity": "medium",
    "summary": "Thread pool size not explicitly set",
    "recommendation": "Set explicit thread pool bounds",
    "evidence_locator": "src/main/resources/application.yaml",
    "collector_name": "spring_config",
    "collector_version": "0.1.0",
    "confidence": 0.7,
    "pattern_tag": "concurrency",
}

_GREEN_FINDING: dict[str, Any] = {
    "record_type": "finding",
    "rule_id": "R003",
    "rag": "green",
    "severity": "info",
    "summary": "Health endpoint present",
    "recommendation": "",
    "evidence_locator": "src/main/java/Health.java",
    "collector_name": "java_ast",
    "collector_version": "0.1.0",
    "confidence": 1.0,
    "pattern_tag": "observability",
}


class TestLoadFindings:
    def test_all_findings_loaded(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _RED_CRITICAL, _AMBER_FINDING, _GREEN_FINDING])
        findings = action_issues._load_findings(p)
        assert len(findings) == 3

    def test_multiple_reds(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA, _RED_CRITICAL, _RED_HIGH])
        findings = action_issues._load_findings(p)
        assert len(findings) == 2

    def test_metadata_excluded(self, tmp_path: Path) -> None:
        p = _write_jsonl(tmp_path, [_METADATA])
        findings = action_issues._load_findings(p)
        assert findings == []


class TestFilterFindings:
    def test_default_threshold_high(self) -> None:
        filtered = action_issues.filter_findings([_RED_CRITICAL, _RED_HIGH, _RED_MEDIUM])
        assert len(filtered) == 2
        rule_ids = {f["rule_id"] for f in filtered}
        assert rule_ids == {"R001", "R010"}

    def test_critical_threshold(self) -> None:
        filtered = action_issues.filter_findings(
            [_RED_CRITICAL, _RED_HIGH, _RED_MEDIUM], severity_threshold="critical"
        )
        assert len(filtered) == 1
        assert filtered[0]["rule_id"] == "R001"

    def test_medium_threshold_includes_all(self) -> None:
        filtered = action_issues.filter_findings(
            [_RED_CRITICAL, _RED_HIGH, _RED_MEDIUM], severity_threshold="medium"
        )
        assert len(filtered) == 3

    def test_empty_input(self) -> None:
        assert action_issues.filter_findings([]) == []


class TestGenerateIssueTitle:
    def test_basic_title(self) -> None:
        title = action_issues.generate_issue_title(_RED_CRITICAL)
        assert title == "[nfr-review] R001: No circuit breaker configured"

    def test_long_summary_truncated_at_60(self) -> None:
        finding = {**_RED_CRITICAL, "summary": "A" * 200}
        title = action_issues.generate_issue_title(finding)
        summary_part = title.split(": ", 1)[1]
        assert len(summary_part) <= 60
        assert summary_part.endswith("...")

    def test_missing_fields(self) -> None:
        title = action_issues.generate_issue_title({"record_type": "finding"})
        assert title.startswith("[nfr-review] UNKNOWN:")


class TestGenerateIssueBody:
    def test_contains_key_marker(self) -> None:
        body = action_issues.generate_issue_body(_RED_CRITICAL)
        assert "<!-- nfr-review:key=" in body
        assert "<!-- nfr-review:rule=" in body
        assert "<!-- nfr-review:rag=" in body

    def test_contains_rule_id(self) -> None:
        body = action_issues.generate_issue_body(_RED_CRITICAL)
        assert "`R001`" in body

    def test_contains_severity(self) -> None:
        body = action_issues.generate_issue_body(_RED_CRITICAL)
        assert "`critical`" in body

    def test_contains_summary(self) -> None:
        body = action_issues.generate_issue_body(_RED_CRITICAL)
        assert "No circuit breaker configured" in body

    def test_contains_recommendation(self) -> None:
        body = action_issues.generate_issue_body(_RED_CRITICAL)
        assert "### Recommendation" in body
        assert "resilience4j" in body

    def test_no_recommendation_section_when_empty(self) -> None:
        finding = {**_RED_CRITICAL, "recommendation": ""}
        body = action_issues.generate_issue_body(finding)
        assert "### Recommendation" not in body

    def test_contains_evidence_location(self) -> None:
        body = action_issues.generate_issue_body(_RED_CRITICAL)
        assert "`src/main/java/App.java:42`" in body

    def test_contains_footer(self) -> None:
        body = action_issues.generate_issue_body(_RED_CRITICAL)
        assert "Filed automatically by" in body

    def test_ends_with_newline(self) -> None:
        body = action_issues.generate_issue_body(_RED_CRITICAL)
        assert body.endswith("\n")


class TestIssueLabels:
    def test_base_label(self) -> None:
        labels = action_issues.issue_labels(_RED_CRITICAL)
        assert "nfr-review" in labels

    def test_severity_label(self) -> None:
        labels = action_issues.issue_labels(_RED_CRITICAL)
        assert "severity:critical" in labels

    def test_high_severity_label(self) -> None:
        labels = action_issues.issue_labels(_RED_HIGH)
        assert "severity:high" in labels


class TestFindingFingerprint:
    def test_deterministic(self) -> None:
        fp1 = action_issues._finding_fingerprint(_RED_CRITICAL)
        fp2 = action_issues._finding_fingerprint(_RED_CRITICAL)
        assert fp1 == fp2

    def test_different_findings_different_fp(self) -> None:
        fp1 = action_issues._finding_fingerprint(_RED_CRITICAL)
        fp2 = action_issues._finding_fingerprint(_RED_HIGH)
        assert fp1 != fp2

    def test_length(self) -> None:
        fp = action_issues._finding_fingerprint(_RED_CRITICAL)
        assert len(fp) == 12


class TestDedupMarker:
    def test_format(self) -> None:
        marker = action_issues._dedup_marker(_RED_CRITICAL)
        assert marker.startswith("<!-- nfr-review:issue:")
        assert marker.endswith(" -->")

    def test_contains_fingerprint(self) -> None:
        fp = action_issues._finding_fingerprint(_RED_CRITICAL)
        marker = action_issues._dedup_marker(_RED_CRITICAL)
        assert fp in marker


class TestFileIssuesDryRun:
    def test_dry_run_returns_results(self) -> None:
        results = action_issues.file_issues(
            [_RED_CRITICAL, _RED_HIGH],
            "owner/repo",
            dry_run=True,
        )
        assert len(results) == 2
        assert all(r["status"] == "dry_run" for r in results)

    def test_dry_run_includes_rule_ids(self) -> None:
        results = action_issues.file_issues(
            [_RED_CRITICAL, _RED_HIGH],
            "owner/repo",
            dry_run=True,
        )
        rule_ids = {r["rule_id"] for r in results}
        assert rule_ids == {"R001", "R010"}

    def test_dry_run_with_threshold(self) -> None:
        results = action_issues.file_issues(
            [_RED_CRITICAL, _RED_HIGH, _RED_MEDIUM],
            "owner/repo",
            dry_run=True,
            severity_threshold="critical",
        )
        assert len(results) == 1
        assert results[0]["rule_id"] == "R001"

    def test_dry_run_empty_findings(self) -> None:
        results = action_issues.file_issues([], "owner/repo", dry_run=True)
        assert results == []


class TestFileIssuesDedup:
    def test_skips_existing(self) -> None:
        fp = action_issues._finding_fingerprint(_RED_CRITICAL)
        with patch("nfr_review.issues.find_existing_issues", return_value={fp}):
            results = action_issues.file_issues(
                [_RED_CRITICAL, _RED_HIGH],
                "owner/repo",
            )
        assert len(results) == 2
        statuses = {r["rule_id"]: r["status"] for r in results}
        assert statuses["R001"] == "skipped"
        assert statuses["R010"] != "skipped"

    def test_all_existing_skipped(self) -> None:
        fp1 = action_issues._finding_fingerprint(_RED_CRITICAL)
        fp2 = action_issues._finding_fingerprint(_RED_HIGH)
        with patch("nfr_review.issues.find_existing_issues", return_value={fp1, fp2}):
            results = action_issues.file_issues(
                [_RED_CRITICAL, _RED_HIGH],
                "owner/repo",
            )
        assert all(r["status"] == "skipped" for r in results)


class TestFindExistingIssues:
    def test_no_gh_cli(self) -> None:
        with patch("nfr_review.issues.subprocess.run", side_effect=FileNotFoundError):
            result = action_issues.find_existing_issues("owner/repo")
        assert result == set()

    def test_parses_legacy_markers(self) -> None:
        fp = action_issues._finding_fingerprint(_RED_CRITICAL)
        body = f"<!-- nfr-review:issue:{fp} -->\nsome body text"
        mock_result = type(
            "R",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    [{"number": 1, "body": body, "state": "OPEN", "url": ""}]
                ),
            },
        )()
        with patch("nfr_review.issues.subprocess.run", return_value=mock_result):
            result = action_issues.find_existing_issues("owner/repo")
        assert fp in result

    def test_parses_new_markers(self) -> None:
        fp = action_issues._finding_fingerprint(_RED_CRITICAL)
        body = f"<!-- nfr-review:key={fp} -->\n<!-- nfr-review:rule=R001 -->"
        mock_result = type(
            "R",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    [{"number": 1, "body": body, "state": "OPEN", "url": ""}]
                ),
            },
        )()
        with patch("nfr_review.issues.subprocess.run", return_value=mock_result):
            result = action_issues.find_existing_issues("owner/repo")
        assert fp in result

    def test_gh_failure(self) -> None:
        mock_result = type("R", (), {"returncode": 1, "stdout": ""})()
        with patch("nfr_review.issues.subprocess.run", return_value=mock_result):
            result = action_issues.find_existing_issues("owner/repo")
        assert result == set()

    def test_invalid_json(self) -> None:
        mock_result = type("R", (), {"returncode": 0, "stdout": "not json"})()
        with patch("nfr_review.issues.subprocess.run", return_value=mock_result):
            result = action_issues.find_existing_issues("owner/repo")
        assert result == set()
