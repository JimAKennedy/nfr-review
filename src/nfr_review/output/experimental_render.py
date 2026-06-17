# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Render experimental class-diagram reports to JSON and Markdown."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from nfr_review.experimental_models import ExperimentalReport

logger = logging.getLogger(__name__)


def _render_json(report: ExperimentalReport, output_path: Path) -> Path:
    """Serialize *report* as indented JSON and write to *output_path*."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = report.model_dump()
    output_path.write_text(json.dumps(data, indent=2, default=str) + "\n")
    logger.info("Experimental JSON report written to %s", output_path)
    return output_path


def _render_markdown(report: ExperimentalReport, output_path: Path) -> Path:
    """Render *report* as Markdown with Mermaid code blocks."""
    lines: list[str] = []

    # Header
    lines.append("# Experimental Report")
    lines.append("")
    lines.append(f"**Repository:** {report.repo_name}  ")
    if report.metadata.get("timestamp"):
        lines.append(f"**Generated:** {report.metadata['timestamp']}  ")
    if report.metadata.get("version"):
        lines.append(f"**Tool version:** {report.metadata['version']}  ")
    if report.metadata.get("repos_analyzed"):
        lines.append(f"**Repos analyzed:** {report.metadata['repos_analyzed']}  ")
    lines.append("")

    # Class diagrams
    lines.append("## Class Diagrams")
    lines.append("")
    if report.class_diagrams:
        lines.append(f"Total diagrams: {len(report.class_diagrams)}")
        lines.append("")
        for diagram in report.class_diagrams:
            lines.append(f"### {diagram.title}")
            lines.append("")
            if diagram.scope:
                lines.append(f"*Scope: {diagram.scope} | Level: {diagram.level}*")
                lines.append("")
            lines.append("```mermaid")
            lines.append(diagram.mermaid.rstrip("\n"))
            lines.append("```")
            lines.append("")
    else:
        lines.append("No class diagrams generated.")
        lines.append("")

    # Dynamic analysis
    if report.dynamic_analysis:
        da = report.dynamic_analysis
        lines.append("## Dynamic Analysis")
        lines.append("")
        lines.append(f"**Services observed:** {da.service_count}  ")
        lines.append(f"**Cross-service edges:** {da.edge_count}  ")
        lines.append("")
        if da.services:
            lines.append("### Observed Services")
            lines.append("")
            for svc in da.services:
                lines.append(f"- {svc}")
            lines.append("")
        if da.topology_mermaid:
            lines.append("### Service Topology")
            lines.append("")
            lines.append("```mermaid")
            lines.append(da.topology_mermaid.rstrip("\n"))
            lines.append("```")
            lines.append("")

    # Cross-repo edges
    lines.append("## Cross-Repository Edges")
    lines.append("")
    if report.cross_repo_edges:
        lines.append(f"Total cross-repo edges: {len(report.cross_repo_edges)}")
        lines.append("")
        lines.append("| Source Repo | Source Class | Target Repo | Target Class |")
        lines.append("|-------------|-------------|-------------|--------------|")
        for edge in report.cross_repo_edges:
            lines.append(
                f"| {edge.source_repo} | {edge.source_class} "
                f"| {edge.target_repo} | {edge.target_class} |"
            )
        lines.append("")
    else:
        lines.append("No cross-repository edges detected.")
        lines.append("")

    text = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text)
    logger.info("Experimental Markdown report written to %s", output_path)
    return output_path


def render_experimental_report(
    report: ExperimentalReport,
    output_dir: Path,
    *,
    formats: list[str] | None = None,
) -> dict[str, Path | None]:
    """Render *report* in multiple formats to *output_dir*.

    *formats* defaults to ``["json", "md"]``.

    Returns a dict mapping format name to the output path (or ``None`` if the
    format could not be produced).
    """
    if formats is None:
        formats = ["json", "md"]

    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Path | None] = {}

    for fmt in formats:
        if fmt == "json":
            path = output_dir / "experimental-report.json"
            results["json"] = _render_json(report, path)
        elif fmt == "md":
            path = output_dir / "experimental-report.md"
            results["md"] = _render_markdown(report, path)
        else:
            logger.warning("Unknown format %r; skipping", fmt)
            results[fmt] = None

    return results


__all__ = [
    "render_experimental_report",
]
