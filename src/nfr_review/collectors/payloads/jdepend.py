# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the JDepend collector."""

from __future__ import annotations

from nfr_review.models import BasePayload


class JDependPackageMetrics(BasePayload):
    """Metrics for a single Java package."""

    name: str
    total_classes: int = 0
    concrete_classes: int = 0
    abstract_classes: int = 0
    ca: int = 0
    ce: int = 0
    a: float = 0.0
    i: float = 0.0
    d: float = 0.0
    v: int = 0


class JDependPackagesPayload(BasePayload):
    """Payload for kind='jdepend-packages' evidence."""

    bytecode_dir: str
    packages: list[JDependPackageMetrics]


class JDependSummaryPayload(BasePayload):
    """Payload for kind='jdepend-summary' evidence."""

    total_packages: int
    packages_with_cycles: int
    cycle_groups: list[list[str]]
    avg_distance: float
    max_distance: float


class JDependSkipPayload(BasePayload):
    """Payload for kind='jdepend-skip' evidence."""

    reason: str
    stderr: str = ""


__all__ = [
    "JDependPackageMetrics",
    "JDependPackagesPayload",
    "JDependSkipPayload",
    "JDependSummaryPayload",
]
