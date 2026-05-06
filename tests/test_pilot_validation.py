"""Pilot integration tests: full nfr-review pipeline against agentic-java-demo.

These tests validate that all 20 rules execute against the real
agentic-java-demo Spring Boot repo, producing correct CSV + JSONL output
with full provenance. They require the pilot target to be cloned locally
at /Users/jim/dev/agentic-java-demo.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.cli import cli
from nfr_review.output.csv import CSV_HEADER

PILOT_TARGET = Path("/Users/jim/dev/agentic-java-demo")
PILOT_CONFIG = Path(__file__).parent / "fixtures" / "configs" / "agentic-java-demo.yaml"

_skip_unless_pilot = pytest.mark.skipif(
    not PILOT_TARGET.is_dir(),
    reason="pilot target not available",
)


def _run_pilot(tmp_path: Path) -> tuple[Path, Path, object]:
    """Run the full pilot scan, return (csv_path, jsonl_path, result)."""
    csv_path = tmp_path / "findings.csv"
    jsonl_path = tmp_path / "findings.jsonl"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            str(PILOT_TARGET),
            "--config",
            str(PILOT_CONFIG),
            "--csv",
            str(csv_path),
            "--jsonl",
            str(jsonl_path),
        ],
    )
    return csv_path, jsonl_path, result


@_skip_unless_pilot
def test_pilot_completes_under_120_seconds(tmp_path: Path) -> None:
    start = time.perf_counter()
    csv_path, jsonl_path, result = _run_pilot(tmp_path)
    elapsed = time.perf_counter() - start

    assert result.exit_code in (0, 2), (
        f"exit_code={result.exit_code} stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert csv_path.exists()
    assert jsonl_path.exists()
    assert elapsed < 120, f"pilot scan took {elapsed:.1f}s, exceeds 120s budget"


@_skip_unless_pilot
def test_pilot_csv_has_r007_header_and_findings(tmp_path: Path) -> None:
    csv_path, _, result = _run_pilot(tmp_path)
    assert result.exit_code in (0, 2), result.stderr

    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))

    assert rows, "CSV is empty"
    assert tuple(rows[0]) == CSV_HEADER, f"header mismatch: {rows[0]}"
    finding_rows = [r for r in rows[1:] if r[1] != "skipped"]
    assert len(finding_rows) >= 1, "expected at least one non-skipped finding"


@_skip_unless_pilot
def test_pilot_jsonl_has_full_provenance(tmp_path: Path) -> None:
    _, jsonl_path, result = _run_pilot(tmp_path)
    assert result.exit_code in (0, 2), result.stderr

    with jsonl_path.open(encoding="utf-8") as fh:
        lines = [line for line in fh.read().splitlines() if line]

    assert lines, "JSONL is empty"
    metadata = json.loads(lines[0])
    assert metadata["record_type"] == "run_metadata"

    assert metadata["git_sha"] is not None and len(metadata["git_sha"]) >= 7
    assert metadata["git_branch"] is not None
    assert metadata["git_dirty"] is not None
    assert metadata["timestamp"]
    assert metadata["tool_version"]
    assert isinstance(metadata["collector_versions"], dict)
    assert len(metadata["collector_versions"]) >= 1
    assert isinstance(metadata["rules_run"], list)
    assert isinstance(metadata["rules_skipped"], list)


@_skip_unless_pilot
def test_pilot_exercises_multiple_collectors(tmp_path: Path) -> None:
    csv_path, _, result = _run_pilot(tmp_path)
    assert result.exit_code in (0, 2), result.stderr

    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))

    collector_col_idx = list(CSV_HEADER).index("collector_name")
    collector_names = {
        row[collector_col_idx]
        for row in rows[1:]
        if row[1] != "skipped" and row[collector_col_idx]
    }
    assert len(collector_names) >= 3, (
        f"expected findings from >=3 collectors, got {collector_names}"
    )


@_skip_unless_pilot
def test_pilot_all_rules_accounted(tmp_path: Path) -> None:
    _, jsonl_path, result = _run_pilot(tmp_path)
    assert result.exit_code in (0, 2), result.stderr

    with jsonl_path.open(encoding="utf-8") as fh:
        lines = [line for line in fh.read().splitlines() if line]

    metadata = json.loads(lines[0])
    rules_run = metadata["rules_run"]
    rules_skipped_ids = [s["rule_id"] for s in metadata["rules_skipped"]]

    total_registered = 27
    config_skipped = ["health-endpoint-missing"]
    accounted = len(rules_run) + len(rules_skipped_ids)
    assert accounted == total_registered, (
        f"rules_run({len(rules_run)}) + rules_skipped({len(rules_skipped_ids)}) "
        f"= {accounted}, expected {total_registered}. "
        f"run={rules_run}, skipped_ids={rules_skipped_ids}"
    )

    for skipped_id in config_skipped:
        assert skipped_id in rules_skipped_ids, (
            f"config-skipped rule {skipped_id!r} not in rules_skipped"
        )


@_skip_unless_pilot
def test_pilot_band2_graceful_degradation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    _, jsonl_path, result = _run_pilot(tmp_path)
    assert result.exit_code in (0, 2), f"exit_code={result.exit_code} stderr={result.stderr!r}"

    with jsonl_path.open(encoding="utf-8") as fh:
        lines = [line for line in fh.read().splitlines() if line]

    metadata = json.loads(lines[0])
    rules_skipped = metadata["rules_skipped"]
    rules_run = metadata["rules_run"]
    skipped_ids = [s["rule_id"] for s in rules_skipped]

    band2_rules = {"architectural-drift-from-adr", "pii-in-log-statements"}

    for rule_id in band2_rules:
        if rule_id in skipped_ids:
            skip_entry = next(s for s in rules_skipped if s["rule_id"] == rule_id)
            assert skip_entry["reason"], f"Band 2 rule {rule_id!r} skipped with empty reason"
        else:
            assert rule_id in rules_run, (
                f"Band 2 rule {rule_id!r} neither in rules_run nor rules_skipped"
            )

    assert band2_rules & (set(skipped_ids) | set(rules_run)) == band2_rules, (
        "all Band 2 rules must be accounted for"
    )
