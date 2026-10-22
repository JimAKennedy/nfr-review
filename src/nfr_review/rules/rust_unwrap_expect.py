# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: rust-unwrap-expect — flags .unwrap()/.expect() calls outside test code."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.rust_ast import RustAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class RustUnwrapExpectRule(FieldRule[RustAstFilePayload]):
    """Flag .unwrap()/.expect() calls that panic instead of propagating the error."""

    id = "rust-unwrap-expect"
    collector_name = "rust-ast"
    evidence_kind = "rust-ast-file"
    payload_type = RustAstFilePayload
    pattern_tag = "rust-unwrap-expect"
    required_tech: list[str] = ["rust"]
    default_confidence = 0.85
    all_clear_summary = "No .unwrap()/.expect() calls detected outside test code."

    def check(self, payload: RustAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for call in payload.unwrap_expect_calls:
            if call.in_test:
                continue
            yield Hit(
                rag="amber",
                severity="medium",
                summary=(
                    f"{call.receiver}.{call.method}() panics instead of propagating the error"
                ),
                recommendation=(
                    "Propagate the error with `?`, or handle the `Err`/`None` case"
                    " explicitly, instead of panicking on failure."
                ),
                locator=f"{payload.file_path}:{call.line}",
            )


__all__ = ["RustUnwrapExpectRule"]
