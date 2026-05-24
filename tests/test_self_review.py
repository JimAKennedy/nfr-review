"""CLI-level self-review tests proving M012 milestone success criteria.

Runs nfr-review against the actual repo root to verify that path filtering
works end-to-end at the CLI level: test/fixture paths are included by default
and excluded with --exclude-tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.cli import cli

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_findings(jsonl_path: Path) -> list[dict]:
    findings: list[dict] = []
    with jsonl_path.open() as fh:
        for line in fh:
            record = json.loads(line)
            if record.get("record_type") == "finding" and record.get("rag") != "skipped":
                findings.append(record)
    return findings


@pytest.mark.slow
def test_self_review_default_includes_fixture_findings(tmp_path: Path) -> None:
    csv_path = tmp_path / "nfr-review.csv"
    jsonl_path = tmp_path / "nfr-review.jsonl"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["run", str(_REPO_ROOT), "--csv", str(csv_path), "--jsonl", str(jsonl_path)],
    )

    assert result.exit_code == 0, (
        f"CLI failed with exit code {result.exit_code}:\n{result.output}"
    )
    assert jsonl_path.exists(), "JSONL output file was not created"

    findings = _parse_findings(jsonl_path)
    fixture_findings = [
        f for f in findings if "tests/fixtures/" in f.get("evidence_locator", "")
    ]

    assert len(fixture_findings) >= 1, (
        "Expected at least 1 finding from tests/fixtures/ by default, "
        f"got {len(fixture_findings)}. Total findings: {len(findings)}"
    )


@pytest.mark.slow
def test_self_review_exclude_tests_removes_fixture_findings(tmp_path: Path) -> None:
    csv_path = tmp_path / "nfr-review.csv"
    jsonl_path = tmp_path / "nfr-review.jsonl"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            str(_REPO_ROOT),
            "--exclude-tests",
            "--csv",
            str(csv_path),
            "--jsonl",
            str(jsonl_path),
        ],
    )

    assert result.exit_code == 0, (
        f"CLI failed with exit code {result.exit_code}:\n{result.output}"
    )
    assert jsonl_path.exists(), "JSONL output file was not created"

    findings = _parse_findings(jsonl_path)
    fixture_findings = [
        f for f in findings if "tests/fixtures/" in f.get("evidence_locator", "")
    ]

    regression_findings = [
        f for f in findings if "tests/regression/" in f.get("evidence_locator", "")
    ]

    assert len(fixture_findings) == 0, (
        f"Expected zero findings from tests/fixtures/ with --exclude-tests, "
        f"got {len(fixture_findings)}: "
        f"{[f['evidence_locator'] for f in fixture_findings]}"
    )
    assert len(regression_findings) == 0, (
        f"Expected zero findings from tests/regression/ with --exclude-tests, "
        f"got {len(regression_findings)}: "
        f"{[f['evidence_locator'] for f in regression_findings]}"
    )


@pytest.mark.slow
def test_self_review_no_dep_resolution_failures(tmp_path: Path) -> None:
    csv_path = tmp_path / "nfr-review.csv"
    jsonl_path = tmp_path / "nfr-review.jsonl"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["run", str(_REPO_ROOT), "--csv", str(csv_path), "--jsonl", str(jsonl_path)],
    )

    assert result.exit_code == 0, (
        f"CLI failed with exit code {result.exit_code}:\n{result.output}"
    )

    output_lower = result.output.lower()
    assert "resolution failed" not in output_lower, (
        f"Found 'resolution failed' in output:\n{result.output}"
    )
    assert "unresolvable" not in output_lower, (
        f"Found 'unresolvable' in output:\n{result.output}"
    )
