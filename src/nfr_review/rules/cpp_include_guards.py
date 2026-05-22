# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: CPP-002 — checks header files for include guards or pragma once."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry

_HEADER_EXTENSIONS = frozenset({".h", ".hpp", ".hxx"})


class CppIncludeGuardsRule:
    id = "cpp-include-guards"
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

        headers = [
            e
            for e in cpp_ev
            if any(e.payload.get("file_path", "").endswith(ext) for ext in _HEADER_EXTENSIONS)
        ]
        if not headers:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no C++ header files found",
            )

        findings: list[Finding] = []
        for ev in headers:
            file_path = ev.payload.get("file_path", ev.locator)
            has_pragma = ev.payload.get("has_pragma_once", False)
            has_guard = ev.payload.get("has_include_guard", False)
            if not has_pragma and not has_guard:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="medium",
                        summary="Header missing include guard or #pragma once",
                        recommendation=(
                            "Add #pragma once or traditional #ifndef/#define include guards."
                        ),
                        evidence_locator=file_path,
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.95,
                        pattern_tag="cpp-missing-include-guard",
                    )
                )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="All headers have include guards.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=headers[0].collector_name,
                    collector_version=headers[0].collector_version,
                    confidence=0.95,
                    pattern_tag="cpp-include-guards-ok",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "cpp-include-guards" not in rule_registry:
        rule_registry.register("cpp-include-guards", CppIncludeGuardsRule())


_register()

__all__ = ["CppIncludeGuardsRule"]
