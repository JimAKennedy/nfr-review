# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: exception-handling-antipattern.

Catches broad Exception/Throwable without rethrow.
"""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.java_ast import JavaAstFilePayload
from nfr_review.models import Evidence, compute_content_hash
from nfr_review.rules.framework import FieldRule, Hit

_BROAD_TYPES = frozenset({"Exception", "Throwable"})


class ExceptionHandlingAntipatternRule(FieldRule[JavaAstFilePayload]):
    """Flag catch blocks that swallow Exception/Throwable without rethrowing."""

    id = "exception-handling-antipattern"
    collector_name = "java-ast"
    evidence_kind = "java-ast-file"
    payload_type = JavaAstFilePayload
    pattern_tag = "exception-handling"
    default_confidence = 0.85
    all_clear_summary = "No broad exception swallowing detected."
    all_clear_recommendation = "No action required."

    def check(self, payload: JavaAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for block in payload.catch_blocks:
            if block.caught_type in _BROAD_TYPES and not block.rethrows:
                yield Hit(
                    rag="red",
                    severity="high",
                    summary=f"Broad catch({block.caught_type}) without rethrow",
                    recommendation=(
                        "Catch specific exception types or"
                        " rethrow to preserve stack trace"
                        " visibility."
                    ),
                    locator=f"{payload.file_path}:{block.line}",
                    content_hash=compute_content_hash(block.caught_type),
                )


__all__ = ["ExceptionHandlingAntipatternRule"]
