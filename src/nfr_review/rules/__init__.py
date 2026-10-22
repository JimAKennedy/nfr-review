# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Built-in rules. Importing this package auto-registers them."""

from __future__ import annotations

import importlib
import logging
import pkgutil

from nfr_review.plugin_discovery import RULES_GROUP, discover_plugins
from nfr_review.registry import rule_registry

logger = logging.getLogger(__name__)

_EXCLUDE = frozenset(
    {"__init__", "ast_common", "rule_helpers", "_cross_language", "framework"}
)

# Rules belonging to optional lang packs — only load if the lang pack is installed.
_OPTIONAL_LANG_RULES = frozenset({
    "java_exception", "java_health", "java_package_subdivision", "java_resilience",
    "java_thread_pool", "spring_actuator", "spring_logging", "spring_profile",
    "jacoco_coverage", "jacoco_threshold", "jdepend_cycle", "jdepend_distance",
    "jdepend_instability", "dormant_classes",
    "go_defer_in_loop", "go_error_ignored", "go_goroutine_leak", "go_http_no_timeout",
    "go_package_subdivision",
    "rust_blocking_in_async", "rust_http_no_timeout", "rust_mutex_lock_unwrap",
    "rust_unbounded_spawn_in_loop", "rust_unwrap_expect",
    "csharp_async_void", "csharp_blocking_async", "csharp_configure_await",
    "csharp_disposable_no_using",
    "nodejs_callback_error_ignored", "nodejs_floating_promise", "nodejs_promise_no_catch",
    "nodejs_sync_fs_api",
    "cpp_clang_format", "cpp_clang_tidy", "cpp_dormant_classes", "cpp_exception_safety",
    "cpp_include_guards", "cpp_raw_memory", "cpp_sanitizer_ci",
    "cmake_build_config", "cmake_fetchcontent_pinning", "cmake_minimum_version",
    "gatling_performance",
})

_discovered: list[str] = []
for _info in pkgutil.iter_modules(__path__):
    if _info.name in _EXCLUDE:
        continue
    if _info.name in _OPTIONAL_LANG_RULES:
        try:
            importlib.import_module(f"{__name__}.{_info.name}")
            _discovered.append(_info.name)
        except ImportError:
            logger.debug("Optional lang rule %r skipped — package not installed", _info.name)
    else:
        importlib.import_module(f"{__name__}.{_info.name}")
        _discovered.append(_info.name)

discover_plugins(rule_registry, RULES_GROUP)

__all__ = sorted(_discovered)
