# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-002 — checks header files for include guards or pragma once."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from nfr_review.collectors.payloads.cpp_ast import CppAstFilePayload
from nfr_review.models import Evidence, RuleResult
from nfr_review.rules.framework import FieldRule, Hit

_HEADER_EXTENSIONS = frozenset({".h", ".hpp", ".hxx"})


class CppIncludeGuardsRule(FieldRule[CppAstFilePayload]):
    id = "cpp-include-guards"
    collector_name = "cpp-ast"
    evidence_kind = "cpp-ast-file"
    payload_type = CppAstFilePayload
    pattern_tag = "cpp-missing-include-guard"
    required_tech = ["cpp"]
    default_confidence = 0.95
    all_clear_summary = "All headers have include guards."
    all_clear_tag = "cpp-include-guards-ok"

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        relevant = [
            e
            for e in evidence
            if e.collector_name == self.collector_name and e.kind == self.evidence_kind
        ]
        if not relevant:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason=f"no {self.evidence_kind} evidence available",
            )
        headers = [
            e
            for e in relevant
            if any(
                self._coerce(e.payload).file_path.endswith(ext) for ext in _HEADER_EXTENSIONS
            )
        ]
        if not headers:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no C++ header files in evidence",
            )
        return super().evaluate(evidence, context)

    def check(self, payload: CppAstFilePayload, ev: Evidence) -> Iterable[Hit]:
        if not any(payload.file_path.endswith(ext) for ext in _HEADER_EXTENSIONS):
            return
        if payload.has_pragma_once or payload.has_include_guard:
            yield Hit(
                rag="green",
                severity="info",
                summary="Header has include guard or #pragma once",
                recommendation="No action required.",
                locator=payload.file_path,
                pattern_tag="cpp-include-guards-ok",
            )
        else:
            yield Hit(
                rag="red",
                severity="medium",
                summary="Header missing include guard or #pragma once",
                recommendation=(
                    "Add #pragma once or traditional #ifndef/#define include guards."
                ),
                locator=payload.file_path,
            )


__all__ = ["CppIncludeGuardsRule"]
