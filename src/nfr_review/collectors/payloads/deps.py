# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for dependency collectors.

All five dependency collectors (java, python, go, nodejs, csharp) emit
the same top-level shape; they differ only in the ``kind`` string and
optional per-ecosystem fields on the dependency item.
"""

from __future__ import annotations

from nfr_review.models import BasePayload


class DependencyItem(BasePayload):
    """A single resolved dependency from any ecosystem."""

    name: str
    declared_version: str
    version_constraint: str
    source_file: str
    latest_version: str | None = None
    latest_release_date: str | None = None
    deps_dev_status: str = "error"
    scope: str | None = None
    indirect: bool | None = None


class DepsPayload(BasePayload):
    """Common payload for all ``*-deps`` evidence kinds."""

    dependencies: list[DependencyItem]
    manifest_files_found: list[str]
    enrichment_errors: list[str]


__all__ = ["DependencyItem", "DepsPayload"]
