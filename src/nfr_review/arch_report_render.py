# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Multi-format architecture report renderer (JSON, Markdown, PDF)."""

from __future__ import annotations

import base64
import html
import logging
import re
import struct
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nfr_review.arch_models import ArchReport

logger = logging.getLogger(__name__)

# --- Severity / priority styling constants ---

_SEVERITY_ORDER: list[str] = ["critical", "high", "medium", "low"]
_PRIORITY_ORDER: list[str] = ["critical", "high", "medium", "low"]

_SEVERITY_COLORS: dict[str, str] = {
    "critical": "#dc3545",
    "high": "#dc3545",
    "medium": "#fd7e14",
    "low": "#28a745",
}

_SEVERITY_EMOJI: dict[str, str] = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
}

# --- CSS for PDF (follows existing pdf.py patterns) ---

_CSS = (
    "@page { size: A4; margin: 2cm 1.5cm;"
    " @bottom-center { content: counter(page) ' / ' counter(pages);"
    " font-size: 9pt; color: #666; } }\n"
    "@page landscape { size: A4 landscape; margin: 1.5cm 2cm;"
    " @bottom-center { content: counter(page) ' / ' counter(pages);"
    " font-size: 9pt; color: #666; } }\n"
    "* { box-sizing: border-box; }\n"
    "body { font-family: -apple-system, 'Segoe UI', Roboto,"
    " Helvetica, Arial, sans-serif;"
    " font-size: 10pt; line-height: 1.5; color: #1a1a1a; }\n"
    "h1 { font-size: 20pt; color: #1a1a1a; margin-bottom: 0.2em;"
    " border-bottom: 2px solid #333; padding-bottom: 0.3em; }\n"
    "h2 { font-size: 14pt; color: #333; margin-top: 1.5em;"
    " border-bottom: 1px solid #ccc; padding-bottom: 0.2em;"
    " page-break-after: avoid; }\n"
    "h3 { font-size: 12pt; color: #444; margin-top: 1em;"
    " page-break-after: avoid; }\n"
    "h4 { font-size: 10pt; color: #555; margin-top: 0.8em;"
    " page-break-after: avoid; }\n"
    "table { width: 100%; border-collapse: collapse;"
    " margin: 0.5em 0 1em 0; page-break-inside: avoid;"
    " font-size: 9pt; }\n"
    "th, td { border: 1px solid #ddd; padding: 4px 8px;"
    " text-align: left; overflow-wrap: anywhere; }\n"
    "th { background: #f5f5f5; font-weight: 600; }\n"
    "tr:nth-child(even) { background: #fafafa; }\n"
    "pre { font-size: 8pt; background: #f5f5f5;"
    " padding: 8px; border-radius: 4px;"
    " overflow-x: auto; white-space: pre-wrap; }\n"
    "code { font-size: 8pt; background: #f5f5f5;"
    " padding: 1px 4px; border-radius: 2px; }\n"
    ".severity-badge { display: inline-block; padding: 2px 8px;"
    " border-radius: 3px; color: white; font-weight: 600;"
    " font-size: 8pt; }\n"
    ".risk-card { margin: 0.5em 0; padding: 8px 12px;"
    " border-left: 4px solid #ddd; background: #fafafa; }\n"
    ".section-break { page-break-before: always; }\n"
    ".landscape-page { page: landscape; page-break-before: always; }\n"
    ".diagram-page { page-break-before: always; margin: 0; padding: 0; }\n"
    ".diagram-page-landscape { page: landscape;"
    " page-break-before: always; margin: 0; padding: 0; }\n"
    ".diagram-img { display: block; margin: 0.5em auto 0 auto; }\n"
    ".meta-table { width: auto; }\n"
    ".meta-table td { border: none; padding: 2px 12px 2px 0; }\n"
    ".meta-table td:first-child { font-weight: 600; color: #555; }\n"
    ".wide-table th:first-child,"
    " .wide-table td:first-child { min-width: 90px; white-space: nowrap; }\n"
    ".wide-table th:nth-child(2),"
    " .wide-table td:nth-child(2) { min-width: 75px; white-space: nowrap; }\n"
    ".wide-table th:nth-child(3),"
    " .wide-table td:nth-child(3) { min-width: 75px; white-space: nowrap; }\n"
    ".wide-table td:last-child { word-break: break-word; }\n"
    ".comparison-table { table-layout: fixed; width: 100%; }\n"
    ".comparison-table th:nth-child(1) { width: 14%; }\n"
    ".comparison-table th:nth-child(2) { width: 36%; }\n"
    ".comparison-table th:nth-child(3) { width: 10%; }\n"
    ".comparison-table th:nth-child(4) { width: 40%; }\n"
    ".comparison-table td { word-break: break-word;"
    " vertical-align: top; }\n"
    ".coverage-summary { margin-bottom: 0.3em; }\n"
    ".coverage-summary span { display: inline-block;"
    " margin-right: 1.5em; }\n"
    ".gaps-table { table-layout: fixed; width: 100%; }\n"
    ".gaps-table td { word-break: break-word; vertical-align: top; }\n"
    ".domain-table { table-layout: fixed; width: 100%; }\n"
    ".domain-table th:nth-child(1) { width: 12%; }\n"
    ".domain-table th:nth-child(2) { width: 38%; }\n"
    ".domain-table th:nth-child(3) { width: 15%; }\n"
    ".domain-table th:nth-child(4) { width: 35%; }\n"
    ".domain-table td { word-break: break-word; vertical-align: top; }\n"
)


def _h(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text))


_PAGE_CONTENT_W_MM = 210.0 - 30  # A4 portrait: width minus 1.5 cm margins
_PAGE_CONTENT_H_MM = 297.0 - 40  # A4 portrait: height minus 2 cm margins
_DIAGRAM_MAX_H_MM = _PAGE_CONTENT_H_MM - 25  # room for heading + padding

_LANDSCAPE_CONTENT_W_MM = 297.0 - 40  # A4 landscape: width minus 2 cm margins
_LANDSCAPE_CONTENT_H_MM = 210.0 - 30  # A4 landscape: height minus 1.5 cm margins
_LANDSCAPE_DIAGRAM_MAX_H_MM = _LANDSCAPE_CONTENT_H_MM - 25

_WIDE_DIAGRAM_ASPECT_THRESHOLD = 1.8


def _png_dimensions(raw: bytes) -> tuple[int, int] | None:
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 24:
        return None
    w, h = struct.unpack(">II", raw[16:24])
    return w, h


def _is_wide_diagram(img_w: int, img_h: int) -> bool:
    """Return True if the diagram is wide enough to benefit from landscape."""
    if img_h <= 0:
        return False
    aspect = img_w / img_h
    return aspect >= _WIDE_DIAGRAM_ASPECT_THRESHOLD


def _embed_png(path: Path) -> tuple[str, bool]:
    """Base64-embed a PNG, sized to fit within a single A4 page.

    Returns ``(html, is_landscape)`` where *is_landscape* is True when the
    diagram is wide enough to warrant a landscape page.
    """
    raw = path.read_bytes()
    data = base64.b64encode(raw).decode("ascii")
    dims = _png_dimensions(raw)
    style = ""
    landscape = False
    if dims:
        img_w, img_h = dims
        if img_w > 0 and img_h > 0:
            landscape = _is_wide_diagram(img_w, img_h)
            if landscape:
                cw = _LANDSCAPE_CONTENT_W_MM
                ch = _LANDSCAPE_DIAGRAM_MAX_H_MM
            else:
                cw = _PAGE_CONTENT_W_MM
                ch = _DIAGRAM_MAX_H_MM
            aspect = img_w / img_h
            max_aspect = cw / ch
            if aspect >= max_aspect:
                fw = cw
                fh = fw / aspect
            else:
                fh = ch
                fw = fh * aspect
            style = f' style="width:{fw:.1f}mm;height:{fh:.1f}mm"'
    img_tag = f'<img class="diagram-img" src="data:image/png;base64,{data}"{style} />'
    return img_tag, landscape


def _render_mermaid_to_img(
    mermaid_text: str,
    *,
    width: int = 2400,
    height: int = 1600,
) -> tuple[str, bool] | None:
    """Render mermaid text to a high-res inline PNG.

    Uses a wide viewport (default 2400×1600) so complex diagrams have
    enough room for legible node layout before the scale factor is applied.

    Returns ``(html, is_landscape)`` or ``None`` on failure.
    """
    from nfr_review.output.render import render_mermaid_to_png

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        result = render_mermaid_to_png(
            mermaid_text, tmp_path, scale=4, width=width, height=height
        )
        if result is None:
            return None
        return _embed_png(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


def render_arch_json(report: ArchReport, output_path: Path) -> Path:
    """Serialize *report* as indented JSON and write to *output_path*."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.model_dump_json(indent=2) + "\n")
    logger.info("JSON report written to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _md_metadata(report: ArchReport) -> str:
    """Render metadata section."""
    meta = report.metadata
    lines = [
        "# Architecture Report",
        "",
        "> **⚠ EXPERIMENTAL** — This report is generated by an experimental"
        " feature. Format and content may change between releases.",
        "",
        f"**Generated:** {meta.timestamp}  ",
        f"**Tool version:** {meta.tool_version}  ",
        f"**Schema version:** {meta.schema_version}  ",
    ]
    if meta.repos_analyzed:
        repos = ", ".join(r.name for r in meta.repos_analyzed)
        lines.append(f"**Repositories analyzed:** {repos}  ")
    llm_status = f"Yes ({meta.llm_model})" if meta.llm_available else "No"
    lines.append(f"**LLM available:** {llm_status}  ")
    lines.append("")
    return "\n".join(lines)


def _md_executive_summary(report: ArchReport) -> str:
    """Render executive summary section."""
    lines = [
        "## Executive Summary",
        "",
        f"- **Components:** {len(report.components)}",
        f"- **Integration points:** {len(report.integration_points)}",
        f"- **Dynamic scenarios:** {len(report.dynamic_scenarios)}",
        f"- **C4 diagrams:** {len(report.diagrams)}",
    ]

    # Risk summary by severity
    if report.risk_findings:
        severity_counts: dict[str, int] = defaultdict(int)
        for risk in report.risk_findings:
            severity_counts[risk.severity] += 1
        risk_parts = []
        for sev in _SEVERITY_ORDER:
            count = severity_counts.get(sev, 0)
            if count:
                risk_parts.append(f"{count} {sev}")
        lines.append(f"- **Risk findings:** {', '.join(risk_parts)}")
    else:
        lines.append("- **Risk findings:** None")

    lines.append(f"- **Recommendations:** {len(report.recommendations)}")
    lines.append("")
    return "\n".join(lines)


def _md_components(report: ArchReport) -> str:
    """Render components table."""
    if not report.components:
        return "## Components\n\nNo components discovered.\n"

    lines = [
        "## Components",
        "",
        "| ID | Name | Type | Description |",
        "|---|---|---|---|",
    ]
    for comp in report.components:
        lines.append(
            f"| {comp.id} | {comp.name} | {comp.component_type} | {comp.description} |"
        )
    lines.append("")
    return "\n".join(lines)


def _md_integrations(report: ArchReport) -> str:
    """Render integration points table."""
    if not report.integration_points:
        return "## Integration Points\n\nNo integration points discovered.\n"

    lines = [
        "## Integration Points",
        "",
        "| Source | Target | Style | Protocol | Description |",
        "|---|---|---|---|---|",
    ]
    for ip in report.integration_points:
        protocol = ip.protocol or "-"
        lines.append(
            f"| {ip.source_component_id} | {ip.target_component_id}"
            f" | {ip.style} | {protocol} | {ip.description} |"
        )
    lines.append("")
    return "\n".join(lines)


def _md_diagrams(report: ArchReport) -> str:
    """Render C4 diagrams section with mermaid code blocks."""
    if not report.diagrams:
        return ""

    lines = ["## C4 Diagrams", ""]
    for diagram in report.diagrams:
        lines.append(f"### {diagram.title}")
        if diagram.scope:
            lines.append(f"\n*Scope: {diagram.scope}*")
        lines.append(f"\n*Level: {diagram.level}*\n")
        lines.append("```mermaid")
        lines.append(diagram.mermaid)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _md_test_coverage(report: ArchReport) -> str:
    """Render test coverage as per-component subsections."""
    if not report.test_coverage:
        return ""

    lines = ["## Test Coverage", ""]
    for tc in report.test_coverage:
        lines.append(f"### {tc.component_id}")
        lines.append("")
        lines.append(
            f"**Functional:** {tc.functional_coverage} | **NFR:** {tc.nonfunctional_coverage}"
        )
        lines.append("")
        if tc.gaps:
            lines.append("| Gap |")
            lines.append("|---|")
            for gap in tc.gaps:
                lines.append(f"| {gap} |")
        else:
            lines.append("No gaps identified.")
        lines.append("")
    return "\n".join(lines)


def _md_risk_findings(report: ArchReport) -> str:
    """Render risk findings grouped by severity."""
    if not report.risk_findings:
        return "## Risk Findings\n\nNo risks identified.\n"

    by_severity: dict[str, list] = defaultdict(list)
    for risk in report.risk_findings:
        by_severity[risk.severity].append(risk)

    lines = ["## Risk Findings", ""]
    for sev in _SEVERITY_ORDER:
        group = by_severity.get(sev, [])
        if not group:
            continue
        lines.append(f"### {sev.upper()} ({len(group)})")
        lines.append("")
        for risk in group:
            lines.append(f"**[{risk.id}] {risk.title}**  ")
            lines.append(f"Category: {risk.category}  ")
            lines.append(f"{risk.description}  ")
            if risk.evidence:
                lines.append(f"Evidence: {risk.evidence}  ")
            if risk.recommendation:
                lines.append(f"Recommendation: {risk.recommendation}  ")
            if risk.affected_component_ids:
                lines.append(
                    f"Affected components: {', '.join(risk.affected_component_ids)}  "
                )
            lines.append("")
    return "\n".join(lines)


def _md_domain_model(report: ArchReport) -> str:
    """Render domain model section (skip if None)."""
    if report.domain_model is None:
        return ""

    dm = report.domain_model
    lines = ["## Domain Model", ""]

    if dm.entities:
        lines.append("### Entities")
        lines.append("")
        lines.append("| Name | Description | Bounded Context | Attributes |")
        lines.append("|---|---|---|---|")
        for entity in dm.entities:
            ctx = entity.bounded_context or "-"
            attrs = ", ".join(entity.attributes) if entity.attributes else "-"
            lines.append(f"| {entity.name} | {entity.description} | {ctx} | {attrs} |")
        lines.append("")

    if dm.bounded_contexts:
        lines.append("### Bounded Contexts")
        lines.append("")
        for bc in dm.bounded_contexts:
            lines.append(f"**{bc.name}** - {bc.description}  ")
            if bc.entities:
                lines.append(f"Entities: {', '.join(bc.entities)}  ")
            if bc.upstream_contexts:
                lines.append(f"Upstream: {', '.join(bc.upstream_contexts)}  ")
            if bc.downstream_contexts:
                lines.append(f"Downstream: {', '.join(bc.downstream_contexts)}  ")
            lines.append("")

    if dm.context_map_mermaid:
        lines.append("### Context Map")
        lines.append("")
        lines.append("```mermaid")
        lines.append(dm.context_map_mermaid)
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def _md_market_analysis(report: ArchReport) -> str:
    """Render market analysis section (skip if None)."""
    if report.market_analysis is None:
        return ""

    ma = report.market_analysis
    lines = ["## Market Analysis", ""]

    lines.append(f"**Overall maturity:** {ma.overall_maturity}  ")
    if ma.maturity_rationale:
        lines.append(f"**Rationale:** {ma.maturity_rationale}  ")
    if ma.differentiation_summary:
        lines.append(f"**Differentiation:** {ma.differentiation_summary}  ")
    lines.append("")

    if ma.comparisons:
        lines.append("### Comparisons")
        lines.append("")
        lines.append("| Name | Description | Maturity | Positioning |")
        lines.append("|---|---|---|---|")
        for comp in ma.comparisons:
            lines.append(
                f"| {comp.name} | {comp.description}"
                f" | {comp.maturity} | {comp.relative_positioning} |"
            )
        lines.append("")

    return "\n".join(lines)


def _md_repo_dependencies(report: ArchReport) -> str:
    """Render repo-to-repo dependency diagram for multi-repo analyses."""
    if not report.metadata.repos_analyzed or len(report.metadata.repos_analyzed) <= 1:
        return ""

    from nfr_review.output.diagrams import render_mermaid_repo_deps

    mermaid = render_mermaid_repo_deps(report.components, report.integration_points)
    if not mermaid:
        return ""

    lines = [
        "## Repository Dependencies",
        "",
        "```mermaid",
        mermaid.rstrip(),
        "```",
        "",
    ]

    cross_repo = [ip for ip in report.integration_points if ip.is_cross_repo]
    if cross_repo:
        lines.extend(
            [
                "### Cross-Repository Integration Points",
                "",
                "| Source | Target | Style | Description |",
                "|---|---|---|---|",
            ]
        )
        for ip in cross_repo:
            lines.append(
                f"| {ip.source_component_id} | {ip.target_component_id}"
                f" | {ip.style} | {ip.description} |"
            )
        lines.append("")

    return "\n".join(lines)


def _md_cross_repo_edges(report: ArchReport) -> str:
    """Render cross-repository class-level edges as a table."""
    if not report.cross_repo_edges:
        return ""

    lines = [
        "## Cross-Repository Edges",
        "",
        f"Total cross-repo edges: {len(report.cross_repo_edges)}",
        "",
        "| Source Repo | Source Class | Target Repo | Target Class |",
        "|-------------|-------------|-------------|--------------|",
    ]
    for edge in report.cross_repo_edges:
        lines.append(
            f"| {edge.source_repo} | {edge.source_class} "
            f"| {edge.target_repo} | {edge.target_class} |"
        )
    lines.append("")
    return "\n".join(lines)


def _md_dynamic_analysis(report: ArchReport) -> str:
    """Render dynamic analysis (OTel topology) section."""
    if not report.dynamic_analysis:
        return ""

    da = report.dynamic_analysis
    lines = [
        "## Dynamic Analysis",
        "",
        f"**Services observed:** {da.service_count}  ",
        f"**Cross-service edges:** {da.edge_count}  ",
        "",
    ]
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
    return "\n".join(lines)


def _md_recommendations(report: ArchReport) -> str:
    """Render recommendations grouped by priority."""
    if not report.recommendations:
        return "## Recommendations\n\nNo recommendations.\n"

    by_priority: dict[str, list] = defaultdict(list)
    for rec in report.recommendations:
        by_priority[rec.priority].append(rec)

    lines = ["## Recommendations", ""]
    for pri in _PRIORITY_ORDER:
        group = by_priority.get(pri, [])
        if not group:
            continue
        lines.append(f"### {pri.upper()} ({len(group)})")
        lines.append("")
        for rec in group:
            lines.append(f"**[{rec.id}] {rec.title}**  ")
            lines.append(f"Category: {rec.category}  ")
            lines.append(f"{rec.description}  ")
            lines.append(f"Rationale: {rec.rationale}  ")
            if rec.affected_component_ids:
                lines.append(f"Affected components: {', '.join(rec.affected_component_ids)}  ")
            lines.append("")
    return "\n".join(lines)


def render_arch_markdown(report: ArchReport, output_path: Path) -> Path:
    """Render *report* as a structured Markdown document."""
    sections = [
        _md_metadata(report),
        _md_executive_summary(report),
        _md_components(report),
        _md_integrations(report),
        _md_repo_dependencies(report),
        _md_diagrams(report),
        _md_cross_repo_edges(report),
        _md_dynamic_analysis(report),
        _md_test_coverage(report),
        _md_risk_findings(report),
        _md_domain_model(report),
        _md_market_analysis(report),
        _md_recommendations(report),
    ]

    content = "\n".join(s for s in sections if s)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)
    logger.info("Markdown report written to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------


def _pdf_metadata_html(report: ArchReport) -> str:
    """Render metadata as an HTML table."""
    meta = report.metadata
    rows = [
        f"<tr><td>Generated</td><td>{_h(meta.timestamp)}</td></tr>",
        f"<tr><td>Tool version</td><td>{_h(meta.tool_version)}</td></tr>",
        f"<tr><td>Schema version</td><td>{_h(meta.schema_version)}</td></tr>",
    ]
    if meta.repos_analyzed:
        repos = ", ".join(_h(r.name) for r in meta.repos_analyzed)
        rows.append(f"<tr><td>Repositories</td><td>{repos}</td></tr>")
    llm_status = f"Yes ({_h(meta.llm_model or '')})" if meta.llm_available else "No"
    rows.append(f"<tr><td>LLM available</td><td>{llm_status}</td></tr>")
    return f'<table class="meta-table">{"".join(rows)}</table>'


def _pdf_executive_summary_html(report: ArchReport) -> str:
    """Render executive summary as HTML."""
    parts = [
        "<h2>Executive Summary</h2>",
        "<table>",
        "<tr><th>Metric</th><th>Count</th></tr>",
        f"<tr><td>Components</td><td>{len(report.components)}</td></tr>",
        f"<tr><td>Integration points</td><td>{len(report.integration_points)}</td></tr>",
        f"<tr><td>Dynamic scenarios</td><td>{len(report.dynamic_scenarios)}</td></tr>",
        f"<tr><td>C4 diagrams</td><td>{len(report.diagrams)}</td></tr>",
        f"<tr><td>Risk findings</td><td>{len(report.risk_findings)}</td></tr>",
        f"<tr><td>Recommendations</td><td>{len(report.recommendations)}</td></tr>",
        "</table>",
    ]
    return "\n".join(parts)


def _pdf_components_html(report: ArchReport) -> str:
    """Render components table as HTML on a landscape page."""
    if not report.components:
        return ""
    rows = []
    for comp in report.components:
        rows.append(
            f"<tr><td>{_h(comp.id)}</td><td>{_h(comp.name)}</td>"
            f"<td>{_h(comp.component_type)}</td>"
            f"<td>{_h(comp.description)}</td></tr>"
        )
    return (
        '<div class="landscape-page">'
        "<h2>Components</h2>"
        '<table class="wide-table"><thead><tr><th>ID</th><th>Name</th>'
        "<th>Type</th><th>Description</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _pdf_integrations_html(report: ArchReport) -> str:
    """Render integration points table as HTML on a landscape page."""
    if not report.integration_points:
        return ""
    rows = []
    for ip in report.integration_points:
        protocol = _h(ip.protocol) if ip.protocol else "-"
        rows.append(
            f"<tr><td>{_h(ip.source_component_id)}</td>"
            f"<td>{_h(ip.target_component_id)}</td>"
            f"<td>{_h(ip.style)}</td><td>{protocol}</td>"
            f"<td>{_h(ip.description)}</td></tr>"
        )
    return (
        '<div class="landscape-page">'
        "<h2>Integration Points</h2>"
        '<table class="wide-table"><thead><tr><th>Source</th><th>Target</th>'
        "<th>Style</th><th>Protocol</th><th>Description</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _pdf_diagrams_html(report: ArchReport) -> str:
    """Render C4 diagrams as high-res PNG images, one per page."""
    if not report.diagrams:
        return ""
    parts: list[str] = []
    for diagram in report.diagrams:
        result = _render_mermaid_to_img(diagram.mermaid)
        if result:
            img_html, is_landscape = result
            page_cls = "diagram-page-landscape" if is_landscape else "diagram-page"
        else:
            img_html = None
            page_cls = "diagram-page"
        parts.append(f'<div class="{page_cls}">')
        parts.append(f"<h2>{_h(diagram.title)}</h2>")
        if diagram.scope:
            parts.append(f"<p><em>Scope: {_h(diagram.scope)}</em></p>")
        parts.append(f"<p><em>Level: {_h(diagram.level)}</em></p>")
        if img_html:
            parts.append(img_html)
        else:
            parts.append(f"<pre><code>{_h(diagram.mermaid)}</code></pre>")
        parts.append("</div>")
    return "\n".join(parts)


def _pdf_test_coverage_html(report: ArchReport) -> str:
    """Render test coverage as per-component subsections with gap tables."""
    if not report.test_coverage:
        return ""
    parts = ['<div class="section-break">', "<h2>Test Coverage</h2>"]
    for tc in report.test_coverage:
        parts.append(f"<h4>{_h(tc.component_id)}</h4>")
        parts.append(
            f'<p class="coverage-summary">'
            f"<span><strong>Functional:</strong> {_h(tc.functional_coverage)}</span>"
            f"<span><strong>NFR:</strong> {_h(tc.nonfunctional_coverage)}</span>"
            f"</p>"
        )
        if tc.gaps:
            gap_rows = "".join(f"<tr><td>{_h(g)}</td></tr>" for g in tc.gaps)
            parts.append(
                '<table class="gaps-table"><thead><tr>'
                "<th>Gap</th></tr></thead>"
                f"<tbody>{gap_rows}</tbody></table>"
            )
        else:
            parts.append("<p>No gaps identified.</p>")
    parts.append("</div>")
    return "\n".join(parts)


def _pdf_risk_findings_html(report: ArchReport) -> str:
    """Render risk findings grouped by severity as HTML."""
    if not report.risk_findings:
        return (
            '<div class="section-break">'
            "<h2>Risk Findings</h2><p>No risks identified.</p>"
            "</div>"
        )

    by_severity: dict[str, list] = defaultdict(list)
    for risk in report.risk_findings:
        by_severity[risk.severity].append(risk)

    parts = ['<div class="section-break">', "<h2>Risk Findings</h2>"]
    for sev in _SEVERITY_ORDER:
        group = by_severity.get(sev, [])
        if not group:
            continue
        color = _SEVERITY_COLORS.get(sev, "#666")
        parts.append(f"<h3>{_h(sev.upper())} ({len(group)})</h3>")
        for risk in group:
            parts.append(
                f'<div class="risk-card" style="border-left-color:{color}">'
                f"<strong>[{_h(risk.id)}] {_h(risk.title)}</strong><br/>"
                f"Category: {_h(risk.category)}<br/>"
                f"{_h(risk.description)}"
            )
            if risk.evidence:
                parts.append(f"<br/>Evidence: {_h(risk.evidence)}")
            if risk.recommendation:
                parts.append(f"<br/>Recommendation: {_h(risk.recommendation)}")
            if risk.affected_component_ids:
                parts.append(f"<br/>Affected: {_h(', '.join(risk.affected_component_ids))}")
            parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


def _pdf_domain_model_html(report: ArchReport) -> str:
    """Render domain model section as HTML."""
    if report.domain_model is None:
        return ""

    dm = report.domain_model
    parts: list[str] = []

    if dm.entities:
        rows = []
        for entity in dm.entities:
            ctx = _h(entity.bounded_context) if entity.bounded_context else "-"
            attrs = _h(", ".join(entity.attributes)) if entity.attributes else "-"
            rows.append(
                f"<tr><td>{_h(entity.name)}</td>"
                f"<td>{_h(entity.description)}</td>"
                f"<td>{ctx}</td><td>{attrs}</td></tr>"
            )
        parts.append(
            '<div class="landscape-page">'
            "<h2>Domain Model</h2>"
            "<h3>Entities</h3>"
            '<table class="domain-table"><thead><tr><th>Name</th><th>Description</th>'
            "<th>Bounded Context</th><th>Attributes</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
            "</div>"
        )
    else:
        parts.append('<div class="section-break"><h2>Domain Model</h2></div>')

    if dm.bounded_contexts:
        parts.append('<div class="section-break">')
        parts.append("<h3>Bounded Contexts</h3>")
        for bc in dm.bounded_contexts:
            parts.append(f"<p><strong>{_h(bc.name)}</strong> &mdash; {_h(bc.description)}</p>")
            if bc.entities:
                parts.append(f"<p>Entities: {_h(', '.join(bc.entities))}</p>")
        parts.append("</div>")

    if dm.context_map_mermaid:
        result = _render_mermaid_to_img(dm.context_map_mermaid)
        if result:
            img_html, is_landscape = result
            page_cls = "diagram-page-landscape" if is_landscape else "diagram-page"
        else:
            img_html = None
            page_cls = "diagram-page"
        parts.append(f'<div class="{page_cls}">')
        parts.append("<h3>Context Map</h3>")
        if img_html:
            parts.append(img_html)
        else:
            parts.append(f"<pre><code>{_h(dm.context_map_mermaid)}</code></pre>")
        parts.append("</div>")

    return "\n".join(parts)


def _pdf_market_analysis_html(report: ArchReport) -> str:
    """Render market analysis section as HTML."""
    if report.market_analysis is None:
        return ""

    ma = report.market_analysis
    parts = ['<div class="section-break">', "<h2>Market Analysis</h2>"]

    parts.append(f"<p><strong>Overall maturity:</strong> {_h(ma.overall_maturity)}</p>")
    if ma.maturity_rationale:
        parts.append(f"<p><strong>Rationale:</strong> {_h(ma.maturity_rationale)}</p>")
    if ma.differentiation_summary:
        parts.append(
            f"<p><strong>Differentiation:</strong> {_h(ma.differentiation_summary)}</p>"
        )
    parts.append("</div>")

    if ma.comparisons:
        rows = []
        for comp in ma.comparisons:
            rows.append(
                f"<tr><td>{_h(comp.name)}</td><td>{_h(comp.description)}</td>"
                f"<td>{_h(comp.maturity)}</td>"
                f"<td>{_h(comp.relative_positioning)}</td></tr>"
            )
        parts.append(
            '<div class="landscape-page">'
            "<h3>Comparisons</h3>"
            '<table class="comparison-table"><thead><tr><th>Name</th>'
            "<th>Description</th><th>Maturity</th><th>Positioning</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
            "</div>"
        )

    return "\n".join(parts)


def _pdf_repo_dependencies_html(report: ArchReport) -> str:
    """Render repo-to-repo dependency diagram as HTML for PDF."""
    if not report.metadata.repos_analyzed or len(report.metadata.repos_analyzed) <= 1:
        return ""

    from nfr_review.output.diagrams import render_mermaid_repo_deps

    mermaid = render_mermaid_repo_deps(report.components, report.integration_points)
    if not mermaid:
        return ""

    parts: list[str] = ['<div class="section-break">', "<h2>Repository Dependencies</h2>"]

    result = _render_mermaid_to_img(mermaid)
    if result:
        img_html, is_landscape = result
        if is_landscape:
            parts[0] = '<div class="diagram-page-landscape">'
        parts.append(img_html)
    else:
        parts.append(f"<pre><code>{_h(mermaid)}</code></pre>")

    cross_repo = [ip for ip in report.integration_points if ip.is_cross_repo]
    if cross_repo:
        rows = []
        for ip in cross_repo:
            rows.append(
                f"<tr><td>{_h(ip.source_component_id)}</td>"
                f"<td>{_h(ip.target_component_id)}</td>"
                f"<td>{_h(ip.style)}</td>"
                f"<td>{_h(ip.description)}</td></tr>"
            )
        parts.append("<h3>Cross-Repository Integration Points</h3>")
        parts.append(
            '<table class="wide-table"><thead><tr>'
            "<th>Source</th><th>Target</th><th>Style</th><th>Description</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )

    parts.append("</div>")
    return "\n".join(parts)


def _pdf_cross_repo_edges_html(report: ArchReport) -> str:
    """Render cross-repository edges as an HTML table."""
    if not report.cross_repo_edges:
        return ""
    rows = []
    for edge in report.cross_repo_edges:
        rows.append(
            f"<tr><td>{_h(edge.source_repo)}</td><td>{_h(edge.source_class)}</td>"
            f"<td>{_h(edge.target_repo)}</td><td>{_h(edge.target_class)}</td></tr>"
        )
    return (
        '<div class="section-break">'
        "<h2>Cross-Repository Edges</h2>"
        f"<p>Total cross-repo edges: {len(report.cross_repo_edges)}</p>"
        "<table><thead><tr><th>Source Repo</th><th>Source Class</th>"
        "<th>Target Repo</th><th>Target Class</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _pdf_dynamic_analysis_html(report: ArchReport) -> str:
    """Render dynamic analysis (OTel topology) as HTML."""
    if not report.dynamic_analysis:
        return ""
    da = report.dynamic_analysis
    parts = [
        '<div class="section-break">',
        "<h2>Dynamic Analysis</h2>",
        f"<p><strong>Services observed:</strong> {da.service_count} &nbsp; "
        f"<strong>Cross-service edges:</strong> {da.edge_count}</p>",
    ]
    if da.services:
        svc_items = "".join(f"<li>{_h(s)}</li>" for s in da.services)
        parts.append(f"<h3>Observed Services</h3><ul>{svc_items}</ul>")
    if da.topology_mermaid:
        result = _render_mermaid_to_img(da.topology_mermaid)
        if result:
            img_html, _ = result
            parts.append("<h3>Service Topology</h3>")
            parts.append(img_html)
        else:
            parts.append(
                f"<h3>Service Topology</h3><pre><code>{_h(da.topology_mermaid)}</code></pre>"
            )
    parts.append("</div>")
    return "\n".join(parts)


def _pdf_recommendations_html(report: ArchReport) -> str:
    """Render recommendations grouped by priority as HTML."""
    if not report.recommendations:
        return (
            '<div class="section-break">'
            "<h2>Recommendations</h2><p>No recommendations.</p>"
            "</div>"
        )

    by_priority: dict[str, list] = defaultdict(list)
    for rec in report.recommendations:
        by_priority[rec.priority].append(rec)

    parts = ['<div class="section-break">', "<h2>Recommendations</h2>"]
    for pri in _PRIORITY_ORDER:
        group = by_priority.get(pri, [])
        if not group:
            continue
        parts.append(f"<h3>{_h(pri.upper())} ({len(group)})</h3>")
        for rec in group:
            parts.append(
                f'<div class="risk-card">'
                f"<strong>[{_h(rec.id)}] {_h(rec.title)}</strong><br/>"
                f"Category: {_h(rec.category)}<br/>"
                f"{_h(rec.description)}<br/>"
                f"Rationale: {_h(rec.rationale)}"
            )
            if rec.affected_component_ids:
                parts.append(f"<br/>Affected: {_h(', '.join(rec.affected_component_ids))}")
            parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


def render_arch_pdf(report: ArchReport, output_path: Path) -> Path | None:
    """Render *report* as a PDF document using weasyprint.

    Returns the output path on success, or ``None`` if weasyprint is not
    importable.
    """
    try:
        import weasyprint  # type: ignore[import-not-found,import-untyped]
    except ImportError:
        logger.warning("weasyprint not installed; skipping PDF generation")
        return None

    # High-res diagram PNGs can exceed Pillow's default decompression-bomb
    # threshold.  Raise it so weasyprint doesn't choke on large images.
    try:
        from PIL import Image as _PILImage  # type: ignore[import-not-found]

        _PILImage.MAX_IMAGE_PIXELS = 300_000_000
    except ImportError:
        pass

    sections = [
        "<h1>Architecture Report</h1>",
        _pdf_metadata_html(report),
        _pdf_executive_summary_html(report),
        _pdf_components_html(report),
        _pdf_integrations_html(report),
        _pdf_repo_dependencies_html(report),
        _pdf_diagrams_html(report),
        _pdf_cross_repo_edges_html(report),
        _pdf_dynamic_analysis_html(report),
        _pdf_test_coverage_html(report),
        _pdf_risk_findings_html(report),
        _pdf_domain_model_html(report),
        _pdf_market_analysis_html(report),
        _pdf_recommendations_html(report),
    ]

    html_doc = (
        '<!DOCTYPE html>\n<html lang="en">\n'
        '<head><meta charset="utf-8">'
        "<title>Architecture Report</title>\n"
        f"<style>{_CSS}</style></head>\n"
        f"<body>{''.join(s for s in sections if s)}</body>\n</html>"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    weasyprint.HTML(string=html_doc).write_pdf(str(output_path))
    logger.info(
        "PDF report written to %s (%d bytes)",
        output_path,
        output_path.stat().st_size,
    )
    return output_path


# ---------------------------------------------------------------------------
# Multi-format orchestrator
# ---------------------------------------------------------------------------


def _build_filename_prefix(report: ArchReport) -> str:
    """Build a filename prefix like ``myrepo-2026-05-26T1230``."""
    meta = report.metadata
    repo_names = [r.name for r in meta.repos_analyzed] if meta.repos_analyzed else []
    repo_part = "-".join(repo_names) if repo_names else "architecture"
    repo_part = re.sub(r"[^\w\-.]", "_", repo_part)

    ts = meta.timestamp
    ts_match = re.search(r"(\d{4}-\d{2}-\d{2})\D+(\d{2})\D+(\d{2})", ts)
    if ts_match:
        date_part = ts_match.group(1)
        time_part = f"T{ts_match.group(2)}{ts_match.group(3)}"
    else:
        date_part = "undated"
        time_part = ""
    return f"{repo_part}-{date_part}{time_part}"


def render_arch_report(
    report: ArchReport,
    output_dir: Path,
    formats: list[str] | None = None,
) -> dict[str, Path | None]:
    """Render *report* in multiple formats to *output_dir*.

    *formats* defaults to ``["json", "md"]``.  ``"pdf"`` is included only if
    weasyprint is importable (or if explicitly requested — in which case it
    will be ``None`` in the result when weasyprint is unavailable).

    Filenames include the repo name(s) and generation timestamp, e.g.
    ``opentelemetry-demo-2026-05-26T1230-architecture-report.pdf``.

    Returns a dict mapping format name to the output path (or ``None`` if the
    format could not be produced).
    """
    if formats is None:
        formats = ["json", "md"]
        try:
            import weasyprint  # type: ignore[import-not-found,import-untyped] # noqa: F401

            formats.append("pdf")
        except ImportError:
            pass

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = _build_filename_prefix(report)
    results: dict[str, Path | None] = {}

    for fmt in formats:
        if fmt == "json":
            path = output_dir / f"{prefix}-architecture-report.json"
            results["json"] = render_arch_json(report, path)
        elif fmt == "md":
            path = output_dir / f"{prefix}-architecture-report.md"
            results["md"] = render_arch_markdown(report, path)
        elif fmt == "pdf":
            path = output_dir / f"{prefix}-architecture-report.pdf"
            results["pdf"] = render_arch_pdf(report, path)
        elif fmt == "dsl":
            from nfr_review.output.structurizr_dsl import write_workspace_dsl
            from nfr_review.structurizr_bridge import build_workspace_from_arch

            workspace = build_workspace_from_arch(report)
            path = output_dir / f"{prefix}-architecture.dsl"
            results["dsl"] = write_workspace_dsl(workspace, path)
        else:
            logger.warning("Unknown format %r; skipping", fmt)
            results[fmt] = None

    if report.diagrams:
        from nfr_review.arch_diagrams import detect_orphan_nodes, render_orphans_markdown

        orphans = detect_orphan_nodes(report.diagrams)
        orphan_md = render_orphans_markdown(orphans)
        orphan_path = output_dir / f"{prefix}-orphan-nodes.md"
        orphan_path.write_text(orphan_md)
        results["orphans"] = orphan_path
        if orphans:
            logger.info(
                "Orphan nodes report: %d orphans across %d diagrams → %s",
                len(orphans),
                len({o.diagram_title for o in orphans}),
                orphan_path,
            )

    return results


__all__ = [
    "render_arch_json",
    "render_arch_markdown",
    "render_arch_pdf",
    "render_arch_report",
]
