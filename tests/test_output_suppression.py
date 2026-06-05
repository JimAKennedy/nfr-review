# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Integration tests for suppression audit data in output formats."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from nfr_review.engine import RunResult
from nfr_review.models import Finding, RuleResult, RunMetadata
from nfr_review.output.csv import write_csv
from nfr_review.output.jsonl import write_jsonl
from nfr_review.output.markdown import render_markdown_report
from nfr_review.suppression import SuppressionInfo


def _metadata() -> RunMetadata:
    return RunMetadata(
        target_repo="/tmp/test-repo",
        timestamp="2026-06-05T12:00:00Z",
        tool_version="0.1.0",
    )


def _make_finding(
    rule_id: str = "cpp-raw-memory",
    evidence_locator: str = "controller.cpp:10",
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
        "pattern_tag": "cpp-raw-new",
    }
    defaults.update(kwargs)
    return Finding(**defaults)


def _make_run(
    findings: list[Finding] | None = None,
    rule_results: list[RuleResult] | None = None,
) -> RunResult:
    return RunResult(
        findings=findings or [],
        rule_results=rule_results or [],
        run_metadata=_metadata(),
    )


def _make_suppression(
    rule_id: str = "cpp-raw-memory",
    reason: str | None = None,
    source_file: str = "controller.cpp",
    source_line: int = 10,
) -> SuppressionInfo:
    return SuppressionInfo(
        rule_ids=frozenset({rule_id}),
        reason=reason,
        source_file=source_file,
        source_line=source_line,
    )


class TestJsonlSuppression:
    def test_suppressed_records_include_reason(self, tmp_path: Path) -> None:
        out = tmp_path / "out.jsonl"
        finding = _make_finding()
        info = _make_suppression(reason="JIRA-1234")
        write_jsonl(_make_run(), out, suppressed_findings=[(finding, info)])

        records = [json.loads(line) for line in out.read_text().strip().split("\n")]
        suppressed = [r for r in records if r.get("suppressed")]
        assert len(suppressed) == 1
        assert suppressed[0]["suppression_reason"] == "JIRA-1234"
        assert suppressed[0]["suppression_source"] == "controller.cpp:10"

    def test_suppressed_without_reason(self, tmp_path: Path) -> None:
        out = tmp_path / "out.jsonl"
        finding = _make_finding()
        info = _make_suppression(reason=None)
        write_jsonl(_make_run(), out, suppressed_findings=[(finding, info)])

        records = [json.loads(line) for line in out.read_text().strip().split("\n")]
        suppressed = [r for r in records if r.get("suppressed")]
        assert len(suppressed) == 1
        assert suppressed[0]["suppression_reason"] is None

    def test_metadata_counts(self, tmp_path: Path) -> None:
        out = tmp_path / "out.jsonl"
        f1 = _make_finding(evidence_locator="a.cpp:1")
        f2 = _make_finding(evidence_locator="b.cpp:2")
        s1 = _make_suppression(reason="ticket")
        s2 = _make_suppression(reason=None)
        write_jsonl(
            _make_run(),
            out,
            suppressed_findings=[(f1, s1), (f2, s2)],
        )

        records = [json.loads(line) for line in out.read_text().strip().split("\n")]
        meta = records[0]
        assert meta["suppressed_count"] == 2
        assert meta["suppressed_with_reason_count"] == 1
        assert meta["suppressed_without_reason_count"] == 1

    def test_no_suppressed_no_extra_fields(self, tmp_path: Path) -> None:
        out = tmp_path / "out.jsonl"
        write_jsonl(_make_run(findings=[_make_finding()]), out)

        records = [json.loads(line) for line in out.read_text().strip().split("\n")]
        meta = records[0]
        assert "suppressed_count" not in meta


class TestCsvSuppression:
    def test_suppressed_rows_have_rag_suppressed(self, tmp_path: Path) -> None:
        out = tmp_path / "out.csv"
        finding = _make_finding()
        info = _make_suppression(reason="ticket-99")
        write_csv(
            _make_run(findings=[_make_finding(evidence_locator="active.cpp:1")]),
            out,
            suppressed_findings=[(finding, info)],
        )

        with out.open() as f:
            reader = list(csv.reader(f))
        header = reader[0]
        assert "suppression_reason" in header
        reason_idx = header.index("suppression_reason")

        suppressed_rows = [r for r in reader[1:] if r[1] == "suppressed"]
        assert len(suppressed_rows) == 1
        assert suppressed_rows[0][reason_idx] == "ticket-99"

    def test_active_rows_have_empty_reason(self, tmp_path: Path) -> None:
        out = tmp_path / "out.csv"
        active = _make_finding(evidence_locator="a.cpp:1")
        suppressed = _make_finding(evidence_locator="b.cpp:2")
        info = _make_suppression(reason="reason")
        write_csv(
            _make_run(findings=[active]),
            out,
            suppressed_findings=[(suppressed, info)],
        )

        with out.open() as f:
            reader = list(csv.reader(f))
        header = reader[0]
        reason_idx = header.index("suppression_reason")
        active_rows = [r for r in reader[1:] if r[1] != "suppressed"]
        assert len(active_rows) == 1
        assert active_rows[0][reason_idx] == ""

    def test_no_suppressed_no_extra_column(self, tmp_path: Path) -> None:
        out = tmp_path / "out.csv"
        write_csv(_make_run(findings=[_make_finding()]), out)

        with out.open() as f:
            reader = list(csv.reader(f))
        assert "suppression_reason" not in reader[0]

    def test_suppressed_without_reason_empty_string(self, tmp_path: Path) -> None:
        out = tmp_path / "out.csv"
        finding = _make_finding()
        info = _make_suppression(reason=None)
        write_csv(
            _make_run(),
            out,
            suppressed_findings=[(finding, info)],
        )

        with out.open() as f:
            reader = list(csv.reader(f))
        header = reader[0]
        reason_idx = header.index("suppression_reason")
        suppressed_rows = [r for r in reader[1:] if r[1] == "suppressed"]
        assert suppressed_rows[0][reason_idx] == ""


class TestMarkdownSuppression:
    def _fake_result(self, findings: list[Finding] | None = None) -> RunResult:
        return _make_run(findings=findings)

    def test_suppression_audit_section_present(self) -> None:
        finding = _make_finding()
        info = _make_suppression(reason="JIRA-42")
        md = render_markdown_report(
            nfr_result=self._fake_result(),
            suppressed_findings=[(finding, info)],
        )
        assert "## Suppression Audit" in md
        assert "JIRA-42" in md
        assert "cpp-raw-memory" in md

    def test_no_suppression_section_when_empty(self) -> None:
        md = render_markdown_report(
            nfr_result=self._fake_result(),
            suppressed_findings=None,
        )
        assert "## Suppression Audit" not in md

    def test_warning_for_missing_justification(self) -> None:
        finding = _make_finding()
        info = _make_suppression(reason=None)
        md = render_markdown_report(
            nfr_result=self._fake_result(),
            suppressed_findings=[(finding, info)],
        )
        assert "Warning" in md
        assert "no justification" in md.lower()

    def test_no_warning_when_all_have_reasons(self) -> None:
        finding = _make_finding()
        info = _make_suppression(reason="approved")
        md = render_markdown_report(
            nfr_result=self._fake_result(),
            suppressed_findings=[(finding, info)],
        )
        assert "## Suppression Audit" in md
        assert "Warning" not in md

    def test_mixed_reasons_counts(self) -> None:
        f1 = _make_finding(evidence_locator="a.cpp:1")
        f2 = _make_finding(evidence_locator="b.cpp:2")
        s1 = _make_suppression(reason="ticket")
        s2 = _make_suppression(reason=None)
        md = render_markdown_report(
            nfr_result=self._fake_result(),
            suppressed_findings=[(f1, s1), (f2, s2)],
        )
        assert "1 with justification" in md
        assert "1 without" in md
