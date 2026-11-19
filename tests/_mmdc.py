# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Arguments tests pass when they run mmdc directly.

Production rendering (``nfr_review.output.render``) adds ``-p <puppeteer
config>`` when one is configured, e.g. to disable Chromium's sandbox on CI
runners where it cannot start. Tests that call mmdc themselves must do the
same, or they fail there with "Failed to launch the browser process".
"""

from __future__ import annotations

from nfr_review.output.render import _puppeteer_config_path


def puppeteer_args() -> list[str]:
    """``["-p", <config>]`` when a puppeteer config is set, else ``[]``."""
    cfg = _puppeteer_config_path()
    return ["-p", cfg] if cfg else []
