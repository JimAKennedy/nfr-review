"""Markdown report renderer for nfr-review."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from nfr_review.models import RAG, Finding, Severity
from nfr_review.output.classify import partition_findings

if TYPE_CHECKING:
    from nfr_review.engine import RunResult
    from nfr_review.output.pytest_runner import PytestResult

_RAG_ORDER: tuple[RAG, ...] = ("red", "amber", "green")
_SEVERITY_ORDER: tuple[Severity, ...] = ("critical", "high", "medium", "low", "info")


def _summary_table(findings: list[Finding], title: str) -> str:
    """Render a RAG x severity count table."""
    counts: Counter[tuple[RAG, Severity]] = Counter()
    for f in findings:
        counts[(f.rag, f.severity)] += 1

    lines = [f"### {title}", "", "| RAG | Critical | High | Medium | Low | Info | Total |"]
    lines.append("|-----|----------|------|--------|-----|------|-------|")

    for rag in _RAG_ORDER:
        row_total = 0
        cells = []
        for sev in _SEVERITY_ORDER:
            n = counts.get((rag, sev), 0)
            row_total += n
            cells.append(str(n) if n else "-")
        lines.append(f"| {rag} | {' | '.join(cells)} | {row_total} |")

    total = len(findings)
    lines.append(f"| **Total** | | | | | | **{total}** |")
    lines.append("")
    return "\n".join(lines)


def _findings_section(findings: list[Finding], heading: str) -> str:
    """Render a findings section grouped by RAG."""
    if not findings:
        return f"## {heading}\n\nNo findings.\n"

    lines = [f"## {heading}", ""]
    by_rag: dict[RAG, list[Finding]] = {}
    for f in findings:
        by_rag.setdefault(f.rag, []).append(f)

    for rag in _RAG_ORDER:
        group = by_rag.get(rag, [])
        if not group:
            continue
        lines.append(f"### {rag.upper()} ({len(group)})")
        lines.append("")
        for f in group:
            lines.append(f"- **[{f.rule_id}]** {f.summary}")
            lines.append(f"  - Severity: {f.severity} | Confidence: {f.confidence:.0%}")
            lines.append(f"  - Location: `{f.evidence_locator}`")
            lines.append(f"  - Recommendation: {f.recommendation}")
            lines.append("")

    return "\n".join(lines)


def _test_results_section(pytest_result: PytestResult | None) -> str:
    """Render test execution results."""
    if pytest_result is None:
        return "## Test Results\n\nTest execution was not performed.\n"

    if pytest_result.exit_code == -1:
        return f"## Test Results\n\n> ⚠️ {pytest_result.raw_output}\n"

    all_green = pytest_result.failed == 0 and pytest_result.errors == 0
    status = "✅ PASSED" if all_green else "❌ FAILED"
    lines = [
        "## Test Results",
        "",
        f"**Status:** {status}",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Passed | {pytest_result.passed} |",
        f"| Failed | {pytest_result.failed} |",
        f"| Skipped | {pytest_result.skipped} |",
        f"| Errors | {pytest_result.errors} |",
        f"| Duration | {pytest_result.duration_seconds:.2f}s |",
        "",
    ]

    if pytest_result.warnings:
        lines.append(f"Warnings: {', '.join(pytest_result.warnings)}")
        lines.append("")

    return "\n".join(lines)


def _skipped_rules_section(nfr_result: RunResult, hygiene_result: RunResult | None) -> str:
    """Render skipped rules from run metadata."""
    skipped: list[dict[str, str]] = []
    if nfr_result.run_metadata:
        skipped.extend(nfr_result.run_metadata.rules_skipped)
    if hygiene_result and hygiene_result.run_metadata:
        skipped.extend(hygiene_result.run_metadata.rules_skipped)

    if not skipped:
        return ""

    lines = ["## Skipped Rules", "", "| Rule | Reason |", "|------|--------|"]
    for entry in skipped:
        rule_id = entry.get("rule_id", "unknown")
        reason = entry.get("reason", "")
        lines.append(f"| {rule_id} | {reason} |")
    lines.append("")
    return "\n".join(lines)


def render_markdown_report(
    *,
    nfr_result: RunResult,
    hygiene_result: RunResult | None = None,
    pytest_result: PytestResult | None = None,
    deps_section: str = "",
    title: str = "NFR Review Report",
) -> str:
    """Render a complete Markdown report from scan results.

    Partitions all findings into source and test sections, renders summary
    tables, and includes test execution results and provenance metadata.
    """
    all_findings = list(nfr_result.findings)
    if hygiene_result:
        all_findings.extend(hygiene_result.findings)

    source_findings, test_findings = partition_findings(all_findings)

    sections: list[str] = []

    # Header with provenance
    sections.append(f"# {title}")
    sections.append("")

    meta = nfr_result.run_metadata
    if meta:
        sections.append("## Provenance")
        sections.append("")
        sections.append(f"- **Tool version:** {meta.tool_version}")
        sections.append(f"- **Target:** `{meta.target_repo}`")
        sections.append(f"- **Timestamp:** {meta.timestamp}")
        if meta.git_sha:
            dirty = " (dirty)" if meta.git_dirty else ""
            sections.append(f"- **Git SHA:** `{meta.git_sha}`{dirty}")
        if meta.git_branch:
            sections.append(f"- **Branch:** {meta.git_branch}")
        if meta.git_error:
            sections.append(f"- **Git error:** {meta.git_error}")
        sections.append("")

    # Summary tables
    sections.append(_summary_table(all_findings, "Overall Summary"))
    sections.append(_summary_table(source_findings, "Source Code Summary"))
    sections.append(_summary_table(test_findings, "Test Code Summary"))

    # Test results
    sections.append(_test_results_section(pytest_result))

    # Dependency analysis
    if deps_section:
        sections.append(deps_section)

    # Findings by region
    sections.append(_findings_section(source_findings, "Source Code Findings"))
    sections.append(_findings_section(test_findings, "Test Code Findings"))

    # Skipped rules
    skipped_section = _skipped_rules_section(nfr_result, hygiene_result)
    if skipped_section:
        sections.append(skipped_section)

    return "\n".join(sections)
