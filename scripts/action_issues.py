# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Generate and file GitHub issues for NFR findings.

Reads a JSONL file produced by ``nfr-review run`` and syncs GitHub issues
for findings that meet the severity / RAG threshold.

Can be used as a CLI (``python scripts/action_issues.py output.jsonl``)
or imported as a library for testing.

Environment variables consumed (GitHub Actions context):
    GITHUB_REPOSITORY — owner/repo for issue filing (required for filing)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from nfr_review.issues import (
    _dedup_marker,  # noqa: F401 — re-export for test_action_issues.py
    _finding_fingerprint,  # noqa: F401
    _severity_meets_threshold,  # noqa: F401
    file_issues,  # noqa: F401
    filter_findings,  # noqa: F401
    find_existing_issues,  # noqa: F401
    generate_issue_body,  # noqa: F401
    generate_issue_title,  # noqa: F401
    issue_labels,  # noqa: F401
    sync_issues,
)

_DEFAULT_SEVERITY_THRESHOLD = "high"
_ISSUE_LABEL = "nfr-review"


def _load_findings(jsonl_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("record_type") == "finding":
                records.append(rec)
    return records


def main() -> None:
    """CLI entry point: read JSONL path from argv, sync or file issues."""
    import os

    if len(sys.argv) < 2:
        print("usage: action_issues.py <jsonl-path> [--dry-run]", file=sys.stderr)
        sys.exit(1)

    jsonl_path = Path(sys.argv[1])
    if not jsonl_path.exists():
        print(f"error: file not found: {jsonl_path}", file=sys.stderr)
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo and not dry_run:
        print("error: GITHUB_REPOSITORY not set", file=sys.stderr)
        sys.exit(1)

    severity_threshold = os.environ.get(
        "NFR_ISSUE_SEVERITY_THRESHOLD", _DEFAULT_SEVERITY_THRESHOLD
    )
    rag_min = os.environ.get("NFR_ISSUE_RAG_MIN", "amber")

    findings = _load_findings(jsonl_path)
    results = sync_issues(
        findings,
        repo,
        dry_run=dry_run,
        rag_min=rag_min,
        severity_threshold=severity_threshold,
    )

    created = updated = closed = skipped = unchanged = errors = 0
    for r in results:
        action = r["action"]
        url = f" {r['url']}" if r.get("url") else ""
        reason = f" ({r['reason']})" if r.get("reason") else ""
        print(f"  [{action}] {r['title']}{url}{reason}")
        if action == "create":
            created += 1
        elif action == "update":
            updated += 1
        elif action == "close":
            closed += 1
        elif action == "skip":
            skipped += 1
        elif action == "unchanged":
            unchanged += 1
        elif action == "error":
            errors += 1

    print(
        f"\nsync: created={created} updated={updated} closed={closed} "
        f"skipped={skipped} unchanged={unchanged} errors={errors}"
    )


if __name__ == "__main__":
    main()
