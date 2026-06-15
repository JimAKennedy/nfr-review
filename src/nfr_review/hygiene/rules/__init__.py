# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Hygiene rules. Importing this package auto-registers them."""

from __future__ import annotations

import importlib
import pkgutil

_discovered: list[str] = []
for _info in pkgutil.iter_modules(__path__):
    if _info.name == "__init__":
        continue
    importlib.import_module(f"{__name__}.{_info.name}")
    _discovered.append(_info.name)

__all__ = sorted(_discovered)
