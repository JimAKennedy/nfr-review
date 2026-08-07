# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: rust-unbounded-spawn-in-loop — flags tokio::spawn calls inside a loop
with nothing joining or bounding the resulting tasks.
"""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.rust_ast import RustAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class RustUnboundedSpawnInLoopRule(FieldRule[RustAstFilePayload]):
    """Flag tokio::spawn calls inside a loop with no visible task bounding."""

    id = "rust-unbounded-spawn-in-loop"
    collector_name = "rust-ast"
    evidence_kind = "rust-ast-file"
    payload_type = RustAstFilePayload
    pattern_tag = "rust-unbounded-spawn-in-loop"
    required_tech: list[str] = ["rust"]
    default_confidence = 0.8
    all_clear_summary = "No unbounded tokio::spawn calls inside loops detected."

    def check(self, payload: RustAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for call in payload.spawn_calls:
            if not call.in_loop:
                continue
            yield Hit(
                rag="amber",
                severity="medium",
                summary="tokio::spawn inside a loop with no visible task bounding",
                recommendation=(
                    "Collect the JoinHandles into a JoinSet (or Vec + join_all)"
                    " and await them, or bound concurrency with a semaphore,"
                    " instead of spawning an unbounded number of tasks."
                ),
                locator=f"{payload.file_path}:{call.line}",
            )


__all__ = ["RustUnboundedSpawnInLoopRule"]
