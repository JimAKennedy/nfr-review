# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for CSV output writer."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from nfr_review.engine import RunResult
from nfr_review.models import Finding, RuleResult
from nfr_review.output._errors import OutputError
from nfr_review.output.csv import (
    CSV_HEADER,
    CSV_HEADER_WITH_AUDIT,
    _finding_row,
    _skipped_row,
    _stringify,
    write_csv,
)
from nfr_review.suppression import SuppressionInfo

# -- helpers ------------------------------------------------------------------


def _make_finding(**overrides: object) -> Finding:
    defaults: dict[str, object] = {
        "rule_id": "TEST-001",
        "rag": "red",
        "severity": "high",
        "summary": "test finding",
        "recommendation": "fix it",
        "evidence_locator": "file://src/main.py:10",
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
) -> RunResult:
    return RunResult(
        findings=findings or [],
        rule_results=skipped_rules or [],
    )


def _read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


# -- _stringify ---------------------------------------------------------------


class TestStringify:
    def test_none_returns_empty(self) -> None:
        assert _stringify(None) == ""

    def test_true_returns_lowercase(self) -> None:
        assert _stringify(True) == "true"

    def test_false_returns_lowercase(self) -> None:
        assert _stringify(False) == "false"

    def test_string_passthrough(self) -> None:
        assert _stringify("hello") == "hello"

    def test_numeric_coerced(self) -> None:
        assert _stringify(0.9) == "0.9"
        assert _stringify(42) == "42"


# -- _finding_row -------------------------------------------------------------


class TestFindingRow:
    def test_returns_list_of_strings(self) -> None:
        row = _finding_row(_make_finding())
        assert isinstance(row, list)
        assert all(isinstance(v, str) for v in row)

    def test_column_count_matches_header(self) -> None:
        row = _finding_row(_make_finding())
        assert len(row) == len(CSV_HEADER)

    def test_values_match_finding_fields(self) -> None:
        finding = _make_finding(
            rule_id="R-042",
            rag="amber",
            severity="medium",
            summary="some issue",
            recommendation="do something",
            evidence_locator="file://a.py:1",
            collector_name="col",
            collector_version="1.0",
            confidence=0.75,
            pattern_tag="tag-x",
        )
        row = _finding_row(finding)
        assert row[0] == "R-042"
        assert row[1] == "amber"
        assert row[2] == "medium"
        assert row[3] == "some issue"
        assert row[4] == "do something"
        assert row[5] == "file://a.py:1"
        assert row[6] == "col"
        assert row[7] == "1.0"
        assert row[8] == "0.75"
        assert row[9] == "tag-x"


# -- _skipped_row -------------------------------------------------------------


class TestSkippedRow:
    def test_rule_id_in_first_column(self) -> None:
        row = _skipped_row("SKIP-001", "no Java")
        assert row[0] == "SKIP-001"

    def test_rag_is_skipped(self) -> None:
        row = _skipped_row("SKIP-001", "no Java")
        assert row[1] == "skipped"

    def test_reason_embedded_in_summary(self) -> None:
        row = _skipped_row("SKIP-001", "no Java")
        assert "no Java" in row[3]

    def test_column_count(self) -> None:
        # _skipped_row hardcodes 10 columns (original R007 fields before
        # content_hash was added).  Verify the static length is stable.
        row = _skipped_row("SKIP-001", "reason")
        assert len(row) == 10


# -- CSV_HEADER constants -----------------------------------------------------


class TestHeaderConstants:
    def test_csv_header_is_tuple(self) -> None:
        assert isinstance(CSV_HEADER, tuple)

    def test_csv_header_starts_with_rule_id(self) -> None:
        assert CSV_HEADER[0] == "rule_id"

    def test_csv_header_with_audit_extends_base(self) -> None:
        assert CSV_HEADER_WITH_AUDIT[:-1] == CSV_HEADER
        assert CSV_HEADER_WITH_AUDIT[-1] == "suppression_reason"


# -- write_csv ----------------------------------------------------------------


class TestWriteCsv:
    def test_basic_findings(self, tmp_path: Path) -> None:
        findings = [_make_finding(rule_id="A"), _make_finding(rule_id="B")]
        result = _make_result(findings=findings)
        out = tmp_path / "out.csv"
        write_csv(result, out)

        rows = _read_csv(out)
        assert rows[0] == list(CSV_HEADER)
        assert len(rows) == 3  # header + 2 findings
        assert rows[1][0] == "A"
        assert rows[2][0] == "B"

    def test_empty_findings(self, tmp_path: Path) -> None:
        result = _make_result()
        out = tmp_path / "out.csv"
        write_csv(result, out)

        rows = _read_csv(out)
        assert len(rows) == 1  # header only
        assert rows[0] == list(CSV_HEADER)

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "deep" / "nested" / "out.csv"
        write_csv(_make_result(findings=[_make_finding()]), out)
        assert out.exists()

    def test_skipped_rules_appended(self, tmp_path: Path) -> None:
        skipped = [
            RuleResult(rule_id="SKIP-01", skipped=True, skip_reason="not applicable"),
        ]
        result = _make_result(skipped_rules=skipped)
        out = tmp_path / "out.csv"
        write_csv(result, out)

        rows = _read_csv(out)
        # header + 1 skipped row
        assert len(rows) == 2
        assert rows[1][0] == "SKIP-01"
        assert rows[1][1] == "skipped"
        assert "not applicable" in rows[1][3]

    def test_skipped_with_no_reason(self, tmp_path: Path) -> None:
        skipped = [
            RuleResult(rule_id="SKIP-02", skipped=True, skip_reason=None),
        ]
        result = _make_result(skipped_rules=skipped)
        out = tmp_path / "out.csv"
        write_csv(result, out)

        rows = _read_csv(out)
        assert "rule reported skipped" in rows[1][3]

    def test_suppressed_findings_add_audit_column(self, tmp_path: Path) -> None:
        finding = _make_finding(rule_id="SUPP-01")
        suppressed = [
            (
                finding,
                SuppressionInfo(
                    rule_ids=frozenset({"SUPP-01"}),
                    reason="accepted risk",
                    source_file="foo.py",
                    source_line=5,
                ),
            ),
        ]
        result = _make_result(findings=[_make_finding(rule_id="NORMAL")])
        out = tmp_path / "out.csv"
        write_csv(result, out, suppressed_findings=suppressed)

        rows = _read_csv(out)
        # Header should be extended
        assert rows[0] == list(CSV_HEADER_WITH_AUDIT)
        # Normal finding row has empty suppression_reason column
        normal_row = rows[1]
        assert normal_row[0] == "NORMAL"
        assert normal_row[-1] == ""
        # Suppressed row has rag overridden and reason filled
        supp_row = rows[2]
        assert supp_row[0] == "SUPP-01"
        assert supp_row[1] == "suppressed"
        assert supp_row[-1] == "accepted risk"

    def test_suppressed_none_reason(self, tmp_path: Path) -> None:
        finding = _make_finding(rule_id="SUPP-02")
        suppressed = [
            (
                finding,
                SuppressionInfo(
                    rule_ids=frozenset({"SUPP-02"}),
                    reason=None,
                    source_file="bar.py",
                    source_line=10,
                ),
            ),
        ]
        result = _make_result()
        out = tmp_path / "out.csv"
        write_csv(result, out, suppressed_findings=suppressed)

        rows = _read_csv(out)
        assert rows[0] == list(CSV_HEADER_WITH_AUDIT)
        # None reason serializes as empty string
        supp_row = rows[1]
        assert supp_row[-1] == ""

    def test_skipped_row_gets_extra_column_when_suppressed(self, tmp_path: Path) -> None:
        finding = _make_finding()
        suppressed = [
            (
                finding,
                SuppressionInfo(
                    rule_ids=frozenset({"TEST-001"}),
                    reason="ok",
                    source_file="x.py",
                    source_line=1,
                ),
            ),
        ]
        skipped = [RuleResult(rule_id="SKIP-X", skipped=True, skip_reason="n/a")]
        result = _make_result(skipped_rules=skipped)
        out = tmp_path / "out.csv"
        write_csv(result, out, suppressed_findings=suppressed)

        rows = _read_csv(out)
        # Header uses the extended audit header
        assert rows[0] == list(CSV_HEADER_WITH_AUDIT)
        # Skipped row present with rule id and "skipped" rag
        skipped_row = rows[2]  # header, suppressed, skipped
        assert skipped_row[0] == "SKIP-X"
        assert skipped_row[1] == "skipped"

    def test_output_error_on_bad_path(self) -> None:
        result = _make_result(findings=[_make_finding()])
        bad_path = Path("/dev/null/impossible/out.csv")
        with pytest.raises(OutputError, match="failed to write CSV"):
            write_csv(result, bad_path)

    def test_non_skipped_rule_results_ignored(self, tmp_path: Path) -> None:
        rule_results = [
            RuleResult(rule_id="PASS-01", skipped=False),
        ]
        result = _make_result(skipped_rules=rule_results)
        out = tmp_path / "out.csv"
        write_csv(result, out)

        rows = _read_csv(out)
        assert len(rows) == 1  # header only; non-skipped rule produces no row
