# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the JDepend collector."""

from __future__ import annotations

from pydantic import AliasChoices, ConfigDict, Field

from nfr_review.models import BasePayload


class JDependPackageMetrics(BasePayload):
    """Metrics for a single Java package.

    JDepend XML uses uppercase tags (Ca, Ce, A, I, D, V) but the model
    stores them as lowercase.  ``AliasChoices`` lets both forms pass
    validation so raw collector dicts (lowercase) and test/XML dicts
    (uppercase) are accepted.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    total_classes: int = 0
    concrete_classes: int = 0
    abstract_classes: int = 0
    ca: int = Field(default=0, validation_alias=AliasChoices("ca", "Ca"))
    ce: int = Field(default=0, validation_alias=AliasChoices("ce", "Ce"))
    a: float = Field(default=0.0, validation_alias=AliasChoices("a", "A"))
    i: float = Field(default=0.0, validation_alias=AliasChoices("i", "I"))
    d: float = Field(default=0.0, validation_alias=AliasChoices("d", "D"))
    v: int = Field(default=0, validation_alias=AliasChoices("v", "V"))


class JDependPackagesPayload(BasePayload):
    """Payload for kind='jdepend-packages' evidence."""

    bytecode_dir: str
    packages: list[JDependPackageMetrics]
    cycle_groups: list[list[str]] = []


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
