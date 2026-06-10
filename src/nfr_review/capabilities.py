# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Runtime feature detection for optional rendering backends.

Checks which external tools and optional Python packages are available
so the CLI can report capabilities and degrade gracefully.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Capabilities:
    git: bool = False
    mmdc: bool = False
    dot: bool = False
    weasyprint: bool = False


def detect_capabilities() -> Capabilities:
    """Probe the runtime environment for optional backends."""
    wp = False
    try:
        import weasyprint as _wp  # type: ignore[import-untyped,import-not-found]  # noqa: F401

        wp = True
    except ImportError:
        pass

    return Capabilities(
        git=shutil.which("git") is not None,
        mmdc=shutil.which("mmdc") is not None,
        dot=shutil.which("dot") is not None,
        weasyprint=wp,
    )


def log_capabilities(caps: Capabilities) -> None:
    """Log detected capabilities at DEBUG level."""
    parts: list[str] = []
    for name in ("git", "mmdc", "dot", "weasyprint"):
        status = "available" if getattr(caps, name) else "not found"
        parts.append(f"{name}={status}")
    logger.debug("runtime capabilities: %s", ", ".join(parts))

    if not caps.weasyprint:
        logger.debug("PDF generation unavailable — install with: pip install nfr-review[pdf]")
    if not caps.mmdc:
        logger.debug("mmdc not found — diagrams use bundled JS (HTML) or SVG fallback (PDF)")
