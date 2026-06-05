# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Generate a self-contained HTML rule catalogue from ``list-rules --format json``.

Reads JSON from stdin or ``--input`` file and produces a single HTML page
with client-side search and filtering by category, severity, and tags.
No external dependencies (CSS/JS are inlined).

Usage::

    nfr-review list-rules --format json | python scripts/generate_catalogue.py
    python scripts/generate_catalogue.py --input rules.json --output catalogue.html
"""

from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path
from typing import Any

_SEVERITY_COLORS: dict[str, str] = {
    "critical": "#dc2626",
    "high": "#ea580c",
    "medium": "#ca8a04",
    "low": "#2563eb",
    "info": "#6b7280",
}

_SEVERITY_BG: dict[str, str] = {
    "critical": "#fef2f2",
    "high": "#fff7ed",
    "medium": "#fefce8",
    "low": "#eff6ff",
    "info": "#f9fafb",
}

_SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


def _severity_sort_key(rule: dict[str, Any]) -> tuple[int, str]:
    sev = rule.get("severity", "info")
    idx = _SEVERITY_ORDER.index(sev) if sev in _SEVERITY_ORDER else len(_SEVERITY_ORDER)
    return (idx, rule.get("id", ""))


def _build_html(rules: list[dict[str, Any]]) -> str:
    rules_sorted = sorted(rules, key=_severity_sort_key)

    categories = sorted({r.get("category", "") for r in rules})
    severities = [s for s in _SEVERITY_ORDER if any(r.get("severity") == s for r in rules)]

    rows: list[str] = []
    for r in rules_sorted:
        rid = escape(r.get("id", ""))
        sev = r.get("severity", "info")
        cat = escape(r.get("category", ""))
        tags = ", ".join(escape(t) for t in r.get("tags", []))
        desc = escape(r.get("description", ""))
        refs = ", ".join(escape(c) for c in r.get("compliance_refs", []))
        color = _SEVERITY_COLORS.get(sev, "#6b7280")
        bg = _SEVERITY_BG.get(sev, "#f9fafb")

        search_text = escape((rid + " " + desc + " " + tags).lower())
        rows.append(
            f'<tr data-severity="{escape(sev)}" data-category="{cat}" '
            f'data-tags="{escape(tags.lower())}" '
            f'data-search="{search_text}">'
            f"<td><code>{rid}</code></td>"
            f'<td><span class="badge" style="background:{bg};color:{color};'
            f'border:1px solid {color}">{escape(sev)}</span></td>'
            f"<td>{cat}</td>"
            f"<td>{tags}</td>"
            f"<td>{desc}</td>"
            f"<td>{refs}</td>"
            f"</tr>"
        )

    cat_options = "".join(
        f'<option value="{escape(c)}">{escape(c)}</option>' for c in categories
    )
    sev_options = "".join(
        f'<option value="{escape(s)}">{escape(s)}</option>' for s in severities
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>nfr-review Rule Catalogue</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:#f8fafc;color:#1e293b;line-height:1.5}}
.container{{max-width:1280px;margin:0 auto;padding:24px}}
h1{{font-size:1.5rem;margin-bottom:4px}}
.subtitle{{color:#64748b;margin-bottom:20px;font-size:0.9rem}}
.filters{{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap;align-items:center}}
.filters input,.filters select{{padding:6px 10px;border:1px solid #cbd5e1;border-radius:6px;
  font-size:0.875rem;background:#fff}}
.filters input{{min-width:240px}}
.filters select{{min-width:140px}}
.count{{color:#64748b;font-size:0.85rem;margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;
  overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.06)}}
th{{background:#f1f5f9;text-align:left;padding:10px 12px;font-size:0.8rem;
  text-transform:uppercase;letter-spacing:0.05em;color:#475569;
  border-bottom:2px solid #e2e8f0}}
td{{padding:8px 12px;border-bottom:1px solid #f1f5f9;font-size:0.85rem;
  vertical-align:top}}
tr:hover{{background:#f8fafc}}
tr.hidden{{display:none}}
code{{background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:0.8rem}}
.badge{{display:inline-block;padding:2px 8px;border-radius:9999px;font-size:0.75rem;
  font-weight:600;text-transform:uppercase;letter-spacing:0.03em}}
footer{{margin-top:24px;text-align:center;color:#94a3b8;font-size:0.8rem}}
</style>
</head>
<body>
<div class="container">
<h1>nfr-review Rule Catalogue</h1>
<p class="subtitle">{len(rules)} rules across {len(categories)} categories</p>
<div class="filters">
  <input type="text" id="search" placeholder="Search rules…" autofocus>
  <select id="catFilter"><option value="">All categories</option>{cat_options}</select>
  <select id="sevFilter"><option value="">All severities</option>{sev_options}</select>
</div>
<p class="count" id="matchCount">Showing {len(rules)} of {len(rules)} rules</p>
<table>
<thead><tr><th>ID</th><th>Severity</th><th>Category</th><th>Tags</th><th>Description</th><th>Compliance</th></tr></thead>
<tbody id="ruleBody">
{"".join(rows)}
</tbody>
</table>
<footer>Generated by nfr-review &mdash; <a href="https://github.com/JimAKennedy/nfr-review">source</a></footer>
</div>
<script>
(function(){{
  const search=document.getElementById('search');
  const catF=document.getElementById('catFilter');
  const sevF=document.getElementById('sevFilter');
  const rows=document.querySelectorAll('#ruleBody tr');
  const count=document.getElementById('matchCount');
  const total=rows.length;
  function filter(){{
    const q=search.value.toLowerCase();
    const cat=catF.value;
    const sev=sevF.value;
    let shown=0;
    rows.forEach(function(r){{
      const matchQ=!q||r.dataset.search.indexOf(q)!==-1;
      const matchC=!cat||r.dataset.category===cat;
      const matchS=!sev||r.dataset.severity===sev;
      if(matchQ&&matchC&&matchS){{r.classList.remove('hidden');shown++}}
      else{{r.classList.add('hidden')}}
    }});
    count.textContent='Showing '+shown+' of '+total+' rules';
  }}
  search.addEventListener('input',filter);
  catF.addEventListener('change',filter);
  sevF.addEventListener('change',filter);
}})();
</script>
</body>
</html>"""


def generate_catalogue(
    rules: list[dict[str, Any]],
    output: Path | None = None,
) -> str:
    """Build HTML catalogue and optionally write to *output*.

    Returns the HTML string.
    """
    html = _build_html(rules)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html, encoding="utf-8")
    return html


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate HTML rule catalogue")
    parser.add_argument("--input", type=Path, help="JSON input file (default: stdin)")
    parser.add_argument("--output", type=Path, help="HTML output file (default: stdout)")
    args = parser.parse_args(argv)

    if args.input:
        raw = args.input.read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()

    rules: list[dict[str, Any]] = json.loads(raw)
    html = generate_catalogue(rules, args.output)

    if args.output is None:
        sys.stdout.write(html)


if __name__ == "__main__":
    main()
