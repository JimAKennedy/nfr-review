from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nfr_review.engine import RunResult
from nfr_review.models import Finding, RuleResult, RunMetadata
from nfr_review.output import CSV_HEADER, OutputError, write_csv, write_jsonl

R007_HEADER = (
    "rule_id",
    "rag",
    "severity",
    "summary",
    "recommendation",
    "evidence_locator",
    "collector_name",
    "collector_version",
    "confidence",
    "pattern_tag",
)


def _make_finding(**overrides: object) -> Finding:
    payload: dict[str, object] = {
        "rule_id": "sample-readme-exists",
        "rag": "green",
        "severity": "info",
        "summary": "README found at repo root",
        "recommendation": "No action needed",
        "evidence_locator": "README.md",
        "collector_name": "repo_structure",
        "collector_version": "0.1.0",
        "confidence": 0.95,
        "pattern_tag": "documentation",
    }
    payload.update(overrides)
    return Finding(**payload)  # type: ignore[arg-type]


def _make_metadata(**overrides: object) -> RunMetadata:
    payload: dict[str, object] = {
        "tool_version": "0.1.0",
        "target_repo": "/repos/sample",
        "git_sha": "abc1234",
        "git_branch": "main",
        "git_dirty": False,
        "timestamp": "2026-05-03T12:00:00Z",
        "collector_versions": {"repo_structure": "0.1.0"},
        "rules_run": ["sample-readme-exists"],
        "rules_skipped": [],
    }
    payload.update(overrides)
    return RunMetadata(**payload)  # type: ignore[arg-type]


def _make_run(
    findings: list[Finding] | None = None,
    rule_results: list[RuleResult] | None = None,
    metadata: RunMetadata | None = None,
) -> RunResult:
    return RunResult(
        findings=findings or [],
        rule_results=rule_results or [],
        run_metadata=metadata if metadata is not None else _make_metadata(),
    )


# ---- CSV ---------------------------------------------------------------


def test_csv_header_constant_matches_r007() -> None:
    assert CSV_HEADER == R007_HEADER


def test_csv_header_is_first_line(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    write_csv(_make_run(findings=[_make_finding()]), out)
    first_line = out.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == ",".join(R007_HEADER)


def test_csv_finding_row_preserves_field_order(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    write_csv(_make_run(findings=[_make_finding()]), out)

    rows = list(csv.reader(out.open(encoding="utf-8")))
    assert rows[0] == list(R007_HEADER)
    assert rows[1] == [
        "sample-readme-exists",
        "green",
        "info",
        "README found at repo root",
        "No action needed",
        "README.md",
        "repo_structure",
        "0.1.0",
        "0.95",
        "documentation",
    ]


def test_csv_empty_findings_writes_header_only(tmp_path: Path) -> None:
    out = tmp_path / "empty.csv"
    write_csv(_make_run(), out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines == [",".join(R007_HEADER)]


def test_csv_skipped_rule_appears_as_row(tmp_path: Path) -> None:
    out = tmp_path / "skip.csv"
    rule_results = [
        RuleResult(
            rule_id="needs-llm",
            skipped=True,
            skip_reason="ANTHROPIC_API_KEY unset",
        ),
    ]
    write_csv(_make_run(rule_results=rule_results), out)

    rows = list(csv.reader(out.open(encoding="utf-8")))
    assert rows[0] == list(R007_HEADER)
    skip_row = rows[1]
    assert skip_row[0] == "needs-llm"
    assert skip_row[1] == "skipped"
    assert skip_row[3] == "rule skipped: ANTHROPIC_API_KEY unset"
    # Other columns blank.
    for idx in (2, 4, 5, 6, 7, 8, 9):
        assert skip_row[idx] == ""


def test_csv_skipped_without_reason_uses_fallback(tmp_path: Path) -> None:
    out = tmp_path / "skip-no-reason.csv"
    rule_results = [RuleResult(rule_id="bare-skip", skipped=True)]
    write_csv(_make_run(rule_results=rule_results), out)
    rows = list(csv.reader(out.open(encoding="utf-8")))
    assert rows[1][3] == "rule skipped: rule reported skipped"


def test_csv_findings_then_skipped_rule_order(tmp_path: Path) -> None:
    out = tmp_path / "mixed.csv"
    write_csv(
        _make_run(
            findings=[_make_finding()],
            rule_results=[
                RuleResult(rule_id="ok", skipped=False),
                RuleResult(
                    rule_id="needs-llm",
                    skipped=True,
                    skip_reason="missing key",
                ),
            ],
        ),
        out,
    )
    rows = list(csv.reader(out.open(encoding="utf-8")))
    # header, finding, skipped (the non-skipped rule_result is not echoed).
    assert len(rows) == 3
    assert rows[1][0] == "sample-readme-exists"
    assert rows[2][0] == "needs-llm"
    assert rows[2][1] == "skipped"


def test_csv_escapes_comma_and_quote(tmp_path: Path) -> None:
    out = tmp_path / "tricky.csv"
    finding = _make_finding(
        summary='Has "quotes", and a comma',
        recommendation='Use "explicit" delimiters',
    )
    write_csv(_make_run(findings=[finding]), out)

    raw = out.read_text(encoding="utf-8")
    # The quoted field should be wrapped and inner quotes doubled.
    assert '"Has ""quotes"", and a comma"' in raw

    # Round-trip via the csv module gives the original strings back.
    rows = list(csv.reader(out.open(encoding="utf-8")))
    assert rows[1][3] == 'Has "quotes", and a comma'
    assert rows[1][4] == 'Use "explicit" delimiters'


def test_csv_round_trips_non_ascii_utf8(tmp_path: Path) -> None:
    out = tmp_path / "utf8.csv"
    finding = _make_finding(summary="日本語 — café — 🚀")
    write_csv(_make_run(findings=[finding]), out)

    rows = list(csv.reader(out.open(encoding="utf-8")))
    assert rows[1][3] == "日本語 — café — 🚀"


def test_csv_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "out.csv"
    assert not nested.parent.exists()
    write_csv(_make_run(findings=[_make_finding()]), nested)
    assert nested.exists()


def test_csv_uses_quote_minimal(tmp_path: Path) -> None:
    """Plain finding with no special chars should not be wrapped in quotes."""
    out = tmp_path / "minimal.csv"
    write_csv(_make_run(findings=[_make_finding()]), out)
    body = out.read_text(encoding="utf-8")
    # 'README found at repo root' has spaces but no quote/comma -> unquoted.
    assert "README found at repo root" in body
    assert '"README found at repo root"' not in body


def test_csv_wraps_filesystem_error_in_output_error(tmp_path: Path) -> None:
    out = tmp_path / "boom.csv"

    real_open = Path.open

    def explode(self: Path, *args: object, **kwargs: object) -> object:
        if self == out:
            raise OSError("disk full")
        return real_open(self, *args, **kwargs)

    with patch.object(Path, "open", explode), pytest.raises(OutputError) as exc:
        write_csv(_make_run(findings=[_make_finding()]), out)
    assert str(out) in str(exc.value)


# ---- JSONL -------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_jsonl_first_line_is_run_metadata(tmp_path: Path) -> None:
    out = tmp_path / "out.jsonl"
    write_jsonl(_make_run(findings=[_make_finding()]), out)

    records = _read_jsonl(out)
    assert records[0]["record_type"] == "run_metadata"
    assert records[0]["git_sha"] == "abc1234"
    assert records[0]["git_branch"] == "main"
    assert records[0]["timestamp"] == "2026-05-03T12:00:00Z"
    assert records[0]["collector_versions"] == {"repo_structure": "0.1.0"}


def test_jsonl_finding_record_has_all_finding_fields(tmp_path: Path) -> None:
    out = tmp_path / "out.jsonl"
    write_jsonl(_make_run(findings=[_make_finding()]), out)

    records = _read_jsonl(out)
    finding_record = records[1]
    assert finding_record["record_type"] == "finding"
    for col in R007_HEADER:
        assert col in finding_record
    assert finding_record["confidence"] == 0.95
    assert finding_record["rag"] == "green"


def test_jsonl_each_line_is_independently_valid_json(tmp_path: Path) -> None:
    out = tmp_path / "out.jsonl"
    write_jsonl(
        _make_run(
            findings=[_make_finding(), _make_finding(rule_id="other")],
            rule_results=[
                RuleResult(
                    rule_id="needs-llm",
                    skipped=True,
                    skip_reason="missing key",
                ),
            ],
        ),
        out,
    )
    raw = out.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    for line in raw.splitlines():
        # Must independently parse.
        parsed = json.loads(line)
        assert "record_type" in parsed


def test_jsonl_no_trailing_whitespace_per_line(tmp_path: Path) -> None:
    out = tmp_path / "out.jsonl"
    write_jsonl(_make_run(findings=[_make_finding()]), out)
    for line in out.read_text(encoding="utf-8").splitlines():
        assert line == line.rstrip()
        assert not line.endswith(" ")


def test_jsonl_empty_findings_writes_metadata_only(tmp_path: Path) -> None:
    out = tmp_path / "empty.jsonl"
    write_jsonl(_make_run(), out)
    records = _read_jsonl(out)
    assert len(records) == 1
    assert records[0]["record_type"] == "run_metadata"


def test_jsonl_skipped_rule_record_is_emitted(tmp_path: Path) -> None:
    out = tmp_path / "skipped.jsonl"
    write_jsonl(
        _make_run(
            rule_results=[
                RuleResult(
                    rule_id="needs-llm",
                    skipped=True,
                    skip_reason="ANTHROPIC_API_KEY unset",
                ),
            ],
        ),
        out,
    )
    records = _read_jsonl(out)
    assert len(records) == 2
    skip_record = records[1]
    assert skip_record["record_type"] == "finding"
    assert skip_record["rule_id"] == "needs-llm"
    assert skip_record["rag"] == "skipped"
    assert skip_record["summary"] == "rule skipped: ANTHROPIC_API_KEY unset"


def test_jsonl_skipped_without_reason_uses_fallback(tmp_path: Path) -> None:
    out = tmp_path / "skipped-bare.jsonl"
    write_jsonl(
        _make_run(rule_results=[RuleResult(rule_id="bare", skipped=True)]),
        out,
    )
    records = _read_jsonl(out)
    assert records[1]["summary"] == "rule skipped: rule reported skipped"


def test_jsonl_round_trips_non_ascii_utf8(tmp_path: Path) -> None:
    out = tmp_path / "utf8.jsonl"
    finding = _make_finding(summary="日本語 — café — 🚀")
    write_jsonl(_make_run(findings=[finding]), out)
    records = _read_jsonl(out)
    assert records[1]["summary"] == "日本語 — café — 🚀"


def test_jsonl_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "x" / "y" / "out.jsonl"
    assert not nested.parent.exists()
    write_jsonl(_make_run(findings=[_make_finding()]), nested)
    assert nested.exists()


def test_jsonl_raises_when_metadata_missing(tmp_path: Path) -> None:
    out = tmp_path / "no-meta.jsonl"
    run = RunResult(findings=[_make_finding()], run_metadata=None)
    with pytest.raises(OutputError) as exc:
        write_jsonl(run, out)
    assert str(out) in str(exc.value)


def test_jsonl_wraps_filesystem_error_in_output_error(tmp_path: Path) -> None:
    out = tmp_path / "boom.jsonl"

    real_open = Path.open

    def explode(self: Path, *args: object, **kwargs: object) -> object:
        if self == out:
            raise OSError("disk full")
        return real_open(self, *args, **kwargs)

    with patch.object(Path, "open", explode), pytest.raises(OutputError) as exc:
        write_jsonl(_make_run(findings=[_make_finding()]), out)
    assert str(out) in str(exc.value)


def test_jsonl_writes_findings_then_skipped(tmp_path: Path) -> None:
    out = tmp_path / "ordered.jsonl"
    write_jsonl(
        _make_run(
            findings=[_make_finding()],
            rule_results=[
                RuleResult(rule_id="ok", skipped=False),
                RuleResult(
                    rule_id="needs-llm",
                    skipped=True,
                    skip_reason="missing",
                ),
            ],
        ),
        out,
    )
    records = _read_jsonl(out)
    assert [r["record_type"] for r in records] == [
        "run_metadata",
        "finding",
        "finding",
    ]
    assert records[1]["rule_id"] == "sample-readme-exists"
    assert records[2]["rule_id"] == "needs-llm"
    assert records[2]["rag"] == "skipped"
