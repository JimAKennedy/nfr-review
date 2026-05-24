# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Generate and file GitHub issues for red NFR findings.

Reads a JSONL file produced by ``nfr-review run`` and creates GitHub issues
for findings that meet the severity threshold.  Each issue is tagged with a
hidden deduplication marker so subsequent runs skip already-filed findings.

Can be used as a CLI (``python scripts/action_issues.py output.jsonl``)
or imported as a library for testing.

Environment variables consumed (GitHub Actions context):
    GITHUB_REPOSITORY — owner/repo for issue filing (required for filing)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_DEFAULT_SEVERITY_THRESHOLD = "high"
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_ISSUE_LABEL = "nfr-review"


def _load_findings(jsonl_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("record_type") == "finding" and rec.get("rag") == "red":
                records.append(rec)
    return records


def _finding_fingerprint(finding: dict[str, Any]) -> str:
    parts = [
        finding.get("rule_id", ""),
        finding.get("evidence_locator", ""),
        finding.get("pattern_tag", ""),
    ]
    key = ":".join(parts)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _dedup_marker(finding: dict[str, Any]) -> str:
    fp = _finding_fingerprint(finding)
    return f"<!-- nfr-review:issue:{fp} -->"


def _severity_meets_threshold(severity: str, threshold: str) -> bool:
    return _SEVERITY_RANK.get(severity, 99) <= _SEVERITY_RANK.get(threshold, 1)


def filter_findings(
    findings: list[dict[str, Any]],
    severity_threshold: str = _DEFAULT_SEVERITY_THRESHOLD,
) -> list[dict[str, Any]]:
    """Filter red findings to those meeting the severity threshold."""
    return [
        f
        for f in findings
        if _severity_meets_threshold(f.get("severity", "info"), severity_threshold)
    ]


def generate_issue_title(finding: dict[str, Any]) -> str:
    rule_id = finding.get("rule_id", "UNKNOWN")
    summary = finding.get("summary", "NFR finding")
    title = f"[NFR] {rule_id}: {summary}"
    if len(title) > 120:
        title = title[:117] + "..."
    return title


def generate_issue_body(finding: dict[str, Any]) -> str:
    marker = _dedup_marker(finding)
    rule_id = finding.get("rule_id", "")
    severity = finding.get("severity", "")
    summary = finding.get("summary", "")
    recommendation = finding.get("recommendation", "")
    locator = finding.get("evidence_locator", "")
    collector = finding.get("collector_name", "")
    confidence = finding.get("confidence", "")
    pattern_tag = finding.get("pattern_tag", "")

    lines = [
        marker,
        "",
        "## NFR Finding",
        "",
        f"**Rule:** `{rule_id}`",
        f"**Severity:** `{severity}`",
        "**RAG:** :red_circle: red",
        f"**Confidence:** {confidence}",
        "",
        "### Summary",
        "",
        summary,
        "",
    ]

    if recommendation:
        lines.extend(
            [
                "### Recommendation",
                "",
                recommendation,
                "",
            ]
        )

    lines.extend(
        [
            "### Evidence",
            "",
            f"**Location:** `{locator}`",
            f"**Collector:** `{collector}`",
            f"**Pattern:** `{pattern_tag}`",
            "",
            "---",
            "*Filed automatically by "
            "[nfr-review](https://github.com/nfr-review/nfr-review) "
            "GitHub Action.*",
        ]
    )

    return "\n".join(lines) + "\n"


def issue_labels(finding: dict[str, Any]) -> list[str]:
    labels = [_ISSUE_LABEL]
    severity = finding.get("severity", "")
    if severity:
        labels.append(f"severity:{severity}")
    return labels


def find_existing_issues(repo: str) -> set[str]:
    """Query open issues for existing nfr-review dedup markers.

    Returns a set of fingerprints that already have open issues.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                repo,
                "--label",
                _ISSUE_LABEL,
                "--state",
                "open",
                "--json",
                "body",
                "--limit",
                "200",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return set()

    if result.returncode != 0:
        return set()

    existing: set[str] = set()
    try:
        issues = json.loads(result.stdout)
    except json.JSONDecodeError:
        return set()

    for issue in issues:
        body = issue.get("body", "")
        if "<!-- nfr-review:issue:" in body:
            start = body.index("<!-- nfr-review:issue:") + len("<!-- nfr-review:issue:")
            end = body.index(" -->", start)
            existing.add(body[start:end])
    return existing


def file_issues(
    findings: list[dict[str, Any]],
    repo: str,
    *,
    dry_run: bool = False,
    severity_threshold: str = _DEFAULT_SEVERITY_THRESHOLD,
) -> list[dict[str, Any]]:
    """File GitHub issues for red findings above the severity threshold.

    Returns a list of dicts with keys: rule_id, title, status (filed|skipped|dry_run), url.
    """
    filtered = filter_findings(findings, severity_threshold)
    if not filtered:
        return []

    existing_fps = set() if dry_run else find_existing_issues(repo)

    results: list[dict[str, Any]] = []
    for finding in filtered:
        fp = _finding_fingerprint(finding)
        title = generate_issue_title(finding)

        if fp in existing_fps:
            results.append(
                {
                    "rule_id": finding.get("rule_id", ""),
                    "title": title,
                    "status": "skipped",
                    "url": "",
                }
            )
            continue

        if dry_run:
            results.append(
                {
                    "rule_id": finding.get("rule_id", ""),
                    "title": title,
                    "status": "dry_run",
                    "url": "",
                }
            )
            continue

        body = generate_issue_body(finding)
        labels = issue_labels(finding)
        label_args: list[str] = []
        for lbl in labels:
            label_args.extend(["--label", lbl])

        try:
            result = subprocess.run(
                [
                    "gh",
                    "issue",
                    "create",
                    "--repo",
                    repo,
                    "--title",
                    title,
                    "--body",
                    body,
                    *label_args,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            url = result.stdout.strip() if result.returncode == 0 else ""
            status = "filed" if result.returncode == 0 else "error"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            url = ""
            status = "error"

        results.append(
            {
                "rule_id": finding.get("rule_id", ""),
                "title": title,
                "status": status,
                "url": url,
            }
        )

    return results


def main() -> None:
    """CLI entry point: read JSONL path from argv, file issues or print dry-run."""
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

    findings = _load_findings(jsonl_path)
    results = file_issues(
        findings,
        repo,
        dry_run=dry_run,
        severity_threshold=severity_threshold,
    )

    filed = sum(1 for r in results if r["status"] == "filed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    dry = sum(1 for r in results if r["status"] == "dry_run")
    errors = sum(1 for r in results if r["status"] == "error")

    for r in results:
        status = r["status"]
        url = f" {r['url']}" if r["url"] else ""
        print(f"  [{status}] {r['title']}{url}")

    if dry_run:
        print(f"\ndry run: {dry} issue(s) would be filed")
    else:
        print(f"\nfiled={filed} skipped={skipped} errors={errors}")


if __name__ == "__main__":
    main()
