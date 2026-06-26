# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: python-star-import — detects wildcard imports (from X import *)."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.python_ast import PythonAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class PythonStarImportRule(FieldRule[PythonAstFilePayload]):
    """Flag wildcard imports that obscure dependencies."""

    id = "python-star-import"
    collector_name = "python-ast"
    evidence_kind = "python-ast-file"
    payload_type = PythonAstFilePayload
    pattern_tag = "star-import"
    default_confidence = 0.95
    all_clear_summary = "No wildcard imports detected."

    def check(self, payload: PythonAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for imp in payload.imports:
            if imp.is_star:
                yield Hit(
                    rag="amber",
                    summary=f"Star import from {imp.module}",
                    recommendation=(
                        "Use explicit imports to make dependencies"
                        " visible and avoid namespace pollution."
                    ),
                    locator=f"{payload.file_path}:{imp.line}",
                )


__all__ = ["PythonStarImportRule"]
