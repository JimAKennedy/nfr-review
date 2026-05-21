# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Hygiene audit registries, separate from the core NFR registries."""

from __future__ import annotations

from nfr_review.protocols import Collector, Rule
from nfr_review.registry import Registry

hygiene_collector_registry: Registry[Collector] = Registry("hygiene-collector")
hygiene_rule_registry: Registry[Rule] = Registry("hygiene-rule")

__all__ = ["hygiene_collector_registry", "hygiene_rule_registry"]
