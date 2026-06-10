# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Render Mermaid and DOT diagram text to image files.

Uses external tools (mmdc for Mermaid, dot for Graphviz) via subprocess.
Supports both PNG and SVG output formats.  All renderers return the output
path on success or ``None`` when the required tool is not installed,
allowing callers to degrade gracefully.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import struct
import subprocess  # nosec B404 — args are hardcoded tool names, not user input
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_MERMAID_CONFIG = {"maxTextSize": 200_000}


def _puppeteer_config_path() -> str | None:
    env = os.environ.get("PUPPETEER_CONFIG")
    if env and Path(env).is_file():
        return env
    default = Path("/etc/mmdc-puppeteer.json")
    if default.is_file():
        return str(default)
    return None


def render_mermaid_to_png(
    mermaid_text: str,
    output_path: Path,
    *,
    timeout: int = 30,
    scale: int = 1,
    width: int | None = None,
    height: int | None = None,
) -> Path | None:
    """Render Mermaid diagram text to a PNG file via ``mmdc``.

    *scale* sets the output scale factor (``-s``).  Use 3 for high-DPI
    PDFs that need to look sharp when zoomed.

    *width* / *height* set the viewport dimensions in pixels (``-w``/``-H``).
    Larger values give complex diagrams more room for node layout.

    Returns *output_path* on success, ``None`` if mmdc is not available.
    """
    if not mermaid_text.strip():
        return None

    mmdc = shutil.which("mmdc")
    if mmdc is None:
        logger.warning("mmdc (mermaid-cli) not found on PATH — skipping Mermaid rendering")
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as tmp:
        tmp.write(mermaid_text)
        tmp_path = Path(tmp.name)

    cfg_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as cfg_tmp:
            json.dump(_MERMAID_CONFIG, cfg_tmp)
            cfg_path = Path(cfg_tmp.name)

        cmd = [
            mmdc,
            "-i",
            str(tmp_path),
            "-o",
            str(output_path),
            "-b",
            "transparent",
            "-c",
            str(cfg_path),
        ]
        pup_cfg = _puppeteer_config_path()
        if pup_cfg:
            cmd.extend(["-p", pup_cfg])
        if scale > 1:
            cmd.extend(["-s", str(scale)])
        if width is not None:
            cmd.extend(["-w", str(width)])
        if height is not None:
            cmd.extend(["-H", str(height)])

        subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            timeout=timeout,
            check=True,
        )
    except FileNotFoundError:
        logger.warning("mmdc binary disappeared during render")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("mmdc timed out after %ds", timeout)
        return None
    except subprocess.CalledProcessError as exc:
        logger.warning("mmdc failed (rc=%d): %s", exc.returncode, exc.stderr[:500])
        return None
    finally:
        tmp_path.unlink(missing_ok=True)
        if cfg_path is not None:
            cfg_path.unlink(missing_ok=True)

    if not (output_path.exists() and output_path.stat().st_size > 0):
        return None

    if width is not None and scale >= 2:
        raw = output_path.read_bytes()
        if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
            img_w = struct.unpack(">I", raw[16:20])[0]
            min_expected = width * scale * 0.05
            if img_w < min_expected:
                logger.warning(
                    "mmdc produced a %dpx-wide image (expected >=%dpx)"
                    " — likely an error placeholder",
                    img_w,
                    int(min_expected),
                )
                return None

    return output_path


def render_mermaid_to_svg(
    mermaid_text: str,
    output_path: Path,
    *,
    timeout: int = 30,
) -> Path | None:
    """Render Mermaid diagram text to an SVG file via ``mmdc``.

    Returns *output_path* on success, ``None`` if mmdc is not available.
    """
    if not mermaid_text.strip():
        return None

    mmdc = shutil.which("mmdc")
    if mmdc is None:
        logger.warning("mmdc (mermaid-cli) not found on PATH — skipping Mermaid rendering")
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as tmp:
        tmp.write(mermaid_text)
        tmp_path = Path(tmp.name)

    cfg_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as cfg_tmp:
            json.dump(_MERMAID_CONFIG, cfg_tmp)
            cfg_path = Path(cfg_tmp.name)

        cmd = [
            mmdc,
            "-i",
            str(tmp_path),
            "-o",
            str(output_path),
            "-b",
            "transparent",
            "-c",
            str(cfg_path),
        ]
        pup_cfg = _puppeteer_config_path()
        if pup_cfg:
            cmd.extend(["-p", pup_cfg])

        subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            timeout=timeout,
            check=True,
        )
    except FileNotFoundError:
        logger.warning("mmdc binary disappeared during render")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("mmdc timed out after %ds", timeout)
        return None
    except subprocess.CalledProcessError as exc:
        logger.warning("mmdc failed (rc=%d): %s", exc.returncode, exc.stderr[:500])
        return None
    finally:
        tmp_path.unlink(missing_ok=True)
        if cfg_path is not None:
            cfg_path.unlink(missing_ok=True)

    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path
    return None


def render_dot_to_png(
    dot_text: str,
    output_path: Path,
    *,
    timeout: int = 30,
    dpi: int = 96,
) -> Path | None:
    """Render Graphviz DOT text to a PNG file via ``dot``.

    *dpi* controls output resolution (default 96).  Use 288 for high-DPI
    PDFs that need to look sharp when zoomed (3× native).

    Returns *output_path* on success, ``None`` if dot is not available.
    """
    if not dot_text.strip():
        return None

    dot_bin = shutil.which("dot")
    if dot_bin is None:
        logger.warning("dot (graphviz) not found on PATH — skipping DOT rendering")
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [dot_bin, "-Tpng", f"-Gdpi={dpi}", "-o", str(output_path)]

    try:
        subprocess.run(  # nosec B603
            cmd,
            input=dot_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except FileNotFoundError:
        logger.warning("dot binary disappeared during render")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("dot timed out after %ds", timeout)
        return None
    except subprocess.CalledProcessError as exc:
        logger.warning("dot failed (rc=%d): %s", exc.returncode, exc.stderr[:500])
        return None

    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path
    return None


def render_dot_to_svg(
    dot_text: str,
    output_path: Path,
    *,
    timeout: int = 30,
) -> Path | None:
    """Render Graphviz DOT text to an SVG file via ``dot``.

    Returns *output_path* on success, ``None`` if dot is not available.
    """
    if not dot_text.strip():
        return None

    dot_bin = shutil.which("dot")
    if dot_bin is None:
        logger.warning("dot (graphviz) not found on PATH — skipping DOT rendering")
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(  # nosec B603
            [dot_bin, "-Tsvg", "-o", str(output_path)],
            input=dot_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except FileNotFoundError:
        logger.warning("dot binary disappeared during render")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("dot timed out after %ds", timeout)
        return None
    except subprocess.CalledProcessError as exc:
        logger.warning("dot failed (rc=%d): %s", exc.returncode, exc.stderr[:500])
        return None

    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path
    return None


_SEVERITY_COLORS = {
    "Critical": "#dc3545",
    "High": "#e64a19",
    "Medium": "#f57c00",
    "Low": "#fbc02d",
    "Info": "#1976d2",
}


def render_pie_as_svg_fallback(data: dict[str, int]) -> str:
    """Render a horizontal bar chart as SVG from label→count pairs.

    Pure Python, no external tools. Used when mmdc is unavailable.
    """
    if not data:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="400" height="40">'
            '<text x="10" y="25" font-size="14">No data</text>'
            "</svg>"
        )

    bar_h = 28
    gap = 6
    label_w = 100
    max_bar_w = 260
    total_h = len(data) * (bar_h + gap) + 40
    max_val = max(data.values()) or 1

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="{total_h}">',
        '<text x="10" y="20" font-size="14" font-weight="bold">Severity Distribution</text>',
    ]
    y = 35
    for label, count in data.items():
        color = _SEVERITY_COLORS.get(label, "#6c757d")
        bar_w = max(4, int(count / max_val * max_bar_w))
        parts.append(f'<text x="5" y="{y + 18}" font-size="12">{label}</text>')
        parts.append(
            f'<rect x="{label_w}" y="{y}" '
            f'width="{bar_w}" height="{bar_h}" '
            f'fill="{color}" rx="3"/>'
        )
        parts.append(
            f'<text x="{label_w + bar_w + 5}" y="{y + 18}" font-size="12">{count}</text>'
        )
        y += bar_h + gap
    parts.append("</svg>")
    return "\n".join(parts)


def render_flowchart_as_svg_fallback(items: list[str], title: str = "Technologies") -> str:
    """Render a simple box-and-label layout as SVG.

    Pure Python, no external tools. Used for tech overview when mmdc is unavailable.
    """
    if not items:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="400" height="40">'
            '<text x="10" y="25" font-size="14">'
            "No technologies detected</text></svg>"
        )

    box_w = 140
    box_h = 30
    cols = 3
    gap_x = 10
    gap_y = 8
    rows = (len(items) + cols - 1) // cols
    total_w = cols * (box_w + gap_x) + 10
    total_h = rows * (box_h + gap_y) + 40

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{total_h}">',
        f'<text x="10" y="20" font-size="14" font-weight="bold">{title}</text>',
    ]
    for i, item in enumerate(items):
        col = i % cols
        row = i // cols
        x = 5 + col * (box_w + gap_x)
        y = 35 + row * (box_h + gap_y)
        parts.append(
            f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" '
            f'fill="#e8f4fd" stroke="#1976d2" rx="4"/>'
        )
        parts.append(
            f'<text x="{x + box_w // 2}" y="{y + 20}" font-size="11" '
            f'text-anchor="middle">{item}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def render_diagram_as_html_table(mermaid_text: str, title: str) -> str:
    """Last-resort fallback: render diagram data as a styled HTML table.

    Parses Mermaid pie/flowchart text to extract labels and values.
    """
    lines = [ln.strip() for ln in mermaid_text.strip().splitlines() if ln.strip()]

    if any(ln.startswith("pie") for ln in lines):
        rows = []
        for line in lines:
            if '"' in line and ":" in line:
                label = line.split('"')[1]
                val = line.split(":")[-1].strip()
                rows.append((label, val))
        if rows:
            trs = "".join(
                f'<tr><td style="padding:4px 12px">{label}</td>'
                f'<td style="padding:4px 12px;text-align:right">{val}</td></tr>'
                for label, val in rows
            )
            return (
                f"<h3>{title}</h3>"
                f'<table style="border-collapse:collapse;margin:0.5em 0">'
                f"<thead><tr><th>Category</th><th>Count</th></tr></thead>"
                f"<tbody>{trs}</tbody></table>"
            )

    if any("-->" in ln for ln in lines):
        items = set()
        for line in lines:
            if "-->" in line:
                for part in line.split("-->"):
                    part = part.strip()
                    if "[" in part:
                        label = part.split("[")[1].rstrip("]").strip('"')
                        items.add(label)
        if items:
            trs = "".join(
                f'<tr><td style="padding:4px 12px">{item}</td></tr>' for item in sorted(items)
            )
            return (
                f"<h3>{title}</h3>"
                f'<table style="border-collapse:collapse;margin:0.5em 0">'
                f"<thead><tr><th>Component</th></tr></thead>"
                f"<tbody>{trs}</tbody></table>"
            )

    return (
        f"<h3>{title}</h3>"
        f'<pre style="font-size:8pt;background:#f5f5f5;padding:8px;'
        f'border-radius:4px;overflow-x:auto"><code>'
        f"{mermaid_text}</code></pre>"
    )


__all__ = [
    "render_diagram_as_html_table",
    "render_dot_to_png",
    "render_dot_to_svg",
    "render_flowchart_as_svg_fallback",
    "render_mermaid_to_png",
    "render_mermaid_to_svg",
    "render_pie_as_svg_fallback",
]
