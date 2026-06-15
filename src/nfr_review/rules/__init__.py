# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Built-in rules. Importing this package auto-registers them."""

from __future__ import annotations

import importlib
import pkgutil

_EXCLUDE = frozenset({"__init__", "ast_common", "rule_helpers", "_cross_language"})

_discovered: list[str] = []
for _info in pkgutil.iter_modules(__path__):
    if _info.name in _EXCLUDE:
        continue
    importlib.import_module(f"{__name__}.{_info.name}")
    _discovered.append(_info.name)

__all__ = sorted(_discovered)
