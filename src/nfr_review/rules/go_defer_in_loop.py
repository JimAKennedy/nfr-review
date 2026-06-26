# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: go-defer-in-loop — detects defer statements inside loop bodies."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.go_ast import GoAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class GoDeferInLoopRule(FieldRule[GoAstFilePayload]):
    """Flag defer statements inside for loops that accumulate deferred calls."""

    id = "go-defer-in-loop"
    collector_name = "go-ast"
    evidence_kind = "go-ast-file"
    payload_type = GoAstFilePayload
    pattern_tag = "go-defer-in-loop"
    all_clear_summary = "No defer-in-loop patterns detected."

    def check(self, payload: GoAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for stmt in payload.defer_statements:
            if stmt.in_loop:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary="Defer inside loop accumulates deferred calls",
                    recommendation=(
                        "Extract the loop body to a separate function"
                        " or use explicit close instead of defer."
                    ),
                    locator=f"{payload.file_path}:{stmt.line}",
                )


__all__ = ["GoDeferInLoopRule"]
