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
import shutil
import struct
import subprocess  # nosec B404 — args are hardcoded tool names, not user input
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_MERMAID_CONFIG = {"maxTextSize": 200_000}


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

        subprocess.run(  # nosec B603
            [
                mmdc,
                "-i",
                str(tmp_path),
                "-o",
                str(output_path),
                "-b",
                "transparent",
                "-c",
                str(cfg_path),
            ],
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


__all__ = [
    "render_dot_to_png",
    "render_dot_to_svg",
    "render_mermaid_to_png",
    "render_mermaid_to_svg",
]
