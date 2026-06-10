# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Self-contained HTML report renderer with client-side Mermaid.js diagrams."""

from __future__ import annotations

import html
import re
from importlib.resources import files


def _load_mermaid_js() -> str:
    return files("nfr_review.data").joinpath("mermaid.min.js").read_text(encoding="utf-8")


_MERMAID_FENCE_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)

_REPORT_CSS = """\
:root {
  --bg: #ffffff;
  --fg: #1a1a2e;
  --accent: #0f3460;
  --border: #e0e0e0;
  --code-bg: #f5f5f5;
  --severity-critical: #d32f2f;
  --severity-high: #e64a19;
  --severity-medium: #f57c00;
  --severity-low: #fbc02d;
  --severity-info: #1976d2;
  --rag-red: #d32f2f;
  --rag-amber: #f57c00;
  --rag-green: #388e3c;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1a1a2e;
    --fg: #e0e0e0;
    --accent: #64b5f6;
    --border: #333;
    --code-bg: #16213e;
  }
}
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
    Oxygen, Ubuntu, Cantarell, sans-serif;
  color: var(--fg);
  background: var(--bg);
  line-height: 1.6;
  max-width: 960px;
  margin: 0 auto;
  padding: 2rem 1.5rem;
}
h1 { font-size: 1.8rem; border-bottom: 2px solid var(--accent); padding-bottom: 0.5rem; }
h2 { font-size: 1.4rem; margin-top: 2rem; color: var(--accent); }
h3 { font-size: 1.15rem; margin-top: 1.5rem; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
  font-size: 0.9rem;
}
th, td {
  border: 1px solid var(--border);
  padding: 0.5rem 0.75rem;
  text-align: left;
}
th { background: var(--accent); color: #fff; font-weight: 600; }
tr:nth-child(even) { background: var(--code-bg); }
code {
  background: var(--code-bg);
  padding: 0.15rem 0.35rem;
  border-radius: 3px;
  font-size: 0.88em;
}
pre {
  background: var(--code-bg);
  padding: 1rem;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 0.85rem;
}
pre.mermaid {
  background: transparent;
  text-align: center;
  padding: 0;
}
details { margin: 0.75rem 0; }
summary { cursor: pointer; font-weight: 600; }
.severity-critical { color: var(--severity-critical); font-weight: 700; }
.severity-high { color: var(--severity-high); font-weight: 700; }
.severity-medium { color: var(--severity-medium); font-weight: 600; }
.severity-low { color: var(--severity-low); }
.severity-info { color: var(--severity-info); }
.rag-red { color: var(--rag-red); font-weight: 700; }
.rag-amber { color: var(--rag-amber); font-weight: 700; }
.rag-green { color: var(--rag-green); font-weight: 700; }
hr { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }
@media print {
  body { max-width: none; padding: 1rem; }
  pre.mermaid svg { max-width: 100%; }
}
"""


def _md_to_html(md: str) -> str:
    """Minimal Markdown-to-HTML conversion for report content.

    Handles the subset used by render_markdown_report: headings, tables,
    fenced code blocks, inline code, bold, pipes, and paragraphs.
    """
    lines = md.split("\n")
    out: list[str] = []
    in_table = False
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    para_lines: list[str] = []

    def _flush_para() -> None:
        if para_lines:
            text = " ".join(para_lines)
            out.append(f"<p>{_inline(text)}</p>")
            para_lines.clear()

    def _inline(text: str) -> str:
        text = re.sub(
            r"`([^`]+)`",
            lambda m: f"<code>{html.escape(m.group(1))}</code>",
            text,
        )
        text = re.sub(
            r"\*\*(.+?)\*\*",
            r"<strong>\1</strong>",
            text,
        )
        return text

    for line in lines:
        # Fenced code blocks
        if line.startswith("```") and not in_code:
            _flush_para()
            if in_table:
                out.append("</table>")
                in_table = False
            in_code = True
            code_lang = line[3:].strip()
            code_lines = []
            continue
        if line.startswith("```") and in_code:
            if code_lang == "mermaid":
                out.append(
                    f'<pre class="mermaid">{html.escape(chr(10).join(code_lines))}</pre>'
                )
            else:
                out.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
            in_code = False
            code_lang = ""
            continue
        if in_code:
            code_lines.append(line)
            continue

        stripped = line.strip()

        # Blank line
        if not stripped:
            _flush_para()
            if in_table:
                out.append("</table>")
                in_table = False
            continue

        # Headings
        if stripped.startswith("#"):
            _flush_para()
            if in_table:
                out.append("</table>")
                in_table = False
            level = len(stripped) - len(stripped.lstrip("#"))
            level = min(level, 6)
            text = stripped[level:].strip()
            out.append(f"<h{level}>{_inline(text)}</h{level}>")
            continue

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            _flush_para()
            if in_table:
                out.append("</table>")
                in_table = False
            out.append("<hr>")
            continue

        # Table rows
        if "|" in stripped and stripped.startswith("|"):
            _flush_para()
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            # Skip separator rows
            if all(re.match(r"^[-:]+$", c) for c in cells):
                continue
            if not in_table:
                out.append("<table>")
                tag = "th"
                in_table = True
            else:
                tag = "td"
            row = "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells)
            out.append(f"<tr>{row}</tr>")
            continue

        # Paragraph text
        para_lines.append(stripped)

    _flush_para()
    if in_table:
        out.append("</table>")
    if in_code:
        out.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")

    return "\n".join(out)


def render_html_report(markdown_content: str) -> str:
    """Convert a markdown report into a self-contained HTML file.

    Takes the output of ``render_markdown_report`` and produces HTML with
    bundled Mermaid.js for client-side diagram rendering.
    """
    mermaid_js = _load_mermaid_js()
    body = _md_to_html(markdown_content)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NFR Review Report</title>
<style>
{_REPORT_CSS}
</style>
</head>
<body>
{body}
<script type="module">
{mermaid_js}
mermaid.initialize({{startOnLoad: true, theme: 'neutral'}});
</script>
</body>
</html>"""
