# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Render Mermaid and DOT diagram text to PNG image files.

Uses external tools (mmdc for Mermaid, dot for Graphviz) via subprocess.
Both renderers return the output path on success or ``None`` when the
required tool is not installed, allowing callers to degrade gracefully.
"""

from __future__ import annotations

import logging
import shutil
import subprocess  # nosec B404 — args are hardcoded tool names, not user input
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def render_mermaid_to_png(
    mermaid_text: str,
    output_path: Path,
    *,
    timeout: int = 30,
) -> Path | None:
    """Render Mermaid diagram text to a PNG file via ``mmdc``.

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

    try:
        subprocess.run(  # nosec B603
            [mmdc, "-i", str(tmp_path), "-o", str(output_path), "-b", "transparent"],
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

    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path
    return None


def render_dot_to_png(
    dot_text: str,
    output_path: Path,
    *,
    timeout: int = 30,
) -> Path | None:
    """Render Graphviz DOT text to a PNG file via ``dot``.

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
            [dot_bin, "-Tpng", "-o", str(output_path)],
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


__all__ = ["render_dot_to_png", "render_mermaid_to_png"]
