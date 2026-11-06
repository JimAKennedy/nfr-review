# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""PDF report generator using typst.

Composes a Typst document from scan results, optional executive summary,
and optional diagram stubs, then compiles to PDF.
"""

from __future__ import annotations

import logging
import struct
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from nfr_review.scoring import _extract_category

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

_SEVERITY_COLORS: dict[Severity, str] = {
    "critical": "#dc3545",
    "high": "#dc3545",
    "medium": "#fd7e14",
    "low": "#28a745",
    "info": "#28a745",
}

_VERDICT_STYLES = {
    "fit": ("Fit for Purpose", "#28a745", "#d4edda"),
    "conditional": ("Conditional", "#fd7e14", "#fff3cd"),
    "unfit": ("Not Fit for Purpose", "#dc3545", "#f8d7da"),
}

_PAGE_CONTENT_W_MM = 210.0 - 30  # A4 width minus 1.5cm margins each side
_PAGE_CONTENT_H_MM = 297.0 - 40  # A4 height minus 2cm margins top/bottom
_DIAGRAM_MAX_H_MM = _PAGE_CONTENT_H_MM - 25  # room for heading + padding


def _png_dimensions(raw: bytes) -> tuple[int, int] | None:
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 24:
        return None
    w, h = struct.unpack(">II", raw[16:24])
    return w, h


def _t(text: str) -> str:
    """Escape text for Typst markup."""
    text = str(text)
    text = text.replace("\\", "\\\\")
    text = text.replace("#", "\\#")
    text = text.replace("@", "\\@")
    text = text.replace("*", "\\*")
    text = text.replace("_", "\\_")
    text = text.replace("<", "\\<")
    text = text.replace(">", "\\>")
    return text


def _image_typst(filename: str, raw_bytes: bytes) -> str:
    """Return a Typst #image(...) call for a registered image file."""
    dims = _png_dimensions(raw_bytes)
    if dims:
        w_px, h_px = dims
        # Scale to fit within page content width, preserving aspect ratio
        w_mm = min(_PAGE_CONTENT_W_MM, w_px / 3.78)  # 96dpi → mm approx
        h_mm = w_mm * h_px / w_px
        if h_mm > _DIAGRAM_MAX_H_MM:
            h_mm = _DIAGRAM_MAX_H_MM
            w_mm = h_mm * w_px / h_px
        return f'#image("{filename}", width: {w_mm:.1f}mm)\n'
    return f'#image("{filename}", width: 100%)\n'


def _render_mermaid_for_typst(
    mermaid_text: str,
    image_files: dict[str, bytes],
    counter: list[int],
) -> str:
    """Render a mermaid code block to a Typst image or fallback.

    Tier 1: mmdc → PNG → #image(...)
    Tier 2: SVG fallback (pure Python) → #image(...)
    Tier 3: Typst table/list from parsed diagram content
    """
    from nfr_review.output.render import (
        render_flowchart_as_svg_fallback,
        render_mermaid_to_png,
        render_pie_as_svg_fallback,
    )

    counter[0] += 1
    idx = counter[0]

    # --- Tier 1: mmdc PNG ---
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / f"mermaid_{idx}.png"
        result = render_mermaid_to_png(mermaid_text, out_path)
        if result is not None and result.exists():
            raw = result.read_bytes()
            filename = f"mermaid_{idx}.png"
            image_files[filename] = raw
            return _image_typst(filename, raw)

    # --- Tier 2: SVG fallback ---
    lines = [ln.strip() for ln in mermaid_text.strip().splitlines() if ln.strip()]
    svg_bytes: bytes | None = None
    svg_filename = f"mermaid_{idx}.svg"

    if any(ln.startswith("pie") for ln in lines):
        data: dict[str, int] = {}
        for line in lines:
            if '"' in line and ":" in line:
                label = line.split('"')[1]
                try:
                    val = int(float(line.split(":")[-1].strip()))
                except ValueError:
                    val = 0
                data[label] = val
        if data:
            svg_str = render_pie_as_svg_fallback(data)
            svg_bytes = svg_str.encode("utf-8")

    elif any("-->" in ln for ln in lines):
        items: list[str] = []
        for line in lines:
            if "-->" in line:
                for part in line.split("-->"):
                    part = part.strip()
                    if "[" in part:
                        label = part.split("[")[1].rstrip("]").strip('"')
                        if label not in items:
                            items.append(label)
        if items:
            svg_str = render_flowchart_as_svg_fallback(items)
            svg_bytes = svg_str.encode("utf-8")

    if svg_bytes:
        image_files[svg_filename] = svg_bytes
        return f'#image("{svg_filename}", width: 100%)\n'

    # --- Tier 3: Typst table ---
    if any(ln.startswith("pie") for ln in lines):
        rows: list[tuple[str, str]] = []
        for line in lines:
            if '"' in line and ":" in line:
                label = line.split('"')[1]
                val = line.split(":")[-1].strip()
                rows.append((_t(label), _t(val)))
        if rows:
            cells = "".join(f"  [{label}], [{val}],\n" for label, val in rows)
            return (
                "#table(\n"
                "  columns: (1fr, auto),\n"
                '  stroke: 0.5pt + rgb("dddddd"),\n'
                "  [*Category*], [*Count*],\n"
                f"{cells}"
                ")\n"
            )

    if any("-->" in ln for ln in lines):
        seen: list[str] = []
        for line in lines:
            if "-->" in line:
                for part in line.split("-->"):
                    part = part.strip()
                    if "[" in part:
                        label = part.split("[")[1].rstrip("]").strip('"')
                        if label not in seen:
                            seen.append(label)
        if seen:
            cells = "".join(f"  [{_t(item)}],\n" for item in seen)
            return (
                "#table(\n"
                "  columns: (1fr,),\n"
                '  stroke: 0.5pt + rgb("dddddd"),\n'
                "  [*Component*],\n"
                f"{cells}"
                ")\n"
            )

    # Last resort: show as raw code
    escaped = mermaid_text.replace('"', '\\"')
    return f'#raw(lang: "none", block: true, "{escaped}")\n'


def _md_to_typst(
    md: str,
    image_files: dict[str, bytes],
    counter: list[int],
) -> str:
    """Convert a markdown string to Typst markup.

    Handles: headings, pipe tables, fenced code blocks (including mermaid),
    blockquotes, bold inline, inline code, plain paragraphs.
    """
    lines = md.splitlines()
    out: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # --- Fenced code block ---
        if line.strip().startswith("```"):
            fence_marker = line.strip()
            lang = fence_marker[3:].strip().lower()
            body_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body_lines.append(lines[i])
                i += 1
            i += 1  # consume closing fence
            body = "\n".join(body_lines)
            if lang == "mermaid":
                out.append(_render_mermaid_for_typst(body, image_files, counter))
            else:
                # Escape for Typst raw string: backslash then quote
                escaped = body.replace("\\", "\\\\").replace('"', '\\"')
                out.append(f'#raw(lang: "none", block: true, "{escaped}")\n')
            continue

        # --- Pipe table ---
        if "|" in line and line.strip().startswith("|"):
            # Collect all table lines
            table_lines: list[str] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            # Parse: first row = headers, second row = separator, rest = data
            if len(table_lines) >= 2:
                header_cells = [c.strip() for c in table_lines[0].split("|") if c.strip()]
                # skip separator row (index 1)
                data_rows_raw = table_lines[2:]
                n_cols = len(header_cells)
                col_spec = "(" + ", ".join(["1fr"] * n_cols) + ")"
                header_row = "".join(
                    f"  [*{_inline_md_to_typst(h)}*],\n" for h in header_cells
                )
                data_cells = ""
                for row_line in data_rows_raw:
                    cells = [c.strip() for c in row_line.split("|") if c.strip() != ""]
                    # Pad or trim to expected column count
                    while len(cells) < n_cols:
                        cells.append("")
                    cells = cells[:n_cols]
                    data_cells += "".join(f"  [{_inline_md_to_typst(c)}],\n" for c in cells)
                out.append(
                    f"#table(\n"
                    f"  columns: {col_spec},\n"
                    f'  stroke: 0.5pt + rgb("dddddd"),\n'
                    f"{header_row}"
                    f"{data_cells}"
                    f")\n\n"
                )
            continue

        # --- Headings ---
        if line.startswith("#### "):
            out.append(f"==== {_inline_md_to_typst(line[5:])}\n\n")
            i += 1
            continue
        if line.startswith("### "):
            out.append(f"=== {_inline_md_to_typst(line[4:])}\n\n")
            i += 1
            continue
        if line.startswith("## "):
            out.append(f"== {_inline_md_to_typst(line[3:])}\n\n")
            i += 1
            continue
        if line.startswith("# "):
            out.append(f"= {_inline_md_to_typst(line[2:])}\n\n")
            i += 1
            continue

        # --- Blockquote ---
        if line.startswith("> "):
            bq_text = line[2:]
            bq_inner = _inline_md_to_typst(bq_text)
            out.append(
                '#rect(stroke: (left: 3pt + rgb("#dc3545")), '
                f"inset: (left: 8pt, top: 2pt, bottom: 2pt, right: 4pt))[{bq_inner}]\n\n"
            )
            i += 1
            continue

        # --- Blank line ---
        if not line.strip():
            out.append("\n")
            i += 1
            continue

        # --- Plain paragraph ---
        out.append(_inline_md_to_typst(line) + "\n\n")
        i += 1

    return "".join(out)


def _inline_md_to_typst(text: str) -> str:
    """Convert inline markdown (bold, inline code) to Typst inline markup."""
    # Bold: **text** → *text*
    # Process inline code first to avoid escaping content inside backticks
    result = ""
    pos = 0
    while pos < len(text):
        # Inline code: `text`
        if text[pos] == "`":
            end = text.find("`", pos + 1)
            if end != -1:
                inner = text[pos + 1 : end]
                # Escape for Typst raw inline
                inner_escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
                result += f'#raw("{inner_escaped}")'
                pos = end + 1
                continue
        # Bold: **text**
        if text[pos : pos + 2] == "**":
            end = text.find("**", pos + 2)
            if end != -1:
                inner = text[pos + 2 : end]
                result += f"*{_t(inner)}*"
                pos = end + 2
                continue
        # Regular character — escape it
        result += _t(text[pos])
        pos += 1
    return result


def _provenance_section(nfr_result: RunResult) -> str:
    """Render run metadata as a Typst table."""
    meta = nfr_result.run_metadata
    if not meta:
        return ""
    repo_label = Path(meta.target_repo).name
    rows = [
        f"  [*Repository*], [`{_t(repo_label)}`],",
        f"  [*Target path*], [`{_t(meta.target_repo)}`],",
        f"  [*Report generated*], [{_t(meta.timestamp)}],",
    ]
    if meta.git_sha:
        dirty = " (dirty)" if meta.git_dirty else ""
        sha_short = meta.git_sha[:10]
        rows.append(f"  [*Commit*], [`{_t(sha_short)}{_t(dirty)}`],")
    if meta.git_branch:
        rows.append(f"  [*Branch / tag*], [{_t(meta.git_branch)}],")
    rows.append(f"  [*Tool version*], [{_t(meta.tool_version)}],")

    rows_str = "\n".join(rows)
    return f"""#table(
  columns: (auto, 1fr),
  stroke: 0.5pt + rgb("dddddd"),
{rows_str}
)
"""


def _test_results_section(pytest_result: PytestResult | None) -> str:
    """Render test results as Typst markup."""
    if pytest_result is None:
        return "== Test Results\n\n_Test execution was not performed._\n\n"

    if pytest_result.exit_code == -1:
        return f"== Test Results\n\n{_t(pytest_result.raw_output)}\n\n"

    all_green = pytest_result.failed == 0 and pytest_result.errors == 0
    icon = "✓" if all_green else "✗"
    status = "PASSED" if all_green else "FAILED"
    color = "#28a745" if all_green else "#dc3545"

    return f"""== Test Results

#text(fill: rgb("{color}"), weight: "bold")[{icon} {status}]

#table(
  columns: (auto, auto),
  stroke: 0.5pt + rgb("dddddd"),
  [*Metric*], [*Count*],
  [Passed], [{pytest_result.passed}],
  [Failed], [{pytest_result.failed}],
  [Skipped], [{pytest_result.skipped}],
  [Errors], [{pytest_result.errors}],
  [Duration], [{pytest_result.duration_seconds:.2f}s],
)

"""


def _category_severity_table(findings: list[Finding], title: str) -> str:
    """Render category x severity count table as Typst markup."""
    counts: dict[str, Counter[Severity]] = defaultdict(Counter)
    for f in findings:
        cat = _extract_category(f.rule_id)
        counts[cat][f.severity] += 1

    categories = sorted(counts.keys())
    col_totals: Counter[Severity] = Counter()

    # Build header row
    sev_headers = "".join(
        f'  [#text(fill: rgb("{_SEVERITY_COLORS[sev]}"))[*{sev.capitalize()}*]],\n'
        for sev in _SEVERITY_ORDER
    )
    header_row = f"  [*Category*],\n{sev_headers}  [*Total*],"

    # Build data rows
    data_rows: list[str] = []
    for cat in categories:
        row_total = 0
        cells = []
        for sev in _SEVERITY_ORDER:
            n = counts[cat].get(sev, 0)
            row_total += n
            col_totals[sev] += n
            cells.append(f"  [{n if n else '-'}],")
        data_rows.append(f"  [*{_t(cat)}*],\n" + "\n".join(cells) + f"\n  [*{row_total}*],")

    # Total row
    grand_total = sum(col_totals.values())
    total_cells = []
    for sev in _SEVERITY_ORDER:
        n = col_totals.get(sev, 0)
        total_cells.append(f"  [*{n}*]," if n else "  [-],")
    data_rows.append("  [*Total*],\n" + "\n".join(total_cells) + f"\n  [*{grand_total}*],")

    col_spec = "(auto, " + ", ".join(["auto"] * len(_SEVERITY_ORDER)) + ", auto)"

    rows_str = "\n".join(data_rows)
    return f"""=== {_t(title)}

#table(
  columns: {col_spec},
  stroke: 0.5pt + rgb("dddddd"),
{header_row}
{rows_str}
)

"""


def _findings_section(findings: list[Finding], title: str) -> str:
    """Render findings grouped by RAG and rule, as Typst markup."""
    if not findings:
        return f"== {_t(title)}\n\n_No findings._\n\n"

    by_rag: dict[RAG, list[Finding]] = {}
    for f in findings:
        by_rag.setdefault(f.rag, []).append(f)

    parts = [f"== {_t(title)}\n"]
    for rag in _RAG_ORDER:
        group = by_rag.get(rag, [])
        if not group:
            continue
        rag_color = _RAG_COLORS.get(rag, "#666666")
        parts.append(
            f'=== #text(fill: rgb("{rag_color}"))[{_t(rag.upper())}] ({len(group)})\n'
        )

        issue_groups: dict[tuple[str, str], list[Finding]] = {}
        for f in group:
            key = (f.rule_id, f.summary)
            issue_groups.setdefault(key, []).append(f)

        for (rule_id, summary), occurrences in issue_groups.items():
            representative = occurrences[0]
            border_color = _RAG_COLORS.get(representative.rag, "#dddddd")
            inset = "inset: (left: 8pt, top: 4pt, bottom: 4pt, right: 4pt)"
            parts.append(
                f'#rect(stroke: (left: 3pt + rgb("{border_color}")), {inset})[\n'
                f"*[{_t(rule_id)}]* {_t(summary)}\n\n"
                f"Recommendation: {_t(representative.recommendation)}\n\n"
            )
            # Occurrences table
            occ_rows = "".join(
                f"  [`{_t(occ.evidence_locator)}`], "
                f"[{_t(occ.severity)}], [{occ.confidence:.0%}],\n"
                for occ in occurrences
            )
            parts.append(
                "#table(\n"
                "  columns: (1fr, auto, auto),\n"
                '  stroke: 0.5pt + rgb("eeeeee"),\n'
                "  [*Location*], [*Severity*], [*Confidence*],\n"
                f"{occ_rows}"
                ")\n]\n\n"
            )

    return "\n".join(parts)


def _exec_summary_section(summary: ExecSummary) -> str:
    """Render executive summary as Typst markup."""
    label, color, bg = _VERDICT_STYLES.get(summary.verdict, ("Unknown", "#666666", "#f0f0f0"))

    parts = [
        "== Executive Summary (AI-generated)\n",
        f'#rect(fill: rgb("{bg}"), stroke: 2pt + rgb("{color}"), radius: 4pt, width: 100%)[',
        "#grid(columns: (1fr, auto),",
        f'  [#text(fill: rgb("{color}"), weight: "bold", size: 14pt)[{_t(label)}]],',
        f'  [#text(fill: rgb("{color}"), weight: "bold", size: 20pt)'
        f"[{summary.overall_score}/100]],",
        ")",
        f"\n{_t(summary.verdict_explanation)}\n",
        '#text(size: 8pt, fill: rgb("666666"))'
        "[This score is an AI-generated holistic assessment"
        " and may differ from the deterministic Design Maturity Score."
        " See the LLM Usage and Scoring Methodology sections in the appendix for details.]",
        "]\n",
    ]

    if summary.risk_highlights:
        parts.append("=== Key Risks\n")
        _bq_inset = "inset: (left: 8pt, top: 2pt, bottom: 2pt, right: 4pt)"
        for risk in summary.risk_highlights:
            parts.append(
                f'#rect(stroke: (left: 3pt + rgb("#dc3545")), {_bq_inset})[{_t(risk)}]\n'
            )

    if summary.remediation_priorities:
        parts.append("\n=== Remediation Priorities\n")
        for item in summary.remediation_priorities:
            urgency_colors = {
                "immediate": "#dc3545",
                "short-term": "#fd7e14",
                "medium-term": "#6c757d",
            }
            urg_color = urgency_colors.get(item.urgency, "#666666")
            urgency_line = (
                f"*{_t(item.title)}* "
                f'#text(fill: rgb("{urg_color}"))[(urgency: {_t(item.urgency)})]'
            )
            parts.append(
                '#rect(fill: rgb("f8f9fa"), radius: 4pt, inset: 8pt, width: 100%)[\n'
                f"{urgency_line}\n\n"
                f"{_t(item.description)}\n]\n"
            )

    parts.append(f"\n=== Production Risks\n\n{_t(summary.production_risks)}\n")
    parts.append(f"\n=== Open-Source Readiness\n\n{_t(summary.open_source_readiness)}\n")

    return "\n".join(parts)


def _diagrams_section(
    diagram_paths: dict[str, Path] | None,
    diagrams: dict[str, str] | None,
    image_files: dict[str, bytes],
    counter: list[int],
) -> str:
    """Render diagrams section from pre-rendered PNGs and/or mermaid text."""
    if not diagram_paths and not diagrams:
        return ""

    parts = ["== Diagrams\n\n"]

    if diagram_paths:
        for name, path in diagram_paths.items():
            counter[0] += 1
            idx = counter[0]
            try:
                raw = path.read_bytes()
            except OSError:
                logger.warning("Could not read diagram file: %s", path)
                parts.append(f"=== {_t(name)}\n\n_Image file not found._\n\n")
                continue
            filename = f"diagram_path_{idx}{path.suffix}"
            image_files[filename] = raw
            parts.append(f"=== {_t(name)}\n\n")
            parts.append(_image_typst(filename, raw))
            parts.append("\n")

    if diagrams:
        for name, mermaid_text in diagrams.items():
            parts.append(f"=== {_t(name)}\n\n")
            parts.append(_render_mermaid_for_typst(mermaid_text, image_files, counter))
            parts.append("\n")

    return "".join(parts)


def _build_typst_document(sections: list[str], title: str) -> str:
    """Assemble the full Typst document."""
    preamble = (
        '#set page(paper: "a4", margin: (x: 1.5cm, y: 2cm), numbering: "1 / 1")\n'
        '#set text(font: "Liberation Sans", size: 10pt)\n'
        "#set heading(numbering: none)\n\n"
    )
    return preamble + "\n".join(sections)


def render_pdf(
    *,
    nfr_result: RunResult,
    output_path: Path,
    hygiene_result: RunResult | None = None,
    exec_summary: ExecSummary | None = None,
    pytest_result: PytestResult | None = None,
    deps_section_md: str = "",
    jdepend_section_md: str = "",
    adr_section_md: str = "",
    derived_adrs_section_md: str = "",
    diagram_paths: dict[str, Path] | None = None,
    diagrams: dict[str, str] | None = None,
    score_section_md: str = "",
    title: str = "NFR Review Report",
    llm_info: tuple[str, str] | None = None,
) -> Path:
    """Render a complete PDF report from scan results.

    Returns the output path on success.
    """
    from nfr_review.output.classify import partition_findings, partition_findings_by_origin

    all_findings: list[Finding] = list(nfr_result.findings)
    if hygiene_result:
        all_findings.extend(hygiene_result.findings)

    first_party, dependency = partition_findings_by_origin(all_findings)
    source_findings, test_findings = partition_findings(first_party)

    # Image files collected during document assembly; written to temp dir before compile
    image_files: dict[str, bytes] = {}
    # Shared counter for unique image filenames
    counter: list[int] = [0]

    sections: list[str] = []

    meta = nfr_result.run_metadata
    repo_label = Path(meta.target_repo).name if meta else ""
    heading = f"{_t(title)} --- {_t(repo_label)}" if repo_label else _t(title)
    sections.append(f"= {heading}\n\n")
    sections.append(_provenance_section(nfr_result))

    if exec_summary:
        sections.append("#pagebreak()\n\n")
        sections.append(_exec_summary_section(exec_summary))

    sections.append(_category_severity_table(first_party, "Findings Summary"))

    if score_section_md:
        body = score_section_md
        if body.startswith("## "):
            body = body.split("\n", 1)[1] if "\n" in body else ""
        sections.append(_md_to_typst(body, image_files, counter))

    # Diagrams section
    diag_section = _diagrams_section(diagram_paths, diagrams, image_files, counter)
    if diag_section:
        sections.append(diag_section)

    sections.append(_test_results_section(pytest_result))

    sections.append("#pagebreak()\n\n")
    sections.append(_findings_section(source_findings, "Source Code Findings"))

    sections.append(_findings_section(test_findings, "Test Code Findings"))

    if dependency:
        sections.append("#pagebreak()\n\n")
        sections.append("== Dependency Findings\n\n")
        _dep_note = (
            "The following findings originate from dependency or vendored code. "
            "They are excluded from the Design Maturity Score."
        )
        sections.append(f'#text(size: 9pt, fill: rgb("666666"))[{_dep_note}]\n\n')
        sections.append(_category_severity_table(dependency, "Dependency Findings Summary"))
        sections.append(_findings_section(dependency, "Dependency Findings Detail"))

    # Markdown sections — convert to Typst
    for md_content, md_title in [
        (adr_section_md, "Architecture Decision Records"),
        (jdepend_section_md, "JDepend Structural Analysis"),
        (derived_adrs_section_md, "Derived Architecture Decision Records"),
    ]:
        if md_content:
            body = md_content
            if body.startswith("## "):
                body = body.split("\n", 1)[1] if "\n" in body else ""
            sections.append(f"== {_t(md_title)}\n\n")
            sections.append(_md_to_typst(body, image_files, counter))

    if deps_section_md:
        body = deps_section_md
        if body.startswith("## "):
            body = body.split("\n", 1)[1] if "\n" in body else ""
        sections.append("#pagebreak()\n\n")
        sections.append("== Appendix A --- Dependency Tree\n\n")
        sections.append(_md_to_typst(body, image_files, counter))

    typst_doc = _build_typst_document(sections, title)

    import typst

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if image_files:
        with tempfile.TemporaryDirectory() as tmpdir:
            for filename, raw in image_files.items():
                (Path(tmpdir) / filename).write_bytes(raw)
            pdf_bytes = typst.compile(typst_doc.encode(), root=tmpdir)
    else:
        pdf_bytes = typst.compile(typst_doc.encode())

    output_path.write_bytes(pdf_bytes)
    logger.info("PDF written to %s (%d bytes)", output_path, output_path.stat().st_size)
    return output_path


__all__ = ["render_pdf"]
