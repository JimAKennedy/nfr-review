"""Snapshot-based regression tests for nfr-review output.

Clones public reference repos, runs nfr-review, and compares normalized
JSONL output against stored baselines. Use ``--update-snapshots`` to
regenerate baselines after intentional changes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.regression.conftest import (
    _normalize_dep_freshness,
    clone_repo,
    load_manifest,
    normalize_findings,
)

_MANIFEST = load_manifest()
_REPO_NAMES = [entry["name"] for entry in _MANIFEST]
_REPO_MAP = {entry["name"]: entry for entry in _MANIFEST}


@pytest.mark.regression
@pytest.mark.parametrize("repo_name", _REPO_NAMES)
def test_regression_snapshot(
    repo_name: str,
    tmp_path: Path,
    regression_repos_dir: Path,
    snapshot_dir: Path,
    update_snapshots: bool,
) -> None:
    entry = _REPO_MAP[repo_name]

    clone_dir = clone_repo(
        name=entry["name"],
        url=entry["url"],
        commit_sha=entry.get("commit_sha"),
        repos_dir=regression_repos_dir,
    )

    jsonl_out = tmp_path / "output.jsonl"
    csv_out = tmp_path / "output.csv"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nfr_review.cli",
            "run",
            str(clone_dir),
            "--jsonl",
            str(jsonl_out),
            "--csv",
            str(csv_out),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode in (0, 2), (
        f"nfr-review exited {result.returncode} for {repo_name}:\n{result.stderr}"
    )

    normalized = normalize_findings(jsonl_out)

    snapshot_file = snapshot_dir / f"{repo_name}.jsonl"

    if update_snapshots:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        with snapshot_file.open("w", encoding="utf-8") as fh:
            for record in normalized:
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                fh.write("\n")
        return

    if not snapshot_file.exists():
        pytest.fail(
            f"No baseline found for {repo_name}. "
            f"Run with --update-snapshots to generate: {snapshot_file}"
        )

    baseline: list[dict] = []
    for line in snapshot_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if record.get("rule_id") == "dep-freshness":
                record = _normalize_dep_freshness(record)
            baseline.append(record)

    if normalized != baseline:
        added = [f for f in normalized if f not in baseline]
        removed = [f for f in baseline if f not in normalized]
        parts = [f"Snapshot mismatch for {repo_name}:"]
        if added:
            parts.append(f"  +{len(added)} new finding(s):")
            for f in added[:5]:
                parts.append(f"    + {f.get('rule_id')}: {f.get('summary', '')[:80]}")
        if removed:
            parts.append(f"  -{len(removed)} removed finding(s):")
            for f in removed[:5]:
                parts.append(f"    - {f.get('rule_id')}: {f.get('summary', '')[:80]}")
        parts.append("Run with --update-snapshots to accept the new baseline.")
        pytest.fail("\n".join(parts))
