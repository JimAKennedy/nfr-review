# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Issue filing for red NFR findings.

Generates and files GitHub issues for findings that meet a severity
threshold.  Each issue is tagged with a hidden deduplication marker
so subsequent runs skip already-filed findings.
"""

from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404
from typing import Any

_DEFAULT_SEVERITY_THRESHOLD = "high"
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_ISSUE_LABEL = "nfr-review"


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
    """Filter findings to red ones meeting the severity threshold."""
    return [
        f
        for f in findings
        if f.get("rag") == "red"
        and _severity_meets_threshold(f.get("severity", "info"), severity_threshold)
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
            "*Filed automatically by [nfr-review](https://github.com/nfr-review/nfr-review).*",
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
    """Query open issues for existing nfr-review dedup markers."""
    try:
        result = subprocess.run(  # nosec B603 B607
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

    Returns a list of dicts with keys: rule_id, title, status, url.
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
            result = subprocess.run(  # nosec B603 B607
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


__all__ = [
    "file_issues",
    "filter_findings",
    "generate_issue_body",
    "generate_issue_title",
    "issue_labels",
]
