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


def _methodology_appendix(
    llm_info: tuple[str, str] | None = None,
) -> str:
    """Render the scoring methodology appendix as Markdown.

    Parameters
    ----------
    llm_info:
        Optional ``(provider, model)`` tuple describing the LLM used for
        this run, or ``None`` when no LLM was configured.
    """
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
        "Every finding's rule ID is mapped to an ISO/IEC 25010"
        " quality category (*security*, *reliability*,"
        " *performance*, *maintainability*) or a hygiene/patching"
        " prefix. Legacy category names are aliased automatically"
        " (*observability* → *reliability*, *ops* →"
        " *maintainability*). Each finding deducts points from"
        " the category's starting score of 100, weighted by"
        " severity:"
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
        "The overall Design Maturity Score is the"
        " coverage-weighted average of all category scores."
        " Each category carries a configurable weight"
        " (default 1.0); categories with higher weights"
        " contribute proportionally more to the final score."
        " Categories with many findings pull the average"
        " down; categories with no findings score 100 and"
        " are still included if they have a configured weight."
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
        "Core NFR Categories (ISO/IEC 25010)",
        [
            (
                "**security**",
                "Auth, secrets, supply-chain pinning, PII, container user directives",
                "No leaked secrets, pinned images/providers, no PII in logs, least-privilege",
            ),
            (
                "**reliability**",
                "Structured logging, correlation IDs, health probes *(alias: observability)*",
                "Structured logs with correlation IDs, separate health/readiness",
            ),
            (
                "**performance**",
                "Timeouts, thread pools, goroutine leaks, async correctness, dep instability",
                "Explicit timeouts, bounded pools, no fire-and-forget async, stable dep graph",
            ),
            (
                "**maintainability**",
                "Containers, K8s, Helm, CI, service-mesh, "
                "Terraform, build tooling, ADR governance"
                " *(alias: ops)*",
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

    _cat_table(
        "OTel Readiness Category (OTEL)",
        [
            (
                "**OTEL**",
                "OpenTelemetry instrumentation readiness: exporter config, pipeline"
                " completeness, sampling strategy, W3C propagation, resource attributes,"
                " test agent setup, integration test coverage, fault injection,"
                " test observability, dynamic method coverage, call-sequence diagrams,"
                " correlation-ID propagation verification,"
                " runtime topology vs ADR drift detection",
                "OTel SDK configured with OTLP exporter, complete trace/metrics/logs"
                " pipelines, W3C trace-context propagation, service.name and"
                " service.version resource attributes, test coverage for"
                " instrumented paths, fault-injection tests for resilience signals,"
                " runtime method coverage reported, correlation IDs propagated"
                " end-to-end, no N+1 query patterns, p95 latency within targets,"
                " runtime service topology matches ADR-declared architecture",
            ),
        ],
    )

    _a("")
    _a("### LLM Usage in This Report")
    _a("")
    if llm_info is not None:
        provider, model = llm_info
        _a(
            f"This report was generated with LLM integration"
            f" enabled (**{provider}**, model `{model}`)."
            " The following sections may use LLM analysis:"
        )
        _a("")
        _a(
            "- **Executive Summary** (PDF only) — AI-generated"
            " holistic assessment including verdict"
            " (Fit / Conditional / Unfit), risk highlights,"
            " remediation priorities, and an independent overall"
            " score (0–100). This score **may differ from the"
            " deterministic Design Maturity Score** as it"
            " considers factors beyond individual rule findings,"
            " such as the overall pattern of issues, test"
            " coverage, and dependency health."
        )
        _a(
            "- **Derived Architecture Decision Records** —"
            " candidate ADRs inferred from repository content"
            " (config files, existing ADRs, README)."
        )
        _a("")
        _a(
            "All other sections — findings, Design Maturity Score,"
            " category breakdowns, diagrams, and dependency"
            " analysis — are produced by deterministic static"
            " analysis and are not influenced by the LLM."
        )
    else:
        _a(
            "This report was generated **without LLM"
            " integration**. All sections are produced by"
            " deterministic static analysis. To enable"
            " AI-generated executive summaries, configure an"
            " LLM provider in `nfr-review.yaml` under the"
            " `llm:` key or set the appropriate environment"
            " variables (`NFR_LLM_PROVIDER`,"
            " `NFR_LLM_MODEL`)."
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
            "The overall score is the coverage-weighted average of the"
            " ISO/IEC 25010 category scores below."
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
    llm_info: tuple[str, str] | None = None,
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
        sections.append(_methodology_appendix(llm_info=llm_info))

    return "\n".join(sections)
