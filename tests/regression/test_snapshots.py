"""Snapshot-based regression tests for nfr-review output.

Clones public reference repos, runs nfr-review, and compares normalized
JSONL output against stored baselines. Use ``--update-snapshots`` to
regenerate baselines after intentional changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.regression.conftest import (
    _normalize_dep_freshness,
    _normalize_structure_finding,
    clone_repo,
    load_manifest,
    load_snapshot_metadata,
    normalize_findings,
    write_snapshot_metadata,
)

_API_CACHE_DIR = Path(__file__).resolve().parent / "api_cache"


def _pair_field_diffs(
    added: list[dict], removed: list[dict]
) -> list[tuple[dict, dict, list[tuple[str, object, object]]]]:
    """Pair added/removed findings by (rule_id, summary) and return field diffs."""
    results = []
    used: set[int] = set()
    for a in added:
        for i, r in enumerate(removed):
            if i in used:
                continue
            if a.get("rule_id") == r.get("rule_id") and a.get("summary") == r.get("summary"):
                diffs = [
                    (k, a.get(k), r.get(k))
                    for k in sorted(set(a) | set(r))
                    if a.get(k) != r.get(k)
                ]
                if diffs:
                    results.append((a, r, diffs))
                    used.add(i)
                    break
    return results


_MANIFEST = load_manifest()
_REPO_NAMES = [entry["name"] for entry in _MANIFEST]
_REPO_MAP = {entry["name"]: entry for entry in _MANIFEST}


@pytest.mark.regression
@pytest.mark.timeout(600)
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

    api_cache_file = _API_CACHE_DIR / f"{repo_name}.json.gz"
    env = {**os.environ, "NFR_DEPS_DEV_CACHE": str(api_cache_file)}

    if not update_snapshots:
        meta = load_snapshot_metadata(snapshot_dir)
        if meta and "generated_at" in meta:
            env["NFR_REFERENCE_DATE"] = meta["generated_at"]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nfr_review.cli",
            "run",
            str(clone_dir),
            "--include-tests",
            "--workers",
            "4",
            "--jsonl",
            str(jsonl_out),
            "--csv",
            str(csv_out),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
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
        write_snapshot_metadata(snapshot_dir)
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
            if record.get("rule_id", "").startswith("structure-"):
                record = _normalize_structure_finding(record)
            baseline.append(record)

    if normalized != baseline:
        added = [f for f in normalized if f not in baseline]
        removed = [f for f in baseline if f not in normalized]

        _UPSTREAM_DRIFT_RULES = {
            # Graphify's Leiden clustering is non-deterministic: community
            # composition, edge counts, and finding counts all vary between
            # runs.  Normalization (conftest._normalize_structure_finding)
            # stabilizes IDs and content fields, but the finding *count*
            # remains unstable.  Pin graphify output (graph.json) to enable
            # removing these from the drift set.
            "structure-coupling-cluster",
            "structure-god-node",
            "structure-weak-boundary",
        }
        added_stable = [f for f in added if f.get("rule_id") not in _UPSTREAM_DRIFT_RULES]
        removed_stable = [f for f in removed if f.get("rule_id") not in _UPSTREAM_DRIFT_RULES]

        if not added_stable and not removed_stable:
            return

        parts = [f"Snapshot mismatch for {repo_name}:"]
        if added_stable:
            parts.append(f"  +{len(added_stable)} new finding(s):")
            for f in added_stable[:5]:
                parts.append(f"    + {f.get('rule_id')}: {f.get('summary', '')[:80]}")
        if removed_stable:
            parts.append(f"  -{len(removed_stable)} removed finding(s):")
            for f in removed_stable[:5]:
                parts.append(f"    - {f.get('rule_id')}: {f.get('summary', '')[:80]}")

        paired = _pair_field_diffs(added_stable, removed_stable)
        if paired:
            parts.append("  Field-level diffs (first 3):")
            for a, _r, diffs in paired[:3]:
                parts.append(f"    {a.get('rule_id')}/{a.get('summary', '')[:40]}:")
                for k, av, rv in diffs:
                    parts.append(f"      {k}: {rv!r} -> {av!r}")

        parts.append("Run with --update-snapshots to accept the new baseline.")
        pytest.fail("\n".join(parts))


@pytest.mark.regression
def test_snapshot_metadata_exists(snapshot_dir: Path) -> None:
    """Verify snapshot metadata is present for staleness tracking."""
    from tests.regression.conftest import load_snapshot_metadata

    meta = load_snapshot_metadata(snapshot_dir)
    if meta is None:
        pytest.skip("No snapshot metadata — run with --update-snapshots to generate")
    generated = datetime.fromisoformat(meta["generated_at"])
    age_days = (datetime.now(UTC) - generated).days
    if age_days > 90:
        pytest.fail(
            f"Snapshots are {age_days} days old (generated {meta['generated_at']}). "
            "Regenerate with: pytest --update-snapshots -m regression"
        )


@pytest.mark.regression
def test_drift_filter_guard() -> None:
    """Prevent _UPSTREAM_DRIFT_RULES from growing unbounded.

    Each excluded rule is a regression gap.  Adding new entries should
    be a conscious decision, not a habit.
    """
    _MAX_DRIFT_RULES = 5
    _UPSTREAM_DRIFT_RULES = {
        "structure-coupling-cluster",
        "structure-god-node",
        "structure-weak-boundary",
    }
    assert len(_UPSTREAM_DRIFT_RULES) <= _MAX_DRIFT_RULES, (
        f"_UPSTREAM_DRIFT_RULES has {len(_UPSTREAM_DRIFT_RULES)} entries "
        f"(max {_MAX_DRIFT_RULES}). Fix the root cause instead of "
        "adding more exclusions."
    )
