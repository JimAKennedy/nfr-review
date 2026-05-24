# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Generate a PR comment from nfr-review JSONL output.

Reads a JSONL file produced by ``nfr-review run`` and emits a Markdown
comment suitable for posting to a pull request.  The comment includes a
RAG summary table, top findings, and a collapsible section with full
details.

Can be used as a CLI (``python scripts/action_comment.py output.jsonl``)
or imported as a library for testing.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Hidden marker used to find and update existing comments (sticky pattern).
COMMENT_MARKER = "<!-- nfr-review-comment -->"

# How many top red/amber findings to surface in the summary.
_TOP_FINDINGS_LIMIT = 5


def _load_records(jsonl_path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file and return all parsed records."""
    records: list[dict[str, Any]] = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _count_by_rag(records: list[dict[str, Any]]) -> dict[str, int]:
    """Count finding records by RAG status."""
    counts: dict[str, int] = {"red": 0, "amber": 0, "green": 0, "skipped": 0}
    for rec in records:
        if rec.get("record_type") != "finding":
            continue
        rag = rec.get("rag", "")
        if rag in counts:
            counts[rag] += 1
    return counts


def _rag_emoji(rag: str) -> str:
    return {"red": "\U0001f534", "amber": "\U0001f7e0", "green": "\U0001f7e2"}.get(rag, "")


def _status_line(counts: dict[str, int]) -> str:
    """Return a one-line status summary."""
    if counts["red"] > 0:
        return "\U0001f534 **Red findings detected** — review required"
    if counts["amber"] > 0:
        return "\U0001f7e0 **Amber findings detected** — review recommended"
    return "\U0001f7e2 **All clear** — no red or amber findings"


def _severity_badge(severity: str) -> str:
    return {"critical": "`critical`", "high": "`high`", "medium": "`medium`"}.get(
        severity, severity
    )


def _top_findings(records: list[dict[str, Any]], limit: int = _TOP_FINDINGS_LIMIT) -> str:
    """Return markdown for the top red/amber findings."""
    important = [
        r
        for r in records
        if r.get("record_type") == "finding" and r.get("rag") in ("red", "amber")
    ]
    if not important:
        return ""

    # Sort: red before amber, then by severity rank.
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    rag_order = {"red": 0, "amber": 1}
    important.sort(
        key=lambda r: (
            rag_order.get(r.get("rag", ""), 9),
            severity_order.get(r.get("severity", ""), 9),
        )
    )
    top = important[:limit]

    lines = ["### Top Findings", ""]
    lines.append("| RAG | Severity | Rule | Summary |")
    lines.append("|-----|----------|------|---------|")
    for f in top:
        rag = f.get("rag", "")
        sev = f.get("severity", "")
        rule = f.get("rule_id", "")
        summary = f.get("summary", "")
        # Truncate long summaries for the table.
        if len(summary) > 120:
            summary = summary[:117] + "..."
        lines.append(
            f"| {_rag_emoji(rag)} {rag} | {_severity_badge(sev)} | {rule} | {summary} |"
        )

    remaining = len(important) - limit
    if remaining > 0:
        lines.append("")
        lines.append(f"*... and {remaining} more red/amber finding(s)*")

    return "\n".join(lines)


def _full_details(records: list[dict[str, Any]]) -> str:
    """Return a collapsible section with all finding details."""
    findings = [r for r in records if r.get("record_type") == "finding"]
    if not findings:
        return ""

    lines = [
        "<details>",
        f"<summary>Full finding details ({len(findings)} findings)</summary>",
        "",
    ]

    for f in findings:
        rag = f.get("rag", "")
        rule = f.get("rule_id", "")
        summary = f.get("summary", "")
        recommendation = f.get("recommendation", "")
        severity = f.get("severity", "")
        locator = f.get("evidence_locator", "")

        lines.append(f"#### {_rag_emoji(rag)} {rule} ({rag}/{severity})")
        lines.append("")
        lines.append(f"**Summary:** {summary}")
        if recommendation:
            lines.append(f"**Recommendation:** {recommendation}")
        if locator:
            lines.append(f"**Location:** `{locator}`")
        lines.append("")

    lines.append("</details>")
    return "\n".join(lines)


def _tool_version(records: list[dict[str, Any]]) -> str:
    """Extract tool version from run_metadata, if present."""
    for rec in records:
        if rec.get("record_type") == "run_metadata":
            return rec.get("tool_version", "unknown")
    return "unknown"


def generate_comment(jsonl_path: Path) -> str:
    """Generate the full PR comment markdown from a JSONL file.

    Parameters
    ----------
    jsonl_path:
        Path to the nfr-review JSONL output file.

    Returns
    -------
    str
        Markdown string ready to be posted as a PR comment.
    """
    records = _load_records(jsonl_path)
    counts = _count_by_rag(records)
    version = _tool_version(records)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    total_findings = counts["red"] + counts["amber"] + counts["green"]

    parts: list[str] = [
        COMMENT_MARKER,
        "## NFR Review Results",
        "",
        _status_line(counts),
        "",
        "### RAG Summary",
        "",
        "| Status | Count |",
        "|--------|-------|",
        f"| \U0001f534 Red | {counts['red']} |",
        f"| \U0001f7e0 Amber | {counts['amber']} |",
        f"| \U0001f7e2 Green | {counts['green']} |",
        f"| **Total** | **{total_findings}** |",
        "",
    ]

    top = _top_findings(records)
    if top:
        parts.append(top)
        parts.append("")

    details = _full_details(records)
    if details:
        parts.append(details)
        parts.append("")

    parts.append("---")
    parts.append(f"*Generated by nfr-review v{version} at {timestamp}*")

    return "\n".join(parts) + "\n"


def main() -> None:
    """CLI entry point: read JSONL path from argv, print comment to stdout."""
    if len(sys.argv) < 2:
        print("usage: action_comment.py <jsonl-path>", file=sys.stderr)
        sys.exit(1)

    jsonl_path = Path(sys.argv[1])
    if not jsonl_path.exists():
        print(f"error: file not found: {jsonl_path}", file=sys.stderr)
        sys.exit(1)

    print(generate_comment(jsonl_path))


if __name__ == "__main__":
    main()
