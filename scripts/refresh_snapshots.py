#!/usr/bin/env python3
"""Refresh regression test snapshots and API cache in one step.

Usage:
    python scripts/refresh_snapshots.py                 # refresh from current manifest pins
    python scripts/refresh_snapshots.py --bump-commits  # update SHAs to latest HEAD first
    python scripts/refresh_snapshots.py --dry-run       # show what would happen
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MANIFEST_PATH = _PROJECT_ROOT / "tests" / "regression" / "manifest.yaml"


def _bump_commits(manifest_path: Path, *, dry_run: bool) -> list[str]:
    """Update each repo's commit_sha to its default branch HEAD."""
    yaml = YAML()
    yaml.preserve_quotes = True
    data = yaml.load(manifest_path)
    changes: list[str] = []

    for repo in data["repos"]:
        name = repo["name"]
        url = repo["url"]
        old_sha = repo.get("commit_sha")
        if old_sha is None:
            continue

        result = subprocess.run(
            ["git", "ls-remote", url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            print(f"  WARN: ls-remote failed for {name}: {result.stderr.strip()}")
            continue

        new_sha = result.stdout.split()[0] if result.stdout.strip() else None
        if not new_sha:
            print(f"  WARN: no HEAD SHA returned for {name}")
            continue

        if new_sha != old_sha:
            changes.append(f"  {name}: {old_sha[:12]} -> {new_sha[:12]}")
            if not dry_run:
                repo["commit_sha"] = new_sha
        else:
            print(f"  {name}: already at HEAD ({old_sha[:12]})")

    if changes and not dry_run:
        yaml.dump(data, manifest_path)

    return changes


def _run_regression_update() -> int:
    """Run the regression suite with --update-snapshots."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/regression/test_snapshots.py",
        "-n",
        "auto",
        "--update-snapshots",
        "--timeout=600",
        "-v",
    ]
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(_PROJECT_ROOT), check=False)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh regression snapshots and API cache.")
    parser.add_argument(
        "--bump-commits",
        action="store_true",
        help="Update manifest commit SHAs to latest HEAD before refreshing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes.",
    )
    args = parser.parse_args()

    print("=== Regression Snapshot Refresh ===\n")

    if args.bump_commits:
        print("Step 1: Bumping manifest commits to latest HEAD...")
        changes = _bump_commits(_MANIFEST_PATH, dry_run=args.dry_run)
        if changes:
            print(f"\n  {len(changes)} repo(s) updated:")
            for c in changes:
                print(c)
        else:
            print("  All repos already at latest HEAD.")
        print()
    else:
        print("Step 1: Skipped (use --bump-commits to update SHAs)\n")

    if args.dry_run:
        print("Step 2: Would run regression suite with --update-snapshots")
        print("  (skipped in dry-run mode)")
        return 0

    print("Step 2: Regenerating snapshots and API cache...")
    rc = _run_regression_update()

    if rc == 0:
        print("\nDone. Review changes with: git diff --stat tests/regression/")
    else:
        print(f"\nRegression suite exited with code {rc}.")

    return rc


if __name__ == "__main__":
    sys.exit(main())
