# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Render JDepend metrics and derived ADR sections for the markdown report."""

from __future__ import annotations

from nfr_review.models import Evidence
from nfr_review.output.diagrams import render_jdepend_dot, render_jdepend_metrics_table


def build_jdepend_section(evidence: list[Evidence]) -> str:
    """Build a JDepend structural analysis section from jdepend evidence."""
    pkg_evidence = [e for e in evidence if e.kind == "jdepend-packages"]
    if not pkg_evidence:
        return ""

    lines = ["## JDepend Structural Analysis", ""]

    for ev in pkg_evidence:
        bytecode_dir = ev.payload.get("bytecode_dir", ev.locator)
        packages = ev.payload.get("packages", [])
        cycle_groups = ev.payload.get("cycle_groups", [])

        if len(pkg_evidence) > 1:
            lines.append(f"### Module: `{bytecode_dir}`")
            lines.append("")

        table = render_jdepend_metrics_table(packages)
        if table:
            lines.append(table)

        if cycle_groups:
            lines.append("### Package Cycles")
            lines.append("")
            for group in cycle_groups:
                cycle_str = " → ".join(group) if isinstance(group, list) else str(group)
                lines.append(f"- {cycle_str}")
            lines.append("")

        dot = render_jdepend_dot(packages)
        if dot:
            lines.append("### Package Dependency Diagram")
            lines.append("")
            lines.append("```dot")
            lines.append(dot.rstrip())
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def build_derived_adrs_section(evidence: list[Evidence]) -> str:
    """Build a derived ADRs section from adr-derived evidence."""
    derived = [e for e in evidence if e.kind == "adr-derived"]
    if not derived:
        return ""

    lines = [
        "## Derived Architecture Decision Records",
        "",
        "The following ADRs were inferred from repository content by LLM analysis.",
        "",
        "| # | Decision | Category | Confidence |",
        "|---|----------|----------|------------|",
    ]

    for i, ev in enumerate(derived, 1):
        title = ev.payload.get("title", "Unknown")
        category = ev.payload.get("category", "unknown")
        confidence = ev.payload.get("confidence", 0.0)
        lines.append(f"| {i} | {title} | {category} | {confidence:.0%} |")

    lines.append("")

    for i, ev in enumerate(derived, 1):
        title = ev.payload.get("title", "Unknown")
        rationale = ev.payload.get("rationale", "")
        evidence_refs = ev.payload.get("evidence_refs", [])

        lines.append(f"### {i}. {title}")
        lines.append("")
        if rationale:
            lines.append(f"**Rationale:** {rationale}")
            lines.append("")
        if evidence_refs:
            lines.append("**Supporting evidence:**")
            for ref in evidence_refs:
                lines.append(f"- `{ref}`")
            lines.append("")

    return "\n".join(lines)


__all__ = ["build_derived_adrs_section", "build_jdepend_section"]
