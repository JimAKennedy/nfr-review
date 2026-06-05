# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Markdown report renderer for nfr-review."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from nfr_review.models import RAG, Finding, Severity
from nfr_review.output.classify import partition_findings
from nfr_review.scoring import _extract_category

if TYPE_CHECKING:
    from nfr_review.engine import RunResult
    from nfr_review.output.pytest_runner import PytestResult
    from nfr_review.scoring import MaturityScore, ScoreTrend
    from nfr_review.suppression import SuppressionInfo

_RAG_ORDER: tuple[RAG, ...] = ("red", "amber", "green")
_SEVERITY_ORDER: tuple[Severity, ...] = ("critical", "high", "medium", "low", "info")


def _category_severity_table(findings: list[Finding], title: str) -> str:
    """Render a category x severity count table."""
    counts: dict[str, Counter[Severity]] = defaultdict(Counter)
    for f in findings:
        cat = _extract_category(f.rule_id)
        counts[cat][f.severity] += 1

    categories = sorted(counts.keys())
    col_totals: Counter[Severity] = Counter()

    lines = [
        f"### {title}",
        "",
        "| Category | Critical | High | Medium | Low | Info | Total |",
    ]
    lines.append("|----------|----------|------|--------|-----|------|-------|")

    for cat in categories:
        row_total = 0
        cells = []
        for sev in _SEVERITY_ORDER:
            n = counts[cat].get(sev, 0)
            row_total += n
            col_totals[sev] += n
            cells.append(str(n) if n else "-")
        lines.append(f"| {cat} | {' | '.join(cells)} | {row_total} |")

    grand_total = sum(col_totals.values())
    total_cells = []
    for sev in _SEVERITY_ORDER:
        n = col_totals.get(sev, 0)
        total_cells.append(f"**{n}**" if n else "-")
    lines.append(f"| **Total** | {' | '.join(total_cells)} | **{grand_total}** |")
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


def _suppression_audit_section(
    suppressed: list[tuple[Finding, SuppressionInfo]],
) -> str:
    """Render a suppression audit section listing suppressed findings."""
    if not suppressed:
        return ""

    with_reason = [(f, i) for f, i in suppressed if i.reason]
    without_reason = [(f, i) for f, i in suppressed if not i.reason]

    lines = [
        "## Suppression Audit",
        "",
        f"**Total suppressed:** {len(suppressed)} "
        f"({len(with_reason)} with justification, "
        f"{len(without_reason)} without)",
        "",
    ]

    if without_reason:
        lines.append(
            "> **Warning:** "
            f"{len(without_reason)} suppression(s) have no justification. "
            "Add `reason: <ticket or explanation>` to the marker for audit compliance."
        )
        lines.append("")

    lines.append("| Rule | Location | Justification |")
    lines.append("|------|----------|---------------|")
    for finding, info in suppressed:
        reason_text = info.reason or "*no justification provided*"
        lines.append(f"| {finding.rule_id} | `{finding.evidence_locator}` | {reason_text} |")
    lines.append("")
    return "\n".join(lines)


def _methodology_appendix() -> str:
    """Render the scoring methodology appendix as Markdown."""
    lines: list[str] = []
    _a = lines.append

    _a("## Appendix — Scoring Methodology")
    _a("")
    _a("### RAG x Severity Matrix")
    _a("")
    _a("Each finding is classified along two independent axes:")
    _a("")
    _a(
        "- **RAG (Red / Amber / Green):** indicates whether"
        " the finding meets, partially meets, or fails the"
        " requirement."
    )
    _a(
        "- **Severity (Critical / High / Medium / Low / Info):**"
        " indicates the potential impact if the finding is left"
        " unaddressed."
    )
    _a("")
    _a(
        "The summary table at the top of the report shows"
        " findings grouped by category and severity, providing"
        " a quick view of which areas have the most findings"
        " and their urgency."
    )
    _a("")
    _a("### Design Maturity Score")
    _a("")
    _a(
        "The Design Maturity Score is a deterministic metric"
        " computed from the scan findings."
        " It is **not** an AI-generated opinion."
    )
    _a("")
    _a("**Per-category scoring**")
    _a("")
    _a(
        "Every finding's rule ID is mapped to a category"
        " (e.g. *security*, *observability*, *performance*,"
        " *ops*, or a hygiene/patching prefix). Each finding"
        " deducts points from the category's starting score"
        " of 100, weighted by severity:"
    )
    _a("")
    _a("| Severity | Deduction |")
    _a("|----------|-----------|")
    _a("| Critical | −15 |")
    _a("| High | −8 |")
    _a("| Medium | −3 |")
    _a("| Low | −1 |")
    _a("| Info | 0 |")
    _a("")
    _a("The category score is clamped to a minimum of 0.")
    _a("")
    _a("**Overall score**")
    _a("")
    _a(
        "The overall Design Maturity Score is the arithmetic"
        " mean of all category scores. Categories with many"
        " findings will pull the average down; categories"
        " with few or no findings score 100."
    )
    _a("")
    _a("**Grade scale**")
    _a("")
    _a("| Grade | Score Range |")
    _a("|-------|------------|")
    _a("| A | 90 – 100 |")
    _a("| B | 75 – 89 |")
    _a("| C | 60 – 74 |")
    _a("| D | 45 – 59 |")
    _a("| F | 0 – 44 |")
    _a("")
    _a("**Rules Coverage**")
    _a("")
    _a(
        "The fraction of available rules that were executed"
        " during the scan. Rules may be skipped when their"
        " prerequisites are absent (e.g. no Dockerfile means"
        " Dockerfile rules are skipped). A lower coverage"
        " percentage does not indicate a worse score — it"
        " means fewer rule categories were applicable to"
        " the scanned repository."
    )
    _a("")
    _a("### Category Definitions")
    _a("")
    _a(
        "Categories are assigned automatically from each"
        " rule's ID. There are three groups: core NFR"
        " categories (from keyword matching), repository"
        " hygiene (prefix `HYG-`), and patching readiness"
        " (prefix `PATCH-`)."
    )

    def _cat_table(
        heading: str,
        rows: list[tuple[str, str, str]],
    ) -> None:
        _a("")
        _a(f"#### {heading}")
        _a("")
        _a("| Category | Scope | What maturity looks like |")
        _a("|----------|-------|-------------------------|")
        for cat, scope, maturity in rows:
            _a(f"| {cat} | {scope} | {maturity} |")

    _cat_table(
        "Core NFR Categories",
        [
            (
                "**security**",
                "Auth, secrets, supply-chain pinning, PII, container user directives",
                "No leaked secrets, pinned images/providers, no PII in logs, least-privilege",
            ),
            (
                "**observability**",
                "Tracing (OTel), structured logging, correlation IDs, health probes",
                "Full trace pipeline, structured logs with "
                "correlation IDs, separate health/readiness",
            ),
            (
                "**performance**",
                "Timeouts, thread pools, goroutine leaks, async correctness, dep instability",
                "Explicit timeouts, bounded pools, no fire-and-forget async, stable dep graph",
            ),
            (
                "**ops**",
                "Containers, K8s, Helm, CI, service-mesh, "
                "Terraform, build tooling, ADR governance",
                "Multi-stage Dockerfiles, resource limits, "
                "network policies, CI gates, current ADRs",
            ),
        ],
    )

    _cat_table(
        "Repository Hygiene Categories (HYG-)",
        [
            (
                "**HYG-BLD**",
                "Build system, versioning, entry points, pre-commit, code debt",
                "Reproducible build, pinned deps, semver, lint + format hooks",
            ),
            (
                "**HYG-CI**",
                "CI pipeline, test/lint/SAST stages, coverage gates, action pinning",
                "All quality gates present, SHA-pinned actions, coverage enforced",
            ),
            (
                "**HYG-COM**",
                "README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CHANGELOG, CODEOWNERS",
                "All community health files present with substantive content",
            ),
            (
                "**HYG-DOC**",
                "API docs, docs directory, package metadata",
                "Published API docs, guides, complete metadata (description, license, URLs)",
            ),
            (
                "**HYG-LIC**",
                "Copyleft risk, license headers, NOTICE, SPDX identifiers",
                "No unexpected copyleft, consistent headers, machine-readable SPDX",
            ),
            (
                "**HYG-PRV**",
                "PII patterns, internal reference leaks, tracking IDs",
                "No PII in source, no internal URLs leaked, no tracking IDs in public code",
            ),
        ],
    )

    _cat_table(
        "Patching Readiness Categories (PATCH-)",
        [
            (
                "**PATCH-ARCH**",
                "Singleton avoidance, graceful shutdown, PDB config, update strategy",
                "No single-replica deploys, shutdown handlers, PDBs, rolling updates",
            ),
            (
                "**PATCH-DEPS**",
                "Version pinning, vuln scanning, automated update paths",
                "Pinned deps with lock files, vuln scanning in CI, clear upgrade path",
            ),
            (
                "**PATCH-HEALTH**",
                "Probe separation, startup probes, trivial-probe detection, termination",
                "Distinct startup probes, non-trivial health checks, pre-stop hooks",
            ),
            (
                "**PATCH-ROLL**",
                "Rollback docs, CI rollback tests, forward migration support",
                "Documented rollback, tested in CI, forward-compatible migrations",
            ),
            (
                "**PATCH-SCOPE**",
                "Change-set sizing, blast-radius analysis",
                "Small focused changesets with clear scope boundaries",
            ),
            (
                "**PATCH-TELEM**",
                "Deployment metrics, canary signals, rollout observability",
                "Deploy success/failure metrics, canary signals, real-time dashboards",
            ),
            (
                "**PATCH-TRAFFIC**",
                "Traffic shifting, circuit breakers, rate limiting",
                "Progressive traffic shifting, circuit breakers, rate limiting configured",
            ),
        ],
    )

    _a("")
    _a("### Executive Summary (PDF only)")
    _a("")
    _a(
        "When an Anthropic API key is configured, the PDF"
        " report includes an AI-generated Executive Summary"
        " with its own overall score (0–100). This score is"
        " a holistic LLM assessment of project fitness and"
        " **may differ from the deterministic Design Maturity"
        " Score**. It considers factors beyond individual rule"
        " findings, such as the overall pattern of issues,"
        " test coverage, and dependency health. The verdict"
        " (Fit / Conditional / Unfit) reflects a go/no-go"
        " recommendation."
    )

    return "\n".join(lines) + "\n"


def render_score_section(score: MaturityScore, trend: ScoreTrend | None = None) -> str:
    """Render a Design Maturity Score section as Markdown.

    Parameters
    ----------
    score:
        The computed maturity score.
    trend:
        Optional trend comparison against a baseline.

    Returns
    -------
    str
        Markdown fragment for the score section.
    """
    lines = [
        "## Design Maturity Score",
        "",
        f"**Overall: {score.overall}/100 (Grade: {score.grade})**",
        "",
        (
            "The overall score is the arithmetic mean of the category scores below."
            " Each category starts at 100 and is reduced by severity-weighted"
            " deductions (critical −15, high −8, medium −3, low −1, info 0),"
            " clamped to a floor of 0."
            " See **Appendix — Scoring Methodology** for full details."
        ),
        "",
        f"Rules Coverage: {score.rules_coverage:.0%}",
        "",
    ]

    if score.category_scores:
        lines.append("### Category Breakdown")
        lines.append("")
        lines.append("| Category | Score |")
        lines.append("|----------|-------|")
        for cat in sorted(score.category_scores):
            cat_score = score.category_scores[cat]
            lines.append(f"| {cat} | {cat_score}/100 |")
        lines.append("")

    if trend is not None:
        lines.append("### Trend (vs baseline)")
        lines.append("")
        label = trend.direction.capitalize()
        lines.append(f"{label}: {trend.delta:+d} points (was {trend.baseline_score})")
        lines.append("")

        if trend.category_deltas:
            lines.append("| Category | Current | Baseline | Delta |")
            lines.append("|----------|---------|----------|-------|")
            for cat in sorted(trend.category_deltas):
                cur = score.category_scores.get(cat, 100)
                bl = cur - trend.category_deltas[cat]
                delta = trend.category_deltas[cat]
                lines.append(f"| {cat} | {cur} | {bl} | {delta:+d} |")
            lines.append("")

    return "\n".join(lines)


def render_markdown_report(
    *,
    nfr_result: RunResult,
    hygiene_result: RunResult | None = None,
    pytest_result: PytestResult | None = None,
    deps_section: str = "",
    jdepend_section: str = "",
    adr_section: str = "",
    derived_adrs_section: str = "",
    title: str = "NFR Review Report",
    diagrams: dict[str, str] | None = None,
    score_section: str = "",
    suppressed_findings: list[tuple[Finding, SuppressionInfo]] | None = None,
) -> str:
    """Render a complete Markdown report from scan results.

    Partitions all findings into source and test sections, renders summary
    tables, and includes test execution results and provenance metadata.
    When ``suppressed_findings`` is provided, a Suppression Audit section
    lists every suppressed finding with its justification (or a warning
    when missing).
    """
    all_findings = list(nfr_result.findings)
    if hygiene_result:
        all_findings.extend(hygiene_result.findings)

    source_findings, test_findings = partition_findings(all_findings)

    sections: list[str] = []

    # Header with provenance
    meta = nfr_result.run_metadata
    repo_label = Path(meta.target_repo).name if meta else ""
    if repo_label:
        sections.append(f"# {title} — {repo_label}")
    else:
        sections.append(f"# {title}")
    sections.append("")

    if meta:
        sections.append("## Report Details")
        sections.append("")
        sections.append("| Field | Value |")
        sections.append("|-------|-------|")
        sections.append(f"| **Repository** | `{repo_label}` |")
        sections.append(f"| **Target path** | `{meta.target_repo}` |")
        sections.append(f"| **Report generated** | {meta.timestamp} |")
        if meta.git_sha:
            dirty = " (dirty)" if meta.git_dirty else ""
            sha_short = meta.git_sha[:10]
            sections.append(f"| **Commit** | `{sha_short}`{dirty} |")
        if meta.git_branch:
            sections.append(f"| **Branch / tag** | {meta.git_branch} |")
        sections.append(f"| **Tool version** | {meta.tool_version} |")
        if meta.git_error:
            sections.append(f"| **Git error** | {meta.git_error} |")
        sections.append("")

    # Summary table
    sections.append(_category_severity_table(all_findings, "Findings Summary"))

    # Design maturity score
    if score_section:
        sections.append(score_section)

    # Diagrams
    if diagrams:
        sections.append("## Diagrams")
        sections.append("")
        for diagram_title, mermaid_text in diagrams.items():
            content = mermaid_text.strip()
            if content:
                sections.append(f"### {diagram_title}")
                sections.append("")
                sections.append("```mermaid")
                sections.append(content)
                sections.append("```")
                sections.append("")

    # Test results
    sections.append(_test_results_section(pytest_result))

    # Findings by region
    sections.append(_findings_section(source_findings, "Source Code Findings"))
    sections.append(_findings_section(test_findings, "Test Code Findings"))

    # Skipped rules
    skipped_section = _skipped_rules_section(nfr_result, hygiene_result)
    if skipped_section:
        sections.append(skipped_section)

    # Suppression audit
    if suppressed_findings:
        sections.append(_suppression_audit_section(suppressed_findings))

    # Architecture Decision Records
    if adr_section:
        sections.append(adr_section)

    # JDepend structural analysis
    if jdepend_section:
        sections.append(jdepend_section)

    # Derived ADRs
    if derived_adrs_section:
        sections.append(derived_adrs_section)

    # Dependency analysis (appendix)
    if deps_section:
        sections.append(deps_section)

    # Scoring methodology appendix (always included when scores are present)
    if score_section:
        sections.append(_methodology_appendix())

    return "\n".join(sections)
