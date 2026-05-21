# Copyright 2026 nfr-review contributors
# SPDX-License-Identifier: Apache-2.0
"""Rule: go-defer-in-loop — detects defer statements inside loop bodies."""

from __future__ import annotations

from typing import Any

from nfr_review.models import Evidence, Finding, RuleResult
from nfr_review.protocols import Band
from nfr_review.registry import rule_registry


class GoDeferInLoopRule:
    """Flag defer statements inside for loops that accumulate deferred calls."""

    id = "go-defer-in-loop"
    band: Band = 1
    required_collectors: list[str] = ["go-ast"]

    def evaluate(self, evidence: list[Evidence], context: Any) -> RuleResult:
        go_evidence = [
            e for e in evidence if e.collector_name == "go-ast" and e.kind == "go-ast-file"
        ]
        if not go_evidence:
            return RuleResult(
                rule_id=self.id,
                skipped=True,
                skip_reason="no go-ast evidence available",
            )

        findings: list[Finding] = []
        for ev in go_evidence:
            file_path = ev.payload.get("file_path", ev.locator)
            for stmt in ev.payload.get("defer_statements", []):
                if stmt["in_loop"]:
                    findings.append(
                        Finding(
                            rule_id=self.id,
                            rag="amber",
                            severity="medium",
                            summary=(
                                f"Defer inside loop at line {stmt['line']}"
                                f" accumulates deferred calls"
                            ),
                            recommendation=(
                                "Extract the loop body to a separate function"
                                " or use explicit close instead of defer."
                            ),
                            evidence_locator=f"{file_path}:{stmt['line']}",
                            collector_name=ev.collector_name,
                            collector_version=ev.collector_version,
                            confidence=0.9,
                            pattern_tag="go-defer-in-loop",
                        )
                    )

        if not findings:
            findings.append(
                Finding(
                    rule_id=self.id,
                    rag="green",
                    severity="info",
                    summary="No defer-in-loop patterns detected.",
                    recommendation="No action required.",
                    evidence_locator="project-wide",
                    collector_name=go_evidence[0].collector_name,
                    collector_version=go_evidence[0].collector_version,
                    confidence=0.9,
                    pattern_tag="go-defer-in-loop",
                )
            )

        return RuleResult(rule_id=self.id, findings=findings)


def _register() -> None:
    if "go-defer-in-loop" not in rule_registry:
        rule_registry.register("go-defer-in-loop", GoDeferInLoopRule())


_register()

__all__ = ["GoDeferInLoopRule"]
