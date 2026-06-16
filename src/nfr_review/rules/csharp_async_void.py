# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: csharp-async-void — detects async void methods in C# code."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class CSharpAsyncVoidRule:
    """Flag async void methods that should be async Task."""

    id = "csharp-async-void"
    band: Band = 1
    required_collectors: list[str] = ["csharp-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        cs_evidence = filter_evidence(evidence, "csharp-ast", "csharp-ast-file")
        if not cs_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no csharp-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in cs_evidence:
            file_path = ev.payload.file_path
            for method in ev.payload.methods:
                if method["is_async"] and method["return_type"] == "void":
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="red",
                            severity="high",
                            summary=f"async void method '{method['name']}'",
                            recommendation=(
                                "Change return type to async Task. async void"
                                " silently swallows exceptions and cannot be awaited."
                            ),
                            evidence_locator=f"{file_path}:{method['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.95,
                            pattern_tag="csharp-async-void",
                        )
                    )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "csharp-async-void",
                    cs_evidence[0],
                    summary="No async void methods detected.",
                    confidence=0.9,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "csharp-async-void" not in rule_registry:
        rule_registry.register("csharp-async-void", CSharpAsyncVoidRule())


_register()

__all__ = ["CSharpAsyncVoidRule"]
