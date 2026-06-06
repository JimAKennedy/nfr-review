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

# GitHub enforces a 65536-character limit on comment bodies.  Leave headroom
# for the surrounding markdown wrapper that create-or-update-comment adds.
_MAX_COMMENT_LENGTH = 65_000


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
    """Count finding records by RAG status, excluding suppressed findings."""
    counts: dict[str, int] = {"red": 0, "amber": 0, "green": 0, "skipped": 0}
    for rec in records:
        if rec.get("record_type") != "finding":
            continue
        if rec.get("suppressed") is True:
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
        if r.get("record_type") == "finding"
        and r.get("rag") in ("red", "amber")
        and r.get("suppressed") is not True
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
    findings = [
        r
        for r in records
        if r.get("record_type") == "finding" and r.get("suppressed") is not True
    ]
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


def _classify_records(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition finding records by classification tag.

    Returns (new, shifted, resolved) lists. If no classification tags are
    present, all findings are treated as new (backward compat).
    """
    new: list[dict[str, Any]] = []
    shifted: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []

    findings = [r for r in records if r.get("record_type") == "finding"]
    has_classification = any(r.get("classification") for r in findings)

    if not has_classification:
        return findings, [], []

    for r in findings:
        cls = r.get("classification", "new")
        if cls == "shifted":
            shifted.append(r)
        elif cls == "resolved":
            resolved.append(r)
        elif cls == "baseline":
            pass
        else:
            new.append(r)

    return new, shifted, resolved


def _classification_summary(
    new: list[dict[str, Any]],
    shifted: list[dict[str, Any]],
    resolved: list[dict[str, Any]],
) -> str:
    """One-line summary of classified findings."""
    parts = [f"**{len(new)} new**"]
    if shifted:
        parts.append(f"{len(shifted)} shifted")
    if resolved:
        parts.append(f"{len(resolved)} resolved")
    return " | ".join(parts)


def _shifted_section(shifted: list[dict[str, Any]]) -> str:
    """Render a collapsible section for shifted findings."""
    if not shifted:
        return ""
    lines = [
        "<details>",
        f"<summary>Shifted findings ({len(shifted)})"
        " — line numbers changed, no action needed</summary>",
        "",
        "| Rule | Pattern | Old Location | New Location |",
        "|------|---------|-------------|-------------|",
    ]
    for r in shifted:
        rule = r.get("rule_id", "")
        tag = r.get("pattern_tag", "")
        old_loc = r.get("baseline_locator", "?")
        new_loc = r.get("evidence_locator", "?")
        lines.append(f"| {rule} | {tag} | `{old_loc}` | `{new_loc}` |")
    lines.append("")
    lines.append("</details>")
    return "\n".join(lines)


def _resolved_section(resolved: list[dict[str, Any]]) -> str:
    """Render a collapsible section for resolved findings."""
    if not resolved:
        return ""
    lines = [
        "<details>",
        f"<summary>✅ Resolved findings ({len(resolved)}) — no longer present</summary>",
        "",
        "| Rule | Pattern | Last Location |",
        "|------|---------|--------------|",
    ]
    for r in resolved:
        rule = r.get("rule_id", "")
        tag = r.get("pattern_tag", "")
        loc = r.get("evidence_locator", "?")
        lines.append(f"| {rule} | {tag} | `{loc}` |")
    lines.append("")
    lines.append("</details>")
    return "\n".join(lines)


def _suppressed_count(records: list[dict[str, Any]]) -> int:
    """Count finding records tagged as suppressed."""
    return sum(
        1 for r in records if r.get("record_type") == "finding" and r.get("suppressed") is True
    )


def _tool_version(records: list[dict[str, Any]]) -> str:
    """Extract tool version from run_metadata, if present."""
    for rec in records:
        if rec.get("record_type") == "run_metadata":
            return rec.get("tool_version", "unknown")
    return "unknown"


def _truncation_notice(total_findings: int) -> str:
    """Return a notice when the full details section is too large for a PR comment."""
    return (
        f"> **Note:** Full finding details ({total_findings} findings) exceeded GitHub's "
        "comment size limit and were omitted. Download the JSONL artifact from "
        "the workflow run for the complete report."
    )


def generate_comment(jsonl_path: Path) -> str:
    """Generate the full PR comment markdown from a JSONL file.

    Parameters
    ----------
    jsonl_path:
        Path to the nfr-review JSONL output file.

    Returns
    -------
    str
        Markdown string ready to be posted as a PR comment.  If the full
        details section would push the comment past GitHub's 65 536-character
        limit, it is replaced with a note directing readers to the JSONL
        artifact.
    """
    records = _load_records(jsonl_path)
    version = _tool_version(records)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    new_records, shifted_records, resolved_records = _classify_records(records)
    has_classification = bool(shifted_records or resolved_records)

    # Actionable findings only (excludes baseline/resolved pre-existing issues).
    actionable = new_records + shifted_records
    counts = _count_by_rag(actionable)

    suppressed_count = _suppressed_count(records)

    total_findings = counts["red"] + counts["amber"] + counts["green"]

    parts: list[str] = [
        COMMENT_MARKER,
        "## NFR Review Results",
        "",
        _status_line(counts),
        "",
    ]

    if has_classification:
        parts.append(_classification_summary(new_records, shifted_records, resolved_records))
        parts.append("")

    if suppressed_count > 0:
        parts.append(
            f"*{suppressed_count} finding(s) suppressed via inline `nfr-review:skip` markers*"
        )
        parts.append("")

    parts.extend(
        [
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
    )

    top = _top_findings(actionable)
    if top:
        parts.append(top)
        parts.append("")

    details = _full_details(actionable)
    if details:
        parts.append(details)
        parts.append("")

    if has_classification:
        shifted_sec = _shifted_section(shifted_records)
        if shifted_sec:
            parts.append(shifted_sec)
            parts.append("")

        resolved_sec = _resolved_section(resolved_records)
        if resolved_sec:
            parts.append(resolved_sec)
            parts.append("")

    parts.append("---")
    parts.append(f"*Generated by nfr-review v{version} at {timestamp}*")

    comment = "\n".join(parts) + "\n"

    if len(comment) <= _MAX_COMMENT_LENGTH:
        return comment

    # Rebuild without the full details section.
    parts_truncated: list[str] = []
    for part in parts:
        if part.startswith("<details>"):
            continue
        parts_truncated.append(part)

    # Insert truncation notice before the footer.
    footer_idx = len(parts_truncated) - 2  # before "---"
    parts_truncated.insert(footer_idx, _truncation_notice(total_findings))
    parts_truncated.insert(footer_idx + 1, "")

    return "\n".join(parts_truncated) + "\n"


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
