# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Issue sync for NFR findings.

Syncs GitHub issues with current scan findings: creates new issues,
updates existing ones, and optionally closes resolved ones.  Each issue
carries three HTML-comment markers for machine-parseable deduplication.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess  # nosec B404
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_RAG_RANK = {"red": 0, "amber": 1, "green": 2}
_ISSUE_LABEL = "nfr-review"

_KEY_MARKER_PREFIX = "<!-- nfr-review:key="
_RULE_MARKER_PREFIX = "<!-- nfr-review:rule="
_RAG_MARKER_PREFIX = "<!-- nfr-review:rag="
_MARKER_SUFFIX = " -->"
_CLOSED_BY_TOOL_MARKER = "<!-- nfr-review:closed-by-tool -->"
_LEGACY_MARKER_PREFIX = "<!-- nfr-review:issue:"


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------


def _finding_key(finding: dict[str, Any]) -> str:
    content_hash = finding.get("content_hash", "")
    if content_hash:
        from nfr_review.models import _strip_line_from_locator

        file_path = _strip_line_from_locator(finding.get("evidence_locator", ""))
        parts = [
            finding.get("rule_id", ""),
            file_path,
            finding.get("pattern_tag", ""),
            content_hash,
        ]
    else:
        parts = [
            finding.get("rule_id", ""),
            finding.get("evidence_locator", ""),
            finding.get("pattern_tag", ""),
        ]
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:12]


# Legacy alias kept for backward compat (used by action_issues.py / tests).
_finding_fingerprint = _finding_key


# ---------------------------------------------------------------------------
# Marker helpers
# ---------------------------------------------------------------------------


def _extract_key(body: str) -> str | None:
    """Extract the nfr-review dedup key from an issue body.

    Supports both the new three-marker format and the legacy single marker.
    """
    for prefix in (_KEY_MARKER_PREFIX, _LEGACY_MARKER_PREFIX):
        if prefix in body:
            start = body.index(prefix) + len(prefix)
            end = body.index(_MARKER_SUFFIX, start)
            return body[start:end]
    return None


def _dedup_marker(finding: dict[str, Any]) -> str:
    """Legacy single-marker format (kept for backward compat)."""
    fp = _finding_key(finding)
    return f"{_LEGACY_MARKER_PREFIX}{fp}{_MARKER_SUFFIX}"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _severity_meets_threshold(severity: str, threshold: str) -> bool:
    return _SEVERITY_RANK.get(severity, 99) <= _SEVERITY_RANK.get(threshold, 1)


def _rag_meets_threshold(rag: str, rag_min: str) -> bool:
    return _RAG_RANK.get(rag, 99) <= _RAG_RANK.get(rag_min, 1)


def filter_findings(
    findings: list[dict[str, Any]],
    severity_threshold: str = "high",
    *,
    rag_min: str = "red",
) -> list[dict[str, Any]]:
    """Filter findings by RAG level and severity.

    Default ``rag_min="red"`` preserves legacy red-only behavior.
    Pass ``rag_min="amber"`` for the new sync default.
    """
    return [
        f
        for f in findings
        if _rag_meets_threshold(f.get("rag", "green"), rag_min)
        and _severity_meets_threshold(f.get("severity", "info"), severity_threshold)
    ]


# ---------------------------------------------------------------------------
# Title / body / labels
# ---------------------------------------------------------------------------


def generate_issue_title(finding: dict[str, Any]) -> str:
    """``[nfr-review] <rule_id>: <summary>`` (summary truncated to 60 chars)."""
    rule_id = finding.get("rule_id", "UNKNOWN")
    summary = finding.get("summary", "NFR finding")
    if len(summary) > 60:
        summary = summary[:57] + "..."
    return f"[nfr-review] {rule_id}: {summary}"


_RAG_EMOJI = {
    "red": ":red_circle:",
    "amber": ":orange_circle:",
    "green": ":green_circle:",
}


def generate_issue_body(finding: dict[str, Any]) -> str:
    """Render issue body with three-marker dedup header."""
    key = _finding_key(finding)
    rule_id = finding.get("rule_id", "")
    rag = finding.get("rag", "")
    severity = finding.get("severity", "")
    confidence = finding.get("confidence", "")
    band = finding.get("band", "")
    summary = finding.get("summary", "")
    recommendation = finding.get("recommendation", "")
    locator = finding.get("evidence_locator", "")
    collector = finding.get("collector_name", "")
    pattern_tag = finding.get("pattern_tag", "")

    emoji = _RAG_EMOJI.get(rag, rag)

    lines: list[str] = [
        f"{_KEY_MARKER_PREFIX}{key}{_MARKER_SUFFIX}",
        f"{_RULE_MARKER_PREFIX}{rule_id}{_MARKER_SUFFIX}",
        f"{_RAG_MARKER_PREFIX}{rag}{_MARKER_SUFFIX}",
        "",
        "## NFR Finding",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| **Rule** | `{rule_id}` |",
        f"| **RAG** | {emoji} {rag} |",
        f"| **Severity** | `{severity}` |",
        f"| **Confidence** | {confidence} |",
    ]
    if band:
        lines.append(f"| **Band** | {band} |")
    lines.append("")

    lines.extend(["### Summary", "", summary, ""])

    if recommendation:
        lines.extend(["### Recommendation", "", recommendation, ""])

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


def issue_labels(
    finding: dict[str, Any],
    extra_labels: list[str] | None = None,
) -> list[str]:
    labels = [_ISSUE_LABEL]
    severity = finding.get("severity", "")
    if severity:
        labels.append(f"severity:{severity}")
    if extra_labels:
        labels.extend(extra_labels)
    return labels


# ---------------------------------------------------------------------------
# GitHub CLI wrappers
# ---------------------------------------------------------------------------


def _gh_run(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 B607
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


_LABEL_COLORS: dict[str, str] = {
    "nfr-review": "0052CC",
    "severity:critical": "B60205",
    "severity:high": "D93F0B",
    "severity:medium": "FBCA04",
    "severity:low": "0E8A16",
    "severity:info": "C5DEF5",
}


def _ensure_labels(repo: str, labels: set[str]) -> None:
    """Create any labels that don't already exist in the repo."""
    if not labels:
        return

    try:
        result = _gh_run(["label", "list", "--repo", repo, "--json", "name", "--limit", "200"])
    except FileNotFoundError:
        return

    if result.returncode != 0:
        logger.warning("Could not list labels: %s", result.stderr.strip()[:120])
        return

    try:
        existing = {item["name"] for item in json.loads(result.stdout)}
    except (json.JSONDecodeError, KeyError):
        existing = set()

    for label in sorted(labels - existing):
        color = _LABEL_COLORS.get(label, "EDEDED")
        try:
            r = _gh_run(
                ["label", "create", label, "--repo", repo, "--color", color, "--force"]
            )
            if r.returncode == 0:
                logger.info("Created label %r in %s", label, repo)
            else:
                logger.warning("Failed to create label %r: %s", label, r.stderr.strip()[:120])
        except FileNotFoundError:
            return


def _fetch_nfr_issues(
    repo: str,
    *,
    state: str = "all",
) -> list[dict[str, Any]]:
    """Fetch nfr-review-labelled issues from GitHub."""
    try:
        result = _gh_run(
            [
                "issue",
                "list",
                "--repo",
                repo,
                "--label",
                _ISSUE_LABEL,
                "--state",
                state,
                "--json",
                "number,body,state,url",
                "--limit",
                "200",
            ]
        )
    except FileNotFoundError:
        return []

    if result.returncode != 0:
        return []

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def _issue_has_tool_close_comment(repo: str, issue_number: int) -> bool:
    """Check whether a closed issue was closed by the tool."""
    try:
        result = _gh_run(
            [
                "issue",
                "view",
                "--repo",
                repo,
                str(issue_number),
                "--json",
                "comments",
            ]
        )
    except FileNotFoundError:
        return False

    if result.returncode != 0:
        return False

    try:
        data = json.loads(result.stdout)
        return any(
            _CLOSED_BY_TOOL_MARKER in c.get("body", "") for c in data.get("comments", [])
        )
    except (json.JSONDecodeError, KeyError):
        return False


# ---------------------------------------------------------------------------
# sync_issues  — the new primary API
# ---------------------------------------------------------------------------


def sync_issues(
    findings: list[dict[str, Any]],
    repo: str,
    *,
    dry_run: bool = False,
    rag_min: str = "amber",
    severity_threshold: str = "high",
    extra_labels: list[str] | None = None,
    first_run_cap: int = 25,
    close_resolved: bool = True,
) -> list[dict[str, Any]]:
    """Sync GitHub issues with current scan findings.

    Returns a list of action dicts with keys:
        rule_id, title, action, url, reason
    where *action* is one of create/update/close/skip/unchanged/error.
    """
    filtered = filter_findings(
        findings,
        severity_threshold,
        rag_min=rag_min,
    )

    finding_by_key: dict[str, dict[str, Any]] = {}
    for f in filtered:
        finding_by_key[_finding_key(f)] = f

    if not dry_run and repo and finding_by_key:
        all_labels: set[str] = set()
        for f in finding_by_key.values():
            all_labels.update(issue_labels(f, extra_labels))
        _ensure_labels(repo, all_labels)

    all_issues = _fetch_nfr_issues(repo) if repo else []

    open_by_key: dict[str, dict[str, Any]] = {}
    closed_by_key: dict[str, dict[str, Any]] = {}
    for issue in all_issues:
        key = _extract_key(issue.get("body", ""))
        if key is None:
            continue
        if issue.get("state", "").upper() == "OPEN":
            open_by_key[key] = issue
        elif issue.get("state", "").upper() == "CLOSED":
            closed_by_key[key] = issue

    is_first_run = len(all_issues) == 0
    results: list[dict[str, Any]] = []
    create_count = 0

    for key, finding in finding_by_key.items():
        title = generate_issue_title(finding)
        rule_id = finding.get("rule_id", "")

        # --- open issue with same key → update (or unchanged) ---
        if key in open_by_key:
            existing = open_by_key[key]
            new_body = generate_issue_body(finding)
            if new_body.strip() == existing.get("body", "").strip():
                results.append(
                    _action(
                        rule_id, title, "unchanged", existing.get("url", ""), "body identical"
                    )
                )
                continue

            if dry_run:
                results.append(
                    _action(rule_id, title, "update", existing.get("url", ""), "body changed")
                )
                continue

            number = existing["number"]
            try:
                _gh_run(["issue", "edit", "--repo", repo, str(number), "--body", new_body])
                results.append(
                    _action(rule_id, title, "update", existing.get("url", ""), "body updated")
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                results.append(_action(rule_id, title, "error", "", "gh edit failed"))
            continue

        # --- closed issue with same key → skip if manually closed ---
        if key in closed_by_key:
            closed_issue = closed_by_key[key]
            if dry_run:
                results.append(
                    _action(
                        rule_id,
                        title,
                        "skip",
                        closed_issue.get("url", ""),
                        "previously closed",
                    )
                )
                continue

            if not _issue_has_tool_close_comment(repo, closed_issue["number"]):
                results.append(
                    _action(
                        rule_id,
                        title,
                        "skip",
                        closed_issue.get("url", ""),
                        "manually closed",
                    )
                )
                continue
            # Tool-closed and finding came back — fall through to create

        # --- create ---
        if is_first_run and create_count >= first_run_cap:
            results.append(
                _action(rule_id, title, "skip", "", f"first-run cap ({first_run_cap})")
            )
            continue

        if dry_run:
            results.append(_action(rule_id, title, "create", "", "new finding"))
            create_count += 1
            continue

        body = generate_issue_body(finding)
        labels = issue_labels(finding, extra_labels)
        label_args: list[str] = []
        for lbl in labels:
            label_args.extend(["--label", lbl])

        try:
            result = _gh_run(
                [
                    "issue",
                    "create",
                    "--repo",
                    repo,
                    "--title",
                    title,
                    "--body",
                    body,
                    *label_args,
                ]
            )
            if result.returncode == 0:
                results.append(
                    _action(rule_id, title, "create", result.stdout.strip(), "new finding")
                )
                create_count += 1
            else:
                results.append(
                    _action(rule_id, title, "error", "", result.stderr.strip()[:120])
                )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            results.append(_action(rule_id, title, "error", "", "gh create failed"))

    # --- close-resolved ---
    if close_resolved:
        for key, issue in open_by_key.items():
            if key in finding_by_key:
                continue
            number = issue["number"]
            url = issue.get("url", "")

            if dry_run:
                results.append(
                    _action("", f"#{number}", "close", url, "finding no longer present")
                )
                continue

            now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
            comment = (
                f"Finding no longer present in scan results as of {now}.\n\n"
                f"{_CLOSED_BY_TOOL_MARKER}"
            )
            try:
                _gh_run(
                    [
                        "issue",
                        "close",
                        "--repo",
                        repo,
                        str(number),
                        "--comment",
                        comment,
                    ]
                )
                results.append(
                    _action("", f"#{number}", "close", url, "finding no longer present")
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                results.append(_action("", f"#{number}", "error", url, "gh close failed"))

    return results


def _action(rule_id: str, title: str, action: str, url: str, reason: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "title": title,
        "action": action,
        "url": url,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Legacy API  — kept for backward compat with ``nfr-review issues <target>``
# ---------------------------------------------------------------------------


def find_existing_issues(repo: str) -> set[str]:
    """Query open issues for existing nfr-review dedup markers."""
    issues = _fetch_nfr_issues(repo, state="open")
    existing: set[str] = set()
    for issue in issues:
        key = _extract_key(issue.get("body", ""))
        if key is not None:
            existing.add(key)
    return existing


def file_issues(
    findings: list[dict[str, Any]],
    repo: str,
    *,
    dry_run: bool = False,
    severity_threshold: str = "high",
) -> list[dict[str, Any]]:
    """File GitHub issues for red findings above the severity threshold.

    Legacy create-only API.  Returns dicts with keys:
    rule_id, title, status (filed|skipped|dry_run|error), url.
    """
    filtered = filter_findings(findings, severity_threshold, rag_min="red")
    if not filtered:
        return []

    if not dry_run and repo:
        all_labels: set[str] = set()
        for f in filtered:
            all_labels.update(issue_labels(f))
        _ensure_labels(repo, all_labels)

    existing_fps = set() if dry_run else find_existing_issues(repo)

    results: list[dict[str, Any]] = []
    for finding in filtered:
        fp = _finding_key(finding)
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
            result = _gh_run(
                [
                    "issue",
                    "create",
                    "--repo",
                    repo,
                    "--title",
                    title,
                    "--body",
                    body,
                    *label_args,
                ]
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
    "sync_issues",
]
