# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: csharp-configure-await — detects await expressions missing ConfigureAwait(false)."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.csharp_ast import CSharpAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class CSharpConfigureAwaitRule(FieldRule[CSharpAstFilePayload]):
    """Flag await expressions that lack ConfigureAwait(false) in library code."""

    id = "csharp-configure-await"
    collector_name = "csharp-ast"
    evidence_kind = "csharp-ast-file"
    payload_type = CSharpAstFilePayload
    pattern_tag = "csharp-configure-await"
    default_confidence = 0.8
    all_clear_summary = "All await expressions use ConfigureAwait."

    def check(self, payload: CSharpAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for await_expr in payload.await_expressions:
            if not await_expr.has_configure_await:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary="await without ConfigureAwait(false)",
                    recommendation=(
                        "Add .ConfigureAwait(false) to avoid capturing the"
                        " synchronization context in library code."
                    ),
                    locator=f"{payload.file_path}:{await_expr.line}",
                )


__all__ = ["CSharpConfigureAwaitRule"]
