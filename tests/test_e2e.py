"""End-to-end test: copy fixture repo -> git init -> run nfr-review -> assert output.

This is the slice's flagship verification — it proves the whole pipeline
(config -> engine -> collectors -> rules -> CSV/JSONL formatters -> CLI exit
code) works on real files with real git provenance. It uses Click's
``CliRunner`` rather than ``subprocess.run`` so the test stays fast and does
not depend on ``pip install -e .`` being run before pytest.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from nfr_review.cli import cli
from nfr_review.output.csv import CSV_HEADER

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample-repo"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial fixture commit")


def test_fixture_directory_is_tracked() -> None:
    """The fixture must be a real, tracked directory under the repo."""
    assert FIXTURE_DIR.is_dir()
    assert (FIXTURE_DIR / "README.md").is_file()
    assert (FIXTURE_DIR / "pyproject.toml").is_file()
    # Must not contain a nested .git — the test creates one in tmp_path.
    assert not (FIXTURE_DIR / ".git").exists()


def test_e2e_run_produces_csv_and_jsonl_with_full_provenance(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "sample-repo"
    shutil.copytree(FIXTURE_DIR, repo)
    _init_repo(repo)

    csv_path = tmp_path / "findings.csv"
    jsonl_path = tmp_path / "findings.jsonl"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            str(repo),
            "--csv",
            str(csv_path),
            "--jsonl",
            str(jsonl_path),
        ],
    )

    assert result.exit_code == 0, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert csv_path.exists()
    assert jsonl_path.exists()

    # CSV header must equal R007 fields in order.
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows, "CSV is empty"
    assert tuple(rows[0]) == CSV_HEADER

    # The fixture has a README -> sample rule emits exactly one green finding.
    finding_rows = rows[1:]
    assert len(finding_rows) >= 1
    sample_rows = [r for r in finding_rows if r[0] == "sample-readme-exists"]
    assert len(sample_rows) == 1
    assert sample_rows[0][1] == "green"

    # JSONL: line 1 is run_metadata with full provenance.
    with jsonl_path.open(encoding="utf-8") as fh:
        lines = [line for line in fh.read().splitlines() if line]
    assert lines, "JSONL is empty"
    metadata = json.loads(lines[0])
    assert metadata["record_type"] == "run_metadata"
    assert metadata["git_sha"] is not None and len(metadata["git_sha"]) >= 7
    assert metadata["git_branch"] is not None
    assert metadata["collector_versions"]["repo-structure"]
    assert metadata["tool_version"]
    assert metadata["timestamp"]

    # Subsequent JSONL lines: at least one finding for sample-readme-exists.
    finding_records = [json.loads(line) for line in lines[1:]]
    assert any(
        rec.get("record_type") == "finding"
        and rec.get("rule_id") == "sample-readme-exists"
        for rec in finding_records
    )


def test_e2e_stderr_summary_line_is_emitted(tmp_path: Path) -> None:
    repo = tmp_path / "sample-repo"
    shutil.copytree(FIXTURE_DIR, repo)
    _init_repo(repo)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            str(repo),
            "--csv",
            str(tmp_path / "out.csv"),
            "--jsonl",
            str(tmp_path / "out.jsonl"),
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert "nfr-review:" in result.stderr
    assert "collectors_run=" in result.stderr
    assert "rules_run=" in result.stderr


@pytest.mark.parametrize(
    ("argv", "expected_exit"),
    [
        (["explain", "definitely-not-a-real-rule-id"], 1),
    ],
)
def test_e2e_explain_unknown_rule_exits_1(argv: list[str], expected_exit: int) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, argv)
    assert result.exit_code == expected_exit
