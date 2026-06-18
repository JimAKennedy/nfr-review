"""Snapshot-based regression tests for Structurizr DSL output.

Runs ``nfr-review arch --format dsl`` against corpus repos and compares
normalized DSL text against stored baselines.  Use ``--update-snapshots``
to regenerate baselines after intentional changes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.regression.conftest import clone_repo, load_manifest, normalize_dsl

_MANIFEST = load_manifest()
_REPO_NAMES = [entry["name"] for entry in _MANIFEST]
_REPO_MAP = {entry["name"]: entry for entry in _MANIFEST}


@pytest.mark.regression
@pytest.mark.timeout(600)
@pytest.mark.parametrize("repo_name", _REPO_NAMES)
def test_dsl_regression_snapshot(
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

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nfr_review.cli",
            "arch",
            str(clone_dir),
            "--output-dir",
            str(tmp_path),
            "--no-llm",
            "--format",
            "dsl",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert result.returncode == 0, (
        f"nfr-review arch exited {result.returncode} for {repo_name}:\n{result.stderr[-2000:]}"
    )

    dsl_files = list(tmp_path.glob("*.dsl"))
    assert dsl_files, f"No DSL file generated for {repo_name} in {tmp_path}"
    dsl_text = dsl_files[0].read_text(encoding="utf-8")

    normalized = normalize_dsl(dsl_text)

    snapshot_file = snapshot_dir / f"{repo_name}.dsl"

    if update_snapshots:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file.write_text(normalized, encoding="utf-8")
        return

    if not snapshot_file.exists():
        pytest.fail(
            f"No DSL baseline found for {repo_name}. "
            f"Run with --update-snapshots to generate: {snapshot_file}"
        )

    baseline = snapshot_file.read_text(encoding="utf-8")

    if normalized != baseline:
        norm_lines = normalized.splitlines()
        base_lines = baseline.splitlines()
        diff_lines: list[str] = []
        for i, (a, b) in enumerate(zip(norm_lines, base_lines, strict=False)):
            if a != b:
                diff_lines.append(f"  line {i + 1}:")
                diff_lines.append(f"    - {b[:120]}")
                diff_lines.append(f"    + {a[:120]}")
                if len(diff_lines) >= 15:
                    break
        if len(norm_lines) != len(base_lines):
            diff_lines.append(
                f"  line count: baseline={len(base_lines)}, current={len(norm_lines)}"
            )
        pytest.fail(
            f"DSL snapshot mismatch for {repo_name}:\n"
            + "\n".join(diff_lines)
            + "\nRun with --update-snapshots to accept the new baseline."
        )
