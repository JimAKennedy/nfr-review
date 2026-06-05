# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Typed payload models for the documentation hygiene collector."""

from __future__ import annotations

from nfr_review.models import BasePayload

__all__ = [
    "DocumentationPayload",
    "ManifestEntry",
]


class ManifestEntry(BasePayload):
    path: str
    type: str
    fields_present: list[str]
    fields_missing: list[str]


class DocumentationPayload(BasePayload):
    manifests: list[ManifestEntry]
    has_docs_dir: bool
    doc_tool: str
    has_api_docs_hint: bool
    has_py_typed: bool
    classifier_count: int
    has_classifiers: bool
