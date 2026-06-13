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

from nfr_review.models import Evidence, Finding, RuleResult, compute_content_hash
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
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


class CppRawMemoryRule:
    id = "cpp-raw-memory"
    band: Band = 1
    required_collectors: list[str] = ["cpp-ast"]
    required_tech: list[str] = ["cpp"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        cpp_ev = [e for e in evidence if e.kind == "cpp-ast-file"]
        if not cpp_ev:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no cpp-ast evidence available",
            )

        findings: list[Finding] = []
        has_smart_ptrs = False
        for ev in cpp_ev:
            if ev.payload.get("smart_pointers"):
                has_smart_ptrs = True

            for expr in ev.payload.get("new_expressions", []):
                if _is_ownership_suppressed(expr):
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="green",
                            severity="info",
                            summary=(
                                "Raw new expression suppressed — "
                                "ownership-transfer or REFCOUNT-SAFE annotation."
                            ),
                            recommendation="No action required.",
                            evidence_locator=f"{expr['file']}:{expr['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="cpp-raw-new-suppressed",
                            content_hash=compute_content_hash(expr.get("expression", "")),
                        )
                    )
                    continue
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber" if has_smart_ptrs else "red",
                        severity="medium" if has_smart_ptrs else "high",
                        summary="Raw new expression detected",
                        recommendation=(
                            "Use std::make_unique or std::make_shared instead of raw new."
                        ),
                        evidence_locator=f"{expr['file']}:{expr['line']}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="cpp-raw-new",
                        content_hash=compute_content_hash(expr.get("expression", "")),
                    )
                )

            for expr in ev.payload.get("delete_expressions", []):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary="Raw delete expression detected",
                        recommendation=(
                            "Use smart pointers (unique_ptr/shared_ptr) "
                            "for automatic lifetime management."
                        ),
                        evidence_locator=f"{expr['file']}:{expr['line']}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="cpp-raw-delete",
                        content_hash=compute_content_hash(expr.get("expression", "")),
                    )
                )

            for call in ev.payload.get("malloc_calls", []):
                if call["call"] in ("malloc", "calloc", "realloc"):
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="red",
                            severity="high",
                            summary=f"{call['call']}() usage detected",
                            recommendation=(
                                "Use C++ allocation (new/make_unique) "
                                "instead of C-style malloc."
                            ),
                            evidence_locator=f"{call['file']}:{call['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="cpp-malloc-usage",
                            content_hash=compute_content_hash(call.get("call", "")),
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "cpp-raii-only",
                    cpp_ev[0],
                    summary=(
                        "No raw memory management patterns "
                        "detected — RAII and smart pointers used."
                    ),
                    confidence=0.9,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "cpp-raw-memory" not in rule_registry:
        rule_registry.register("cpp-raw-memory", CppRawMemoryRule())


_register()

__all__ = ["CppRawMemoryRule"]
