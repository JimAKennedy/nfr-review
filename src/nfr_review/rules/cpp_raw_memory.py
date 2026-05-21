# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-001 — detects raw new/delete and malloc/free usage."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


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
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber" if has_smart_ptrs else "red",
                        severity="medium" if has_smart_ptrs else "high",
                        summary=f"Raw new at line {expr['line']} in {expr['file']}",
                        recommendation=(
                            "Use std::make_unique or std::make_shared instead of raw new."
                        ),
                        evidence_locator=f"{expr['file']}:{expr['line']}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="cpp-raw-new",
                    )
                )

            for expr in ev.payload.get("delete_expressions", []):
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="amber",
                        severity="medium",
                        summary=f"Raw delete at line {expr['line']} in {expr['file']}",
                        recommendation=(
                            "Use smart pointers (unique_ptr/shared_ptr) "
                            "for automatic lifetime management."
                        ),
                        evidence_locator=f"{expr['file']}:{expr['line']}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="cpp-raw-delete",
                    )
                )

            for call in ev.payload.get("malloc_calls", []):
                if call["call"] in ("malloc", "calloc", "realloc"):
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="red",
                            severity="high",
                            summary=(
                                f"{call['call']}() at line {call['line']} in {call['file']}"
                            ),
                            recommendation=(
                                "Use C++ allocation (new/make_unique) "
                                "instead of C-style malloc."
                            ),
                            evidence_locator=f"{call['file']}:{call['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="cpp-malloc-usage",
                        )
                    )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary=(
                        "No raw memory management patterns "
                        "detected — RAII and smart pointers used."
                    ),
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=cpp_ev[0].collector_name,
                    collector_version=cpp_ev[0].collector_version,
                    confidence=0.9,
                    pattern_tag="cpp-raii-only",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "cpp-raw-memory" not in rule_registry:
        rule_registry.register("cpp-raw-memory", CppRawMemoryRule())


_register()

__all__ = ["CppRawMemoryRule"]
