# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: go-goroutine-leak — flags goroutine launches that may leak."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.go_ast import GoAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class GoGoroutineLeakRule(FieldRule[GoAstFilePayload]):
    """Flag goroutine launches without explicit lifecycle management."""

    id = "go-goroutine-leak"
    collector_name = "go-ast"
    evidence_kind = "go-ast-file"
    payload_type = GoAstFilePayload
    pattern_tag = "go-goroutine-leak"
    default_confidence = 0.8
    all_clear_summary = "No goroutine launches detected."

    def check(self, payload: GoAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for launch in payload.goroutine_launches:
            yield Hit(
                rag="amber",
                severity="medium",
                summary="Goroutine launch may leak without lifecycle management",
                recommendation=(
                    "Use context.Context, sync.WaitGroup, or errgroup"
                    " for goroutine lifecycle management."
                ),
                locator=f"{payload.file_path}:{launch.line}",
            )


__all__ = ["GoGoroutineLeakRule"]
