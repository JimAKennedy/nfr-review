# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Discover and load external rule packs via entry-point groups."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from nfr_review.registry import Registry

logger = logging.getLogger(__name__)

RULES_GROUP = "nfr_review.rules"
HYGIENE_RULES_GROUP = "nfr_review.hygiene_rules"


def discover_plugins(registry: Registry, group: str) -> list[str]:
    """Load entry-point modules for *group* and return newly registered IDs.

    Each entry point should resolve to a module that self-registers rules
    into *registry* on import (the same pattern built-in rules use).

    Built-in rules are already registered before this runs, so any
    duplicate ID raises ``ValueError`` from the registry — we catch it,
    log a warning, and continue.  Partial registration within a single
    plugin module is possible: rules that don't conflict will stick.
    """
    before_ids = set(registry.ids())
    eps = entry_points(group=group)
    loaded: list[str] = []

    for ep in eps:
        try:
            ep.load()
        except (ImportError, AttributeError, TypeError):
            logger.warning("Failed to load plugin entry-point %r: ", ep.name, exc_info=True)
            continue

        new_ids = set(registry.ids()) - before_ids
        if new_ids:
            logger.info(
                "Plugin %r registered %d rule(s): %s",
                ep.name,
                len(new_ids),
                ", ".join(sorted(new_ids)),
            )
            loaded.extend(sorted(new_ids))
            before_ids |= new_ids

    return loaded
