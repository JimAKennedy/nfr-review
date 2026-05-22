# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""PDF report generator using weasyprint.

Composes an HTML document from scan results, optional executive summary,
and optional rendered diagram images, then converts to PDF.
"""

from __future__ import annotations

import base64
import html
import logging
import struct
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nfr_review.engine import RunResult
    from nfr_review.models import RAG, Finding, Severity
    from nfr_review.output.pytest_runner import PytestResult
    from nfr_review.output.summary_models import ExecSummary

logger = logging.getLogger(__name__)

_RAG_ORDER: tuple[RAG, ...] = ("red", "amber", "green")
_SEVERITY_ORDER: tuple[Severity, ...] = ("critical", "high", "medium", "low", "info")

_RAG_COLORS = {
    "red": "#dc3545",
    "amber": "#fd7e14",
    "green": "#28a745",
    "skipped": "#6c757d",
}

_VERDICT_STYLES = {
    "fit": ("Fit for Purpose", "#28a745", "#d4edda"),
    "conditional": ("Conditional", "#fd7e14", "#fff3cd"),
    "unfit": ("Not Fit for Purpose", "#dc3545", "#f8d7da"),
}

_CSS = (  # noqa: E501
    "@page { size: A4; margin: 2cm 1.5cm;"
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
    "table { width: 100%; border-collapse: collapse;"
    " margin: 0.5em 0 1em 0; page-break-inside: avoid;"
    " font-size: 9pt; }\n"
    "th, td { border: 1px solid #ddd; padding: 4px 8px;"
    " text-align: left; }\n"
    "th { background: #f5f5f5; font-weight: 600; }\n"
    "tr:nth-child(even) { background: #fafafa; }\n"
    ".verdict-box { padding: 12px 16px; border-radius: 6px;"
    " margin: 1em 0; }\n"
    ".verdict-label { font-size: 14pt; font-weight: 700; }\n"
    ".verdict-score { float: right; font-size: 20pt;"
    " font-weight: 700; }\n"
    ".risk-item { margin: 0.3em 0; padding-left: 1em;"
    " border-left: 3px solid #dc3545; }\n"
    ".remediation { margin: 0.5em 0; padding: 8px 12px;"
    " background: #f8f9fa; border-radius: 4px; }\n"
    ".remediation-title { font-weight: 600; }\n"
    ".urgency-immediate { color: #dc3545; font-weight: 600; }\n"
    ".urgency-short-term { color: #fd7e14; }\n"
    ".urgency-medium-term { color: #6c757d; }\n"
    ".diagram-container { page-break-before: always;"
    " margin: 0.5em 0; }\n"
    ".diagram-img { display: block; margin: 0 auto; }\n"
    ".finding { margin: 0.4em 0; padding: 6px 10px;"
    " border-left: 3px solid #ddd; font-size: 9pt; }\n"
    ".finding-red { border-left-color: #dc3545; }\n"
    ".finding-amber { border-left-color: #fd7e14; }\n"
    ".finding-green { border-left-color: #28a745; }\n"
    ".location-table { margin: 4px 0 0 0; width: auto; }\n"
    ".location-table th { background: none; border: none;"
    " padding: 2px 8px; font-weight: 600; font-size: 8pt;"
    " color: #666; }\n"
    ".location-table td { border: none; border-top: 1px solid #eee;"
    " padding: 2px 8px; font-size: 8pt; }\n"
    ".provenance { font-size: 9pt; color: #666; }\n"
    ".provenance code { background: #f5f5f5; padding: 1px 4px;"
    " border-radius: 2px; }\n"
    ".section-break { page-break-before: always; }\n"
)


def _h(text: str) -> str:
    return html.escape(str(text))


_PAGE_CONTENT_W_MM = 210.0 - 30  # A4 width minus 1.5cm margins each side
_PAGE_CONTENT_H_MM = 297.0 - 40  # A4 height minus 2cm margins top/bottom
_DIAGRAM_MAX_H_MM = _PAGE_CONTENT_H_MM - 25  # room for heading + padding


def _png_dimensions(raw: bytes) -> tuple[int, int] | None:
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 24:
        return None
    w, h = struct.unpack(">II", raw[16:24])
    return w, h


def _embed_image(path: Path) -> str:
    raw = path.read_bytes()
    data = base64.b64encode(raw).decode("ascii")
    suffix = path.suffix.lstrip(".")
    mime = {"png": "image/png", "svg": "image/svg+xml", "jpg": "image/jpeg"}.get(
        suffix, "image/png"
    )

    dims = _png_dimensions(raw) if suffix == "png" else None
    style = ""
    if dims:
        img_w, img_h = dims
        if img_w > 0 and img_h > 0:
            aspect = img_w / img_h
            max_aspect = _PAGE_CONTENT_W_MM / _DIAGRAM_MAX_H_MM
            if aspect >= max_aspect:
                fw = _PAGE_CONTENT_W_MM
                fh = fw / aspect
            else:
                fh = _DIAGRAM_MAX_H_MM
                fw = fh * aspect
            style = f' style="width:{fw:.1f}mm;height:{fh:.1f}mm"'

    return f'<img class="diagram-img" src="data:{mime};base64,{data}"{style} />'


def _summary_table_html(findings: list[Finding], title: str) -> str:
    counts: Counter[tuple[RAG, Severity]] = Counter()
    for f in findings:
        counts[(f.rag, f.severity)] += 1

    rows = []
    for rag in _RAG_ORDER:
        cells = []
        row_total = 0
        for sev in _SEVERITY_ORDER:
            n = counts.get((rag, sev), 0)
            row_total += n
            cells.append(f"<td>{n if n else '-'}</td>")
        color = _RAG_COLORS.get(rag, "#666")
        rows.append(
            f'<tr><td style="color:{color};font-weight:600">{_h(rag.upper())}</td>'
            f"{''.join(cells)}<td><strong>{row_total}</strong></td></tr>"
        )
    rows.append(
        f"<tr><td><strong>Total</strong></td>"
        f'<td colspan="5"></td><td><strong>{len(findings)}</strong></td></tr>'
    )

    return f"""<h3>{_h(title)}</h3>
<table>
<thead><tr><th>RAG</th><th>Critical</th><th>High</th><th>Medium</th><th>Low</th><th>Info</th><th>Total</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>"""


def _exec_summary_html(summary: ExecSummary) -> str:
    label, color, bg = _VERDICT_STYLES.get(summary.verdict, ("Unknown", "#666", "#f0f0f0"))

    parts = [
        f'<div class="verdict-box" style="background:{bg};border:2px solid {color}">',
        f'<span class="verdict-score">{summary.overall_score}/100</span>',
        f'<span class="verdict-label" style="color:{color}">{_h(label)}</span>',
        f"<p>{_h(summary.verdict_explanation)}</p>",
        "</div>",
    ]

    if summary.risk_highlights:
        parts.append("<h3>Key Risks</h3>")
        for risk in summary.risk_highlights:
            parts.append(f'<div class="risk-item">{_h(risk)}</div>')

    if summary.remediation_priorities:
        parts.append("<h3>Remediation Priorities</h3>")
        for item in summary.remediation_priorities:
            urgency_cls = f"urgency-{item.urgency}"
            parts.append(
                f'<div class="remediation">'
                f'<span class="remediation-title">{_h(item.title)}</span> '
                f'<span class="{urgency_cls}">({_h(item.urgency)})</span>'
                f"<br/>{_h(item.description)}</div>"
            )

    parts.append(f"<h3>Production Risks</h3><p>{_h(summary.production_risks)}</p>")
    parts.append(f"<h3>Open-Source Readiness</h3><p>{_h(summary.open_source_readiness)}</p>")

    return "\n".join(parts)


def _findings_html(findings: list[Finding], title: str) -> str:
    if not findings:
        return f"<h2>{_h(title)}</h2><p>No findings.</p>"

    by_rag: dict[RAG, list[Finding]] = {}
    for f in findings:
        by_rag.setdefault(f.rag, []).append(f)

    parts = [f"<h2>{_h(title)}</h2>"]
    for rag in _RAG_ORDER:
        group = by_rag.get(rag, [])
        if not group:
            continue
        parts.append(f"<h3>{_h(rag.upper())} ({len(group)})</h3>")

        issue_groups: dict[tuple[str, str], list[Finding]] = {}
        for f in group:
            key = (f.rule_id, f.summary)
            issue_groups.setdefault(key, []).append(f)

        for (rule_id, summary), occurrences in issue_groups.items():
            representative = occurrences[0]
            parts.append(
                f'<div class="finding finding-{representative.rag}">'
                f"<strong>[{_h(rule_id)}]</strong> {_h(summary)}<br/>"
                f"Recommendation: {_h(representative.recommendation)}"
            )
            parts.append('<table class="location-table">')
            parts.append(
                "<thead><tr>"
                "<th>Location</th><th>Severity</th><th>Confidence</th>"
                "</tr></thead><tbody>"
            )
            for occ in occurrences:
                parts.append(
                    f"<tr>"
                    f"<td><code>{_h(occ.evidence_locator)}</code></td>"
                    f"<td>{_h(occ.severity)}</td>"
                    f"<td>{occ.confidence:.0%}</td>"
                    f"</tr>"
                )
            parts.append("</tbody></table></div>")

    return "\n".join(parts)


def _provenance_html(nfr_result: RunResult) -> str:
    meta = nfr_result.run_metadata
    if not meta:
        return ""
    repo_label = Path(meta.target_repo).name
    parts = [
        '<div class="provenance">',
        "<table>",
        f"<tr><td><strong>Repository</strong></td><td><code>{_h(repo_label)}</code></td></tr>",
        "<tr><td><strong>Target path</strong></td>"
        f"<td><code>{_h(meta.target_repo)}</code></td></tr>",
        f"<tr><td><strong>Report generated</strong></td><td>{_h(meta.timestamp)}</td></tr>",
    ]
    if meta.git_sha:
        dirty = " (dirty)" if meta.git_dirty else ""
        sha_short = meta.git_sha[:10]
        parts.append(
            f"<tr><td><strong>Commit</strong></td>"
            f"<td><code>{_h(sha_short)}</code>{dirty}</td></tr>"
        )
    if meta.git_branch:
        parts.append(
            f"<tr><td><strong>Branch / tag</strong></td><td>{_h(meta.git_branch)}</td></tr>"
        )
    parts.append(
        f"<tr><td><strong>Tool version</strong></td><td>{_h(meta.tool_version)}</td></tr>"
    )
    parts.append("</table>")
    parts.append("</div>")
    return "\n".join(parts)


def _test_results_html(pytest_result: PytestResult | None) -> str:
    if pytest_result is None:
        return "<h2>Test Results</h2><p>Test execution was not performed.</p>"

    if pytest_result.exit_code == -1:
        return f"<h2>Test Results</h2><p>&#9888; {_h(pytest_result.raw_output)}</p>"

    all_green = pytest_result.failed == 0 and pytest_result.errors == 0
    icon = "&#10003;" if all_green else "&#10007;"
    status = "PASSED" if all_green else "FAILED"
    color = "#28a745" if all_green else "#dc3545"

    return f"""<h2>Test Results</h2>
<p style="color:{color};font-weight:600">{icon} {status}</p>
<table>
<tr><th>Metric</th><th>Count</th></tr>
<tr><td>Passed</td><td>{pytest_result.passed}</td></tr>
<tr><td>Failed</td><td>{pytest_result.failed}</td></tr>
<tr><td>Skipped</td><td>{pytest_result.skipped}</td></tr>
<tr><td>Errors</td><td>{pytest_result.errors}</td></tr>
<tr><td>Duration</td><td>{pytest_result.duration_seconds:.2f}s</td></tr>
</table>"""


def _inline_md(text: str) -> str:
    """Convert inline markdown (bold, code) to HTML."""
    import re

    escaped = _h(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    return escaped


def _md_deps_to_html(md: str) -> str:
    """Convert the markdown dependency section to proper HTML tables."""
    lines = md.split("\n")
    parts: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("## "):
            parts.append(f"<h2>{_h(line[3:].strip())}</h2>")
        elif line.startswith("### "):
            parts.append(f"<h3>{_h(line[4:].strip())}</h3>")
        elif line.startswith("#### "):
            parts.append(f"<h4>{_h(line[5:].strip())}</h4>")
        elif line.startswith("| ") and i + 1 < len(lines) and lines[i + 1].startswith("|--"):
            headers = [c.strip() for c in line.split("|")[1:-1]]
            parts.append("<table><thead><tr>")
            parts.append("".join(f"<th>{_h(h)}</th>" for h in headers))
            parts.append("</tr></thead><tbody>")
            i += 2  # skip separator
            while i < len(lines) and lines[i].startswith("| "):
                cells = [c.strip() for c in lines[i].split("|")[1:-1]]
                parts.append("<tr>")
                parts.append("".join(f"<td>{_h(c)}</td>" for c in cells))
                parts.append("</tr>")
                i += 1
            parts.append("</tbody></table>")
            continue
        elif line.startswith("```"):
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            parts.append(
                f'<pre style="font-size:8pt;background:#f5f5f5;'
                f'padding:8px;border-radius:4px;overflow-x:auto">'
                f"<code>{_h(chr(10).join(code_lines))}</code></pre>"
            )
        elif line.startswith("> "):
            parts.append(
                f'<blockquote style="border-left:3px solid #dc3545;'
                f'padding:4px 8px;margin:0.5em 0;color:#721c24">'
                f"{_h(line[2:])}</blockquote>"
            )
        elif line.strip():
            parts.append(f"<p>{_inline_md(line)}</p>")

        i += 1

    return "\n".join(parts)


def render_pdf(
    *,
    nfr_result: RunResult,
    output_path: Path,
    hygiene_result: RunResult | None = None,
    exec_summary: ExecSummary | None = None,
    pytest_result: PytestResult | None = None,
    deps_section_md: str = "",
    diagram_paths: dict[str, Path] | None = None,
    title: str = "NFR Review Report",
) -> Path:
    """Render a complete PDF report from scan results.

    Returns the output path on success. Raises ``ImportError`` if weasyprint
    is not installed.
    """
    from nfr_review.output.classify import partition_findings

    all_findings: list[Finding] = list(nfr_result.findings)
    if hygiene_result:
        all_findings.extend(hygiene_result.findings)

    source_findings, test_findings = partition_findings(all_findings)

    sections: list[str] = []

    meta = nfr_result.run_metadata
    repo_label = Path(meta.target_repo).name if meta else ""
    heading = f"{_h(title)} — {_h(repo_label)}" if repo_label else _h(title)
    sections.append(f"<h1>{heading}</h1>")
    sections.append(_provenance_html(nfr_result))

    if exec_summary:
        sections.append("<h2>Executive Summary</h2>")
        sections.append(_exec_summary_html(exec_summary))

    sections.append(_summary_table_html(all_findings, "Overall Summary"))
    sections.append(_summary_table_html(source_findings, "Source Code Summary"))
    sections.append(_summary_table_html(test_findings, "Test Code Summary"))

    if diagram_paths:
        sections.append("<h2>Diagrams</h2>")
        for diagram_title, path in diagram_paths.items():
            if path.exists():
                sections.append(
                    f'<div class="diagram-container">'
                    f"<h3>{_h(diagram_title)}</h3>"
                    f"{_embed_image(path)}</div>"
                )

    sections.append(_test_results_html(pytest_result))

    if deps_section_md:
        sections.append(_md_deps_to_html(deps_section_md))

    sections.append('<div class="section-break"></div>')
    sections.append(_findings_html(source_findings, "Source Code Findings"))
    sections.append(_findings_html(test_findings, "Test Code Findings"))

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{_h(title)}</title>
<style>{_CSS}</style></head>
<body>{"".join(sections)}</body>
</html>"""

    import weasyprint  # type: ignore[import-not-found]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    weasyprint.HTML(string=html_doc).write_pdf(str(output_path))
    logger.info("PDF written to %s (%d bytes)", output_path, output_path.stat().st_size)
    return output_path


__all__ = ["render_pdf"]
