# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Built-in collectors. Importing this package auto-registers them."""

from __future__ import annotations

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)

_EXCLUDE = frozenset({"__init__", "ast_common"})

# Collectors belonging to optional lang packs — only load if the grammar is installed.
_OPTIONAL_LANG_COLLECTORS = frozenset({
    "java_ast", "java_deps", "spring_config", "jacoco_report", "jdepend",
    "go_ast", "go_deps",
    "rust_ast", "rust_deps",
    "csharp_ast", "csharp_deps",
    "nodejs_ast", "nodejs_deps",
    "cpp_ast", "cmake",
    "gatling",
    "graphify",
})

_discovered: list[str] = []
for _info in pkgutil.iter_modules(__path__):
    if _info.name in _EXCLUDE:
        continue
    if _info.name in _OPTIONAL_LANG_COLLECTORS:
        try:
            importlib.import_module(f"{__name__}.{_info.name}")
            _discovered.append(_info.name)
        except ImportError:
            logger.debug("Optional lang collector %r skipped — package not installed", _info.name)
    else:
        importlib.import_module(f"{__name__}.{_info.name}")
        _discovered.append(_info.name)

__all__ = sorted(_discovered)
