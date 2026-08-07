# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: rust-mutex-lock-unwrap — flags .lock()/.read()/.write().unwrap() on a
std Mutex/RwLock, which panics permanently for the whole process once the
lock is poisoned by any single panicking thread.
"""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.rust_ast import RustAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class RustMutexLockUnwrapRule(FieldRule[RustAstFilePayload]):
    """Flag .lock()/.read()/.write().unwrap() on std::sync Mutex/RwLock."""

    id = "rust-mutex-lock-unwrap"
    collector_name = "rust-ast"
    evidence_kind = "rust-ast-file"
    payload_type = RustAstFilePayload
    pattern_tag = "rust-mutex-lock-unwrap"
    required_tech: list[str] = ["rust"]
    default_confidence = 0.85
    all_clear_summary = "No .lock()/.read()/.write().unwrap() calls detected."

    def check(self, payload: RustAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for call in payload.mutex_lock_unwraps:
            yield Hit(
                rag="amber",
                severity="high",
                summary=(
                    f".{call.lock_method}().unwrap() panics permanently"
                    " once the lock is poisoned"
                ),
                recommendation=(
                    "Handle the PoisonError explicitly (e.g. `.unwrap_or_else(|e|"
                    " e.into_inner())`), or use parking_lot's Mutex/RwLock, which"
                    " does not poison."
                ),
                locator=f"{payload.file_path}:{call.line}",
            )


__all__ = ["RustMutexLockUnwrapRule"]
