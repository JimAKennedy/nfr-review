# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: csharp-blocking-async — detects blocking on async results."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry
from nfr_review.rules.rule_helpers import filter_evidence, make_green_finding


class CSharpBlockingAsyncRule:
    """Flag synchronous blocking on async operations that risk thread pool starvation."""

    id = "csharp-blocking-async"
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
            for call in ev.payload.blocking_calls:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        rag="red",
                        severity="high",
                        summary=f"Blocking call {call['call_type']}",
                        recommendation=(
                            "Use await instead of blocking synchronously on async"
                            " operations. Blocking risks thread pool starvation"
                            " and deadlocks."
                        ),
                        evidence_locator=f"{file_path}:{call['line']}",
                        collector_name=ev.collector_name,
                        collector_version=ev.collector_version,
                        confidence=0.9,
                        pattern_tag="csharp-blocking-async",
                    )
                )

        if not findings:
            findings.append(
                make_green_finding(
                    self.id,
                    "csharp-blocking-async",
                    cs_evidence[0],
                    summary="No blocking calls on async operations detected.",
                    confidence=0.9,
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "csharp-blocking-async" not in rule_registry:
        rule_registry.register("csharp-blocking-async", CSharpBlockingAsyncRule())


_register()

__all__ = ["CSharpBlockingAsyncRule"]
