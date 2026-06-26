# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: csharp-blocking-async — detects blocking on async results."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.csharp_ast import CSharpAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class CSharpBlockingAsyncRule(FieldRule[CSharpAstFilePayload]):
    """Flag synchronous blocking on async operations that risk thread pool starvation."""

    id = "csharp-blocking-async"
    collector_name = "csharp-ast"
    evidence_kind = "csharp-ast-file"
    payload_type = CSharpAstFilePayload
    pattern_tag = "csharp-blocking-async"
    all_clear_summary = "No blocking calls on async operations detected."

    def check(self, payload: CSharpAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for call in payload.blocking_calls:
            yield Hit(
                rag="red",
                severity="high",
                summary=f"Blocking call {call.call_type}",
                recommendation=(
                    "Use await instead of blocking synchronously on async"
                    " operations. Blocking risks thread pool starvation"
                    " and deadlocks."
                ),
                locator=f"{payload.file_path}:{call.line}",
            )


__all__ = ["CSharpBlockingAsyncRule"]
