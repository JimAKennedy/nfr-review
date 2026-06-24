# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-003 — detects exception safety issues: catch-all without rethrow."""

from __future__ import annotations

from collections.abc import Iterable

from nfr_review.collectors.payloads.cpp_ast import CppAstFilePayload
from nfr_review.models import Evidence
from nfr_review.rules.framework import FieldRule, Hit


class CppExceptionSafetyRule(FieldRule[CppAstFilePayload]):
    id = "cpp-exception-safety"
    collector_name = "cpp-ast"
    evidence_kind = "cpp-ast-file"
    payload_type = CppAstFilePayload
    pattern_tag = "cpp-catch-all-silent"
    required_tech = ["cpp"]
    default_confidence = 0.85
    all_clear_summary = "No exception safety issues detected."
    all_clear_tag = "cpp-exception-safety-ok"

    def check(self, payload: CppAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        for block in payload.catch_blocks:
            if "..." in block.caught_type and not block.rethrows:
                yield Hit(
                    rag="amber",
                    severity="medium",
                    summary="catch(...) without rethrow",
                    recommendation=(
                        "Catch specific exception types or rethrow with 'throw;' "
                        "to avoid silently swallowing errors."
                    ),
                    locator=f"{block.file}:{block.line}",
                )


__all__ = ["CppExceptionSafetyRule"]
