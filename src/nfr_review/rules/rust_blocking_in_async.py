# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: rust-blocking-in-async — flags blocking calls (thread::sleep, std::fs,
a sync Mutex lock with no .await) inside an async fn, which block the whole
async executor thread instead of yielding.
"""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.rust_ast import RustAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit

_RECOMMENDATIONS = {
    "thread::sleep": "Use tokio::time::sleep(...).await instead of std::thread::sleep.",
    "fs": (
        "Use tokio::fs (or spawn_blocking for CPU/IO-bound work)"
        " instead of std::fs inside async code."
    ),
    "sync-lock-no-await": (
        "Use tokio::sync::Mutex/RwLock (awaited) inside async code,"
        " or confirm this std lock is held only briefly and never across an .await."
    ),
}


class RustBlockingInAsyncRule(FieldRule[RustAstFilePayload]):
    """Flag blocking calls inside an async fn that block the executor thread."""

    id = "rust-blocking-in-async"
    collector_name = "rust-ast"
    evidence_kind = "rust-ast-file"
    payload_type = RustAstFilePayload
    pattern_tag = "rust-blocking-in-async"
    required_tech: list[str] = ["rust"]
    default_confidence = 0.75
    all_clear_summary = "No blocking calls detected inside async functions."

    def check(self, payload: RustAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for call in payload.async_blocking_calls:
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(
                    f"Blocking call `{call.call}` in async fn `{call.function_name}`"
                    " blocks the executor thread"
                ),
                recommendation=_RECOMMENDATIONS.get(
                    call.kind, "Avoid blocking calls inside async functions."
                ),
                locator=f"{payload.file_path}:{call.line}",
            )


__all__ = ["RustBlockingInAsyncRule"]
