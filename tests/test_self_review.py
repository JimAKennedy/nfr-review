"""CLI-level self-review tests proving M012 milestone success criteria.

Runs nfr-review against the actual repo root to verify that path filtering
works end-to-end at the CLI level: test/fixture paths are excluded by default
and included with --include-tests.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

import nfr_review.collectors  # noqa: F401
import nfr_review.rules  # noqa: F401
from nfr_review.cli import cli

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _ensure_registries_populated() -> None:
    """Re-register rules/collectors if test_registry's autouse fixture cleared them."""
    for name in nfr_review.rules.__all__:
        mod_name = f"nfr_review.rules.{name}"
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
    for name in nfr_review.collectors.__all__:
        mod_name = f"nfr_review.collectors.{name}"
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])


def _parse_findings(jsonl_path: Path) -> list[dict]:
    findings: list[dict] = []
    with jsonl_path.open() as fh:
        for line in fh:
            record = json.loads(line)
            if record.get("record_type") == "finding" and record.get("rag") != "skipped":
                findings.append(record)
    return findings


@pytest.mark.slow
def test_self_review_default_excludes_fixture_findings(tmp_path: Path) -> None:
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

    assert len(fixture_findings) == 0, (
        "Expected zero findings from tests/fixtures/ by default, "
        f"got {len(fixture_findings)}: "
        f"{[f['evidence_locator'] for f in fixture_findings]}"
    )


@pytest.mark.slow
def test_self_review_include_tests_adds_fixture_findings(tmp_path: Path) -> None:
    csv_path = tmp_path / "nfr-review.csv"
    jsonl_path = tmp_path / "nfr-review.jsonl"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            str(_REPO_ROOT),
            "--include-tests",
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

    assert len(fixture_findings) >= 1, (
        "Expected at least 1 finding from tests/fixtures/ with --include-tests, "
        f"got {len(fixture_findings)}. Total findings: {len(findings)}"
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
