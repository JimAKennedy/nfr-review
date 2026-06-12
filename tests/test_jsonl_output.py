# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for R018 JSONL output format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nfr_review.baseline import FindingClassification, ShiftedFinding
from nfr_review.engine import RunResult
from nfr_review.models import Finding, RuleResult, RunMetadata
from nfr_review.output._errors import OutputError
from nfr_review.output.jsonl import _finding_record, _skipped_record, write_jsonl
from nfr_review.suppression import SuppressionInfo


def _make_finding(**overrides: object) -> Finding:
    defaults: dict[str, object] = {
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


def _make_metadata(**overrides: object) -> RunMetadata:
    defaults: dict[str, object] = {
        "tool_version": "0.1.0",
        "target_repo": "/tmp/test-repo",
        "timestamp": "2026-01-01T00:00:00Z",
        "rules_run": ["TEST-001"],
    }
    defaults.update(overrides)
    return RunMetadata(**defaults)


def _make_result(
    findings: list[Finding] | None = None,
    skipped_rules: list[RuleResult] | None = None,
    run_metadata: RunMetadata | None = "DEFAULT",  # type: ignore[assignment]
) -> RunResult:
    if run_metadata == "DEFAULT":  # type: ignore[comparison-overlap]
        run_metadata = _make_metadata()
    return RunResult(
        findings=findings or [],
        rule_results=skipped_rules or [],
        run_metadata=run_metadata,
    )


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file and return a list of parsed dicts."""
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.strip().splitlines()]


# --- _finding_record() ---


def test_finding_record_has_record_type():
    finding = _make_finding()
    record = _finding_record(finding)
    assert record["record_type"] == "finding"


def test_finding_record_contains_all_model_fields():
    finding = _make_finding()
    record = _finding_record(finding)
    for field_name in Finding.model_fields:
        assert field_name in record, f"missing field: {field_name}"


def test_finding_record_without_classification():
    finding = _make_finding()
    record = _finding_record(finding)
    assert "classification" not in record


def test_finding_record_with_classification():
    finding = _make_finding()
    record = _finding_record(finding, classification="new")
    assert record["classification"] == "new"


# --- _skipped_record() ---


def test_skipped_record_has_record_type():
    record = _skipped_record("SKIP-001", "no evidence")
    assert record["record_type"] == "finding"


def test_skipped_record_sets_rag_to_skipped():
    record = _skipped_record("SKIP-001", "no evidence")
    assert record["rag"] == "skipped"


def test_skipped_record_rule_id():
    record = _skipped_record("SKIP-001", "no evidence")
    assert record["rule_id"] == "SKIP-001"


def test_skipped_record_summary_contains_reason():
    record = _skipped_record("SKIP-001", "no evidence")
    assert "no evidence" in record["summary"]


def test_skipped_record_nulls_other_fields():
    record = _skipped_record("SKIP-001", "no evidence")
    for field_name in Finding.model_fields:
        if field_name in ("rule_id", "rag", "summary"):
            continue
        assert record[field_name] is None, f"expected None for {field_name}"


# --- write_jsonl() basics ---


def test_run_metadata_is_first_line(tmp_path: Path):
    result = _make_result(findings=[_make_finding()])
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out)

    records = _read_jsonl(out)
    assert records[0]["record_type"] == "run_metadata"


def test_run_metadata_contains_provenance(tmp_path: Path):
    meta = _make_metadata(tool_version="2.0.0", target_repo="/repos/proj")
    result = _make_result(run_metadata=meta)
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out)

    records = _read_jsonl(out)
    assert records[0]["tool_version"] == "2.0.0"
    assert records[0]["target_repo"] == "/repos/proj"


def test_raises_output_error_when_metadata_is_none(tmp_path: Path):
    result = _make_result(run_metadata=None)
    out = tmp_path / "out.jsonl"
    with pytest.raises(OutputError, match="run_metadata is None"):
        write_jsonl(result, out)


def test_each_line_independently_parseable(tmp_path: Path):
    findings = [_make_finding(rule_id=f"R-{i:03d}") for i in range(5)]
    result = _make_result(findings=findings)
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out)

    text = out.read_text(encoding="utf-8")
    for line in text.strip().splitlines():
        parsed = json.loads(line)
        assert isinstance(parsed, dict)


def test_one_line_per_finding(tmp_path: Path):
    findings = [_make_finding(rule_id=f"R-{i:03d}") for i in range(3)]
    result = _make_result(findings=findings)
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out)

    records = _read_jsonl(out)
    # 1 metadata + 3 findings
    assert len(records) == 4
    finding_records = [r for r in records if r["record_type"] == "finding"]
    assert len(finding_records) == 3
    assert {r["rule_id"] for r in finding_records} == {"R-000", "R-001", "R-002"}


def test_empty_findings_produces_metadata_only(tmp_path: Path):
    result = _make_result()
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out)

    records = _read_jsonl(out)
    assert len(records) == 1
    assert records[0]["record_type"] == "run_metadata"


# --- Classification tagging ---


def test_classification_tags_new_findings(tmp_path: Path):
    finding = _make_finding(rule_id="NEW-001")
    result = _make_result(findings=[finding])
    cls = FindingClassification(
        new=[finding],
        shifted=[],
        resolved=[],
    )
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out, classification=cls)

    records = _read_jsonl(out)
    finding_rec = [r for r in records if r["record_type"] == "finding"][0]
    assert finding_rec["classification"] == "new"


def test_classification_tags_baseline_findings(tmp_path: Path):
    finding = _make_finding(rule_id="BAS-001")
    result = _make_result(findings=[finding])
    # Not in new and not in shifted -> baseline
    cls = FindingClassification(new=[], shifted=[], resolved=[])
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out, classification=cls)

    records = _read_jsonl(out)
    finding_rec = [r for r in records if r["record_type"] == "finding"][0]
    assert finding_rec["classification"] == "baseline"


def test_classification_tags_shifted_findings(tmp_path: Path):
    finding = _make_finding(
        rule_id="SHIFT-001",
        evidence_locator="file://src/main.py:20:1",
        content_hash="abc123",
    )
    result = _make_result(findings=[finding])
    shifted = ShiftedFinding(
        finding=finding,
        baseline_locator="file://src/main.py:10:1",
    )
    cls = FindingClassification(new=[], shifted=[shifted], resolved=[])
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out, classification=cls)

    records = _read_jsonl(out)
    finding_rec = [r for r in records if r["record_type"] == "finding"][0]
    assert finding_rec["classification"] == "shifted"
    assert finding_rec["baseline_locator"] == "file://src/main.py:10:1"


def test_classification_appends_resolved_entries(tmp_path: Path):
    result = _make_result()
    resolved_key = ("RESOLVED-001", "file://src/old.py:5", "legacy-pattern")
    cls = FindingClassification(new=[], shifted=[], resolved=[resolved_key])
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out, classification=cls)

    records = _read_jsonl(out)
    resolved_recs = [r for r in records if r.get("classification") == "resolved"]
    assert len(resolved_recs) == 1
    assert resolved_recs[0]["rule_id"] == "RESOLVED-001"
    assert resolved_recs[0]["evidence_locator"] == "file://src/old.py:5"
    assert resolved_recs[0]["pattern_tag"] == "legacy-pattern"


def test_classification_resolved_with_short_key(tmp_path: Path):
    result = _make_result()
    resolved_key = ("RESOLVED-001",)
    cls = FindingClassification(new=[], shifted=[], resolved=[resolved_key])
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out, classification=cls)

    records = _read_jsonl(out)
    resolved_recs = [r for r in records if r.get("classification") == "resolved"]
    assert len(resolved_recs) == 1
    assert resolved_recs[0]["rule_id"] == "RESOLVED-001"
    assert resolved_recs[0]["evidence_locator"] == ""
    assert resolved_recs[0]["pattern_tag"] == ""


# --- Suppressed findings ---


def test_suppressed_findings_emitted_with_metadata(tmp_path: Path):
    finding = _make_finding(rule_id="SUPP-001")
    info = SuppressionInfo(
        rule_ids=frozenset({"SUPP-001"}),
        reason="JIRA-123 accepted risk",
        source_file="src/main.py",
        source_line=42,
    )
    result = _make_result()
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out, suppressed_findings=[(finding, info)])

    records = _read_jsonl(out)
    suppressed_recs = [r for r in records if r.get("suppressed") is True]
    assert len(suppressed_recs) == 1
    assert suppressed_recs[0]["rule_id"] == "SUPP-001"
    assert suppressed_recs[0]["suppression_reason"] == "JIRA-123 accepted risk"
    assert suppressed_recs[0]["suppression_source"] == "src/main.py:42"


def test_suppressed_finding_without_reason(tmp_path: Path):
    finding = _make_finding(rule_id="SUPP-002")
    info = SuppressionInfo(
        rule_ids=frozenset({"SUPP-002"}),
        reason=None,
        source_file="src/utils.py",
        source_line=10,
    )
    result = _make_result()
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out, suppressed_findings=[(finding, info)])

    records = _read_jsonl(out)
    suppressed_recs = [r for r in records if r.get("suppressed") is True]
    assert len(suppressed_recs) == 1
    assert suppressed_recs[0]["suppression_reason"] is None


def test_suppression_metadata_in_run_metadata(tmp_path: Path):
    f1 = _make_finding(rule_id="S-001")
    f2 = _make_finding(rule_id="S-002")
    info_with = SuppressionInfo(
        rule_ids=frozenset({"S-001"}),
        reason="accepted",
        source_file="a.py",
        source_line=1,
    )
    info_without = SuppressionInfo(
        rule_ids=frozenset({"S-002"}),
        reason=None,
        source_file="b.py",
        source_line=2,
    )
    result = _make_result()
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out, suppressed_findings=[(f1, info_with), (f2, info_without)])

    records = _read_jsonl(out)
    meta = records[0]
    assert meta["record_type"] == "run_metadata"
    assert meta["suppressed_count"] == 2
    assert meta["suppressed_with_reason_count"] == 1
    assert meta["suppressed_without_reason_count"] == 1


def test_no_suppression_metadata_when_none(tmp_path: Path):
    result = _make_result()
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out)

    records = _read_jsonl(out)
    meta = records[0]
    assert "suppressed_count" not in meta


# --- Skipped rules ---


def test_skipped_rules_appended_as_synthetic_records(tmp_path: Path):
    skipped = [
        RuleResult(rule_id="SKIP-001", skipped=True, skip_reason="no Java"),
        RuleResult(rule_id="SKIP-002", skipped=True, skip_reason="no Go"),
    ]
    result = _make_result(skipped_rules=skipped)
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out)

    records = _read_jsonl(out)
    skipped_recs = [r for r in records if r.get("rag") == "skipped"]
    assert len(skipped_recs) == 2
    assert {r["rule_id"] for r in skipped_recs} == {"SKIP-001", "SKIP-002"}
    assert "no Java" in skipped_recs[0]["summary"] or "no Java" in skipped_recs[1]["summary"]


def test_skipped_rule_without_reason_uses_default(tmp_path: Path):
    skipped = [RuleResult(rule_id="SKIP-003", skipped=True, skip_reason=None)]
    result = _make_result(skipped_rules=skipped)
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out)

    records = _read_jsonl(out)
    skipped_recs = [r for r in records if r.get("rag") == "skipped"]
    assert len(skipped_recs) == 1
    assert "rule reported skipped" in skipped_recs[0]["summary"]


def test_non_skipped_rule_results_not_emitted(tmp_path: Path):
    rules = [RuleResult(rule_id="PASS-001", skipped=False)]
    result = _make_result(skipped_rules=rules)
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out)

    records = _read_jsonl(out)
    assert len(records) == 1  # metadata only


# --- OSError wrapping ---


def test_oserror_wrapped_as_output_error():
    result = _make_result(findings=[_make_finding()])
    bad_path = Path("/dev/null/impossible/out.jsonl")
    with pytest.raises(OutputError, match="failed to write JSONL"):
        write_jsonl(result, bad_path)


# --- Ordering ---


def test_output_order_metadata_findings_skipped(tmp_path: Path):
    """Verify ordering: metadata, then findings, then skipped records."""
    findings = [_make_finding(rule_id="F-001")]
    skipped = [RuleResult(rule_id="SK-001", skipped=True, skip_reason="n/a")]
    result = _make_result(findings=findings, skipped_rules=skipped)
    out = tmp_path / "out.jsonl"
    write_jsonl(result, out)

    records = _read_jsonl(out)
    assert records[0]["record_type"] == "run_metadata"
    assert records[1]["record_type"] == "finding"
    assert records[1]["rule_id"] == "F-001"
    assert records[2]["rag"] == "skipped"
    assert records[2]["rule_id"] == "SK-001"


def test_creates_parent_directories(tmp_path: Path):
    result = _make_result()
    out = tmp_path / "nested" / "deep" / "out.jsonl"
    write_jsonl(result, out)
    assert out.exists()
