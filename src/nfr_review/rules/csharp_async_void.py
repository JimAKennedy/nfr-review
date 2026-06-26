# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: csharp-async-void — detects async void methods in C# code."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.csharp_ast import CSharpAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class CSharpAsyncVoidRule(FieldRule[CSharpAstFilePayload]):
    """Flag async void methods that should be async Task."""

    id = "csharp-async-void"
    collector_name = "csharp-ast"
    evidence_kind = "csharp-ast-file"
    payload_type = CSharpAstFilePayload
    pattern_tag = "csharp-async-void"
    default_confidence = 0.95
    all_clear_summary = "No async void methods detected."

    def check(self, payload: CSharpAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for method in payload.methods:
            if method.is_async and method.return_type == "void":
                yield Hit(
                    rag="red",
                    severity="high",
                    summary=f"async void method '{method.name}'",
                    recommendation=(
                        "Change return type to async Task. async void"
                        " silently swallows exceptions and cannot be awaited."
                    ),
                    locator=f"{payload.file_path}:{method.line}",
                )


__all__ = ["CSharpAsyncVoidRule"]
