# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-001 — detects raw new/delete and malloc/free usage.

Ownership-transfer suppression: ``new`` inside a call to an ownership-
transfer function (e.g. ``addView``, ``addParameter``) or annotated with
a ``// REFCOUNT-SAFE`` line comment is treated as intentional and emits
a green finding instead of amber/red.
"""

from __future__ import annotations

import re
from typing import Any

from nfr_review.collectors.payloads.cpp_ast import CppAstFilePayload
from nfr_review.models import Evidence, Finding, RuleResult, compute_content_hash
from nfr_review.rules.framework import FieldRule, Hit, make_finding
from nfr_review.rules.rule_helpers import make_green_finding

_OWNERSHIP_TRANSFER_RE = re.compile(
    r"(?i)^(add(View|Parameter|Component|Unit|SubController|Entry|Animation)"
    r"|remove(View|Component)|replace(View|Component)"
    r"|attach(View|TextEdit)|registerController"
    r"|shared|owned|makeOwned"
    r"|create(Instance|View|Controller)?)"
    r"$"
)

_SUPPRESS_COMMENT_RE = re.compile(r"(?i)REFCOUNT[- _]?SAFE|NOLINT|ownership.transfer")


def _is_ownership_suppressed(expr: dict[str, Any]) -> bool:
    parent = expr.get("parent_call", "")
    if parent and _OWNERSHIP_TRANSFER_RE.match(parent):
        return True
    comment = expr.get("line_comment", "")
    if comment and _SUPPRESS_COMMENT_RE.search(comment):
        return True
    return False


class CppRawMemoryRule(FieldRule[CppAstFilePayload]):
    id = "cpp-raw-memory"
    collector_name = "cpp-ast"
    evidence_kind = "cpp-ast-file"
    payload_type = CppAstFilePayload
    pattern_tag = "cpp-raw-new"
    required_tech = ["cpp"]
    default_confidence = 0.9
    all_clear_summary = (
        "No raw memory management patterns detected — RAII and smart pointers used."
    )

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        relevant = [e for e in evidence if e.kind == self.evidence_kind]
        if not relevant:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no cpp-ast evidence available",
            )

        findings: list[Finding] = []
        has_smart_ptrs = False
        for ev in relevant:
            payload = ev.payload
            if payload.smart_pointers:
                has_smart_ptrs = True

            for expr in payload.new_expressions:
                if _is_ownership_suppressed(expr):
                    findings.append(
                        make_finding(
                            rule_id=self.id,
                            hit=Hit(
                                rag="green",
                                severity="info",
                                summary=(
                                    "Raw new expression suppressed — "
                                    "ownership-transfer or REFCOUNT-SAFE annotation."
                                ),
                                recommendation="No action required.",
                                locator=f"{expr['file']}:{expr['line']}",
                                content_hash=compute_content_hash(expr.get("expression", "")),
                            ),
                            ev=ev,
                            pattern_tag="cpp-raw-new-suppressed",
                            default_confidence=self.default_confidence,
                        )
                    )
                    continue
                findings.append(
                    make_finding(
                        rule_id=self.id,
                        hit=Hit(
                            rag="amber" if has_smart_ptrs else "red",
                            severity="medium" if has_smart_ptrs else "high",
                            summary="Raw new expression detected",
                            recommendation=(
                                "Use std::make_unique or std::make_shared instead of raw new."
                            ),
                            locator=f"{expr['file']}:{expr['line']}",
                            content_hash=compute_content_hash(expr.get("expression", "")),
                        ),
                        ev=ev,
                        pattern_tag="cpp-raw-new",
                        default_confidence=self.default_confidence,
                    )
                )

            for expr in payload.delete_expressions:
                findings.append(
                    make_finding(
                        rule_id=self.id,
                        hit=Hit(
                            rag="amber",
                            severity="medium",
                            summary="Raw delete expression detected",
                            recommendation=(
                                "Use smart pointers (unique_ptr/shared_ptr) "
                                "for automatic lifetime management."
                            ),
                            locator=f"{expr['file']}:{expr['line']}",
                            content_hash=compute_content_hash(expr.get("expression", "")),
                        ),
                        ev=ev,
                        pattern_tag="cpp-raw-delete",
                        default_confidence=self.default_confidence,
                    )
                )

            for call in payload.malloc_calls:
                if call["call"] in ("malloc", "calloc", "realloc"):
                    findings.append(
                        make_finding(
                            rule_id=self.id,
                            hit=Hit(
                                rag="red",
                                severity="high",
                                summary=f"{call['call']}() usage detected",
                                recommendation=(
                                    "Use C++ allocation (new/make_unique) "
                                    "instead of C-style malloc."
                                ),
                                locator=f"{call['file']}:{call['line']}",
                                content_hash=compute_content_hash(call.get("call", "")),
                            ),
                            ev=ev,
                            pattern_tag="cpp-malloc-usage",
                            default_confidence=self.default_confidence,
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "cpp-raii-only",
                    relevant[0],
                    summary=(
                        "No raw memory management patterns "
                        "detected — RAII and smart pointers used."
                    ),
                    confidence=0.9,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


__all__ = ["CppRawMemoryRule"]
